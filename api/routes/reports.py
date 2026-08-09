from __future__ import annotations

import json
import logging
import math
import os
import queue
import threading
from typing import Any, Callable, Dict, Optional, Tuple
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from api.contracts import ReportGenerateRequest, ReportGenerateResponse
from api.dependencies import get_current_user
from api.routes.datasets import _仓储
from 后端_核心.上传报表生成器 import 生成报表数据
from 后端_核心.agent.多智能体 import 多智能体分析
from config.settings import EnvConfig, LLMRequestConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])

# B1 修复：PDF 中文字体模块级一次性注册（多次导出不重复注册；非 Windows 无
# C:/Windows/Fonts/msyh.ttc 时回退内置 Helvetica，避免导出必 500）
_PDF_FONT = "Helvetica"
try:
    from reportlab.pdfbase import pdfmetrics as _pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont as _TTFont
    if os.path.exists("C:/Windows/Fonts/msyh.ttc"):
        _pdfmetrics.registerFont(_TTFont("MSYH", "C:/Windows/Fonts/msyh.ttc"))
        _PDF_FONT = "MSYH"
except Exception:  # noqa: BLE001
    logger.warning("微软雅黑字体不可用，PDF 导出回退内置 Helvetica")

# SSE 直播全局并发上限：每个流式请求 spawn 一个后台线程做 LLM 分析，
# 无限制并发会占满 FastAPI 线程池（DoS）。超出上限直接 503 拒绝。
_STREAM_SEMAPHORE = threading.BoundedSemaphore(4)
# SSE 事件队列上限：trace 单请求最多 ~20 条 + done/error/sentinel，64 足够且防堆积
_STREAM_QUEUE_MAX = 64


def _json_safe(obj: Any) -> Any:
    """递归清洗非有限浮点（NaN/Infinity），保证 SSE 事件输出合法 JSON。"""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    return obj


# ── 公共校验 ──────────────────────────────────────────────────────────────────


def _准备上下文(
    payload: ReportGenerateRequest,
    request: Request,
    user: dict,
) -> Tuple[Any, LLMRequestConfig]:
    """校验数据集存在 + LLM 白名单，返回 (df, llm_config)。generate / generate-stream 共用。

    从 request.headers 读取 LLM provider / model / BYOK key（白名单校验）。
    """
    item = _仓储.读取(user["user_id"], payload.数据集ID)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")

    df = item["数据"]

    # LLM 配置：推荐预设（白名单）或用户自定义供应商（自担风险 BYOK）
    user_provider = (request.headers.get("x-llm-provider") or "deepseek").strip().lower()
    user_model = (request.headers.get("x-llm-model") or "").strip() or payload.model or ""

    providers = getattr(EnvConfig, "LLM_PROVIDERS", {})
    provider_conf = providers.get(user_provider)
    # 用户自定义供应商：base_url/key 来自账号存储（参考 Reasonix 自定义供应商）
    custom_api_key = ""
    is_custom = False
    if not provider_conf:
        from repositories import user_repo as _ur
        custom_conf = next(
            (p for p in _ur.读取自定义供应商(user["user_id"]) if p.get("name") == user_provider),
            None,
        )
        if custom_conf:
            # P0 加固：SSRF 防护——历史入库的 base_url 也要校验（含内网/云元数据拒绝）
            from services.llm_security import 校验LLM供应商URL
            try:
                base_url = 校验LLM供应商URL(custom_conf["base_url"])
            except ValueError as exc:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
            provider_conf = {
                "base_url": base_url,
                "default_model": custom_conf.get("default", "") or "",
                "models": custom_conf.get("models") or [],
            }
            custom_api_key = custom_conf.get("api_key", "")
            is_custom = True
    if not provider_conf:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的 LLM provider：{user_provider}",
        )

    allowed_models = provider_conf.get("models") or [provider_conf.get("default_model", "")]
    if user_model and user_model not in allowed_models:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"provider {user_provider} 不支持模型：{user_model}",
        )

    # BYOK：不存后端、不进日志；不传则回退服务端 .env。自定义供应商 URL 由用户自担风险。
    user_api_key = (request.headers.get("x-llm-api-key") or "").strip()
    if len(user_api_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API Key 格式不合法",
        )
    # 优先级：请求头 X-LLM-API-Key > 账号绑定 key > 自定义供应商 key > provider env key > .env
    if not user_api_key:
        from repositories import user_repo as _user_repo
        user_api_key = _user_repo.读取LLMKey(user["user_id"])
    if not user_api_key and custom_api_key:
        user_api_key = custom_api_key
    # provider 级 Key（api_key_env 对应环境变量，参考 Reasonix 接入方式）
    if not user_api_key and provider_conf.get("api_key_env"):
        user_api_key = os.getenv(provider_conf["api_key_env"], "")
    # P0 加固：自定义供应商绝不回退服务端 .env 密钥（防服务端 LLM_API_KEY 外泄到用户控制的 URL）
    if is_custom and not user_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="自定义 LLM 供应商必须提供 API Key（请求头 / 账号 Key / 供应商自带 Key）",
        )
    llm_config = LLMRequestConfig(
        provider=user_provider,
        base_url=provider_conf["base_url"],
        model=user_model or provider_conf.get("default_model", ""),
        api_key=user_api_key or EnvConfig.LLM_API_KEY,
    )
    return df, llm_config


def _注入追问上下文(
    payload: ReportGenerateRequest,
    user: dict,
) -> ReportGenerateRequest:
    """多轮追问：带 上一报表ID 时回溯最近 N 份报表摘要，作为上下文拼进分析需求。

    追问是「针对上一轮继续分析」——携带追问链上每轮的 需求原文 / 图表配置 / 结论
    （最近一份附数据样例），让 LLM 与规则匹配能接着整段对话语境作答
    （如"那华南呢？"→ 沿用维度换过滤条件；连续追问 3 轮以上不丢前文）。
    跨用户读取上一报表 → 404；链上某份已被删除则截断到已读部分。

    Token 预算（阶段 27）：
    - 需求原文取报表「标题」（落库时为用户原话），而非「分析需求」字段——
      后者是注入后的全量上下文，若回溯时再取它会指数膨胀（第 N 轮含前 N-1 轮全文）；
    - 累计字符预算 1500（中文约 1 token/字），超预算的较早轮次降级为一行摘要
      （「第 N 轮『原话』：图表类型」），最新一轮始终保留结论+样例。
    """
    if not payload.上一报表ID:
        return payload

    payload.原始分析需求 = payload.分析需求

    from repositories import report_repo
    # 回溯最近 N 份（从最新向前），最后逆转为 旧→新 对话顺序
    N = 3
    chain = []
    rid = payload.上一报表ID
    seen = set()
    while rid and len(chain) < N and rid not in seen:
        seen.add(rid)
        item = report_repo.读取报表(user["user_id"], rid)
        if not item:
            if not chain:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上一轮报表不存在或无权访问")
            break  # 追溯链中断（中间某份已删）：保留已回溯部分
        chain.append(item)
        rid = item["报表"].get("上一报表ID")
    chain.reverse()

    # 字符预算（粗估 token 成本）；_结论截断 防单条超长 LLM 结论撑爆上下文
    MAX_CHARS = 1500
    结论截断 = 200

    lines = ["【上一轮分析上下文】（本次是针对上一轮的追问，可参考但不能照抄）"]
    used = 0
    for idx, item in enumerate(chain, 1):
        prev = item["报表"]
        配置 = prev.get("图表配置", {})
        # 需求原文用标题（用户原话）——绝不回填注入后的「分析需求」，防指数膨胀
        需求原文 = (prev.get("标题") or "未命名").strip()[:120]
        图表行 = (
            f"- 第 {idx} 轮「{需求原文}」："
            f"图表 {prev.get('图表类型', '') or '自动'}（X 轴：{配置.get('X轴') or '-'}，"
            f"Y 轴：{'、'.join(配置.get('Y轴') or []) or '-'}，分组：{配置.get('颜色') or '-'}）"
        )
        结论 = prev.get("结论")
        结论行 = f"  结论：{str(结论)[:结论截断]}" if 结论 else ""
        样例行 = ""
        if idx == len(chain):  # 仅最近一份附数据样例
            数据 = prev.get("报表数据", [])
            if 数据:
                import json
                样例行 = f"  数据样例（前 5 条）：{json.dumps(数据[:5], ensure_ascii=False)}"

        cost = len(图表行) + len(结论行) + len(样例行)
        # 超预算且非最新轮：只保留一行主题摘要（链头不丢，细节让位给最新语境）
        if used + cost > MAX_CHARS and idx != len(chain):
            lines.append(图表行)
            used += len(图表行)
            continue
        lines.append(图表行)
        used += len(图表行)
        if 结论行:
            lines.append(结论行)
            used += len(结论行)
        if 样例行:
            lines.append(样例行)
            used += len(样例行)

    payload.分析需求 = "\n".join(lines) + f"\n\n用户追问：{payload.分析需求}"
    return payload


def _生成报表流式(
    payload: ReportGenerateRequest,
    df: Any,
    llm_config: LLMRequestConfig,
    user: dict,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """生成报表 + 持久化；on_event 实时推送决策事件（SSE 直播）。返回 (report_id, report)。"""
    payload = _注入追问上下文(payload, user)
    if payload.agent_mode == "multi":
        report = _多智能体报表(df, payload, llm_config, on_event=on_event, user_id=user["user_id"])
    else:
        report = _单Agent报表(df, payload, llm_config, on_event=on_event, user_id=user["user_id"])

    # 追溯信息落库：追问来源 + 生成模式（重放/溯源时使用）
    report["上一报表ID"] = payload.上一报表ID
    report["agent_mode"] = payload.agent_mode
    # 追问报表标题用用户原话（避免被注入的上下文污染）
    if payload.原始分析需求:
        report["标题"] = payload.原始分析需求.strip()

    # P1 加固：LLM 用量统计（成本可见性）——从 Agent Trace 汇总 token 写入 llm_usage
    try:
        from repositories import usage_repo
        _p = _c = 0
        for _step in report.get("Agent Trace") or []:
            _t = _step.get("token") or {}
            _p += int(_t.get("prompt_tokens") or 0)
            _c += int(_t.get("completion_tokens") or 0)
        if _p or _c:
            usage_repo.记录用量(user["user_id"], llm_config.provider, llm_config.model, _p, _c)
    except Exception as _exc:
        logger.warning("记录 LLM 用量失败: %s", _exc)

    # 报表持久化到后端（阶段 6）
    from repositories import report_repo
    report_id = report_repo.保存报表(
        user_id=user["user_id"],
        dataset_id=payload.数据集ID,
        title=report.get("标题", ""),
        chart_type=report.get("图表类型", ""),
        report=report,
    )
    if on_event:
        on_event({"type": "done", "报表ID": report_id, "标题": report.get("标题", "")})
    return report_id, report


# ── 端点 ──────────────────────────────────────────────────────────────────────


@router.post("/generate", response_model=ReportGenerateResponse)
async def generate_report(
    payload: ReportGenerateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> ReportGenerateResponse:
    # P0 加固：与流式共享并发信号量，超出立即 503（非流式端点曾不受限，可并发刷爆）
    if not _STREAM_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="当前分析任务已满（并发上限 4），请稍后重试",
        )
    try:
        df, llm_config = _准备上下文(payload, request, user)
        try:
            report_id, report = _生成报表流式(payload, df, llm_config, user)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        return _构建响应(payload, report, report_id)
    finally:
        _STREAM_SEMAPHORE.release()


@router.post("/generate-stream")
def generate_report_stream(
    payload: ReportGenerateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """分析直播：SSE 流式返回实时 Agent 决策事件，最后一条为 done/error。

    事件格式：``data: {json}\\n\\n``
    - ``{"type": "step", "data": {…}}``  trace 每记录一步实时推送
    - ``{"type": "done", "报表ID": "…", "标题": "…"}`` 分析完成
    - ``{"type": "error", "message": "…"}``     分析失败
    """
    # 先在同步上下文中完成鉴权 + 校验（失败直接 400/404）
    df, llm_config = _准备上下文(payload, request, user)

    # 并发控制：超出上限立即 503，避免后台线程无限堆积
    if not _STREAM_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="分析任务繁忙，请稍后重试",
        )

    event_q: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(maxsize=_STREAM_QUEUE_MAX)

    def _push(ev: Optional[Dict[str, Any]]) -> None:
        # 队列满说明客户端已断开且无人消费：丢弃事件，绝不阻塞 worker，
        # 保证 finally 必达（并发名额必释放，不会永久 503）
        try:
            event_q.put_nowait(ev)
        except queue.Full:
            pass

    def worker() -> None:
        try:
            _生成报表流式(payload, df, llm_config, user, on_event=_push)
        except ValueError as exc:
            # 参数/字段问题（词云无词、桑基缺分组）→ 可给用户看的明确提示
            logger.warning("报表流式生成参数不满足: %s", exc)
            _push({"type": "error", "message": str(exc)})
        except Exception as exc:  # noqa: BLE001 - SSE 错误统一走事件通道
            # 内部异常只记日志，对外返回通用消息（避免泄露路径/堆栈/数据细节）
            logger.exception("报表流式生成失败")
            _push({"type": "error", "message": "分析失败，请检查参数后重试"})
        finally:
            _push(None)  # 结束哨兵
            _STREAM_SEMAPHORE.release()

    threading.Thread(target=worker, daemon=True).start()

    def event_stream():
        # 注意：并发名额只由 worker 释放（含客户端断开后 worker 自然结束的场景），
        # 这里不再 release，避免 BoundedSemaphore 双释放抛 ValueError。
        while True:
            ev = event_q.get()
            if ev is None:
                break
            yield f"data: {json.dumps(_json_safe(ev), ensure_ascii=False, default=str, allow_nan=False)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 历史 ──────────────────────────────────────────────────────────────────────


@router.get("/")
def list_reports(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出当前用户的报表历史（支持分页）。"""
    from repositories import report_repo
    return {"报表列表": report_repo.列出报表(user["user_id"], limit=limit, offset=offset)}


@router.get("/{report_id}")
def get_report(report_id: str, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """读取一份报表详情（仅限归属用户）。附追溯信息：追问来源报表的标题。"""
    from repositories import report_repo
    item = report_repo.读取报表(user["user_id"], report_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表不存在")
    result = dict(item)
    prev_id = item["报表"].get("上一报表ID")
    if prev_id:
        prev = report_repo.读取报表(user["user_id"], prev_id)
        result["上一报表标题"] = prev["标题"] if prev else ""
    return result


@router.get("/{report_id}/export")
def export_report(
    report_id: str,
    format: str = Query("xlsx", pattern="^(xlsx|csv|pdf)$"),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """导出报表：xlsx / csv / pdf（仅限归属用户）。"""
    # P2 加固：数据导出属敏感操作，记审计
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "导出报表", target_type="report", target_id=report_id, detail=f"format={format}")
    import io
    from urllib.parse import quote

    import pandas as pd
    from repositories import report_repo

    item = report_repo.读取报表(user["user_id"], report_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表不存在")
    report = item["报表"]
    rows = report.get("报表数据", [])
    标题 = (item["标题"] or "报表").replace('"', '').replace('\\', '_')
    buf = io.BytesIO()

    if format == "xlsx":
        pd.DataFrame(rows).to_excel(buf, index=False, engine="openpyxl")
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename=report.xlsx; filename*=UTF-8''{quote(f'{标题}.xlsx')}"},
        )
    if format == "csv":
        # P1 加固：CSV 公式注入——以 = + - @ 开头的单元格加前缀 '（防 Excel 打开执行公式）
        import re as _re
        _危险前缀 = _re.compile(r"^[=+\-@]")
        esc_rows = [
            {k: ("'" + v if isinstance(v, str) and _危险前缀.match(v) else v) for k, v in row.items()}
            for row in rows
        ]
        pd.DataFrame(esc_rows).to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=report.csv; filename*=UTF-8''{quote(f'{标题}.csv')}"},
        )
    # PDF（reportlab + 中文字体；字体模块级注册 _PDF_FONT，多次导出不重复注册）
    import html  # P0 加固：Paragraph 按 HTML 子集解析，数据须转义防 <img> 任意文件读取/注入
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def _esc(value) -> str:
        """全部用户/数据内容进入 Paragraph 前转义（防 reportlab 解析 tags 与文件引用）。"""
        return html.escape(str(value), quote=False)

    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["Normal"], fontName=_PDF_FONT, fontSize=10, leading=15)
    title = ParagraphStyle("Title", parent=styles["Title"], fontName=_PDF_FONT, fontSize=16, leading=22)
    head = ParagraphStyle("Head", parent=styles["Heading2"], fontName=_PDF_FONT, fontSize=11, leading=16, spaceBefore=10)

    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = [Paragraph(f"报表：{_esc(标题)}", title), Spacer(1, 8)]
    story.append(Paragraph(f"图表类型：{_esc(report.get('图表类型', ''))} · 意图来源：{_esc(report.get('意图来源', ''))}", body))
    story.append(Spacer(1, 6))
    if report.get("结论"):
        story.append(Paragraph("分析结论", head))
        story.append(Paragraph(_esc(report["结论"]), body))
    if rows:
        story.append(Paragraph("数据明细", head))
        cols = list(rows[0].keys())
        data = [[Paragraph(_esc(c), body) for c in cols]]
        for row in rows[:200]:
            data.append([Paragraph(_esc(row.get(c, "")), body) for c in cols])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("FONTNAME", (0, 0), (-1, -1), _PDF_FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(table)
    推荐 = report.get("推荐说明", {}).get("理由", [])
    if 推荐:
        story.append(Paragraph("推荐依据", head))
        for r in 推荐:
            story.append(Paragraph(f"· {_esc(r)}", body))
    风险 = report.get("风险提示", [])
    if 风险:
        story.append(Paragraph("注意事项", head))
        for w in 风险:
            story.append(Paragraph(f"· {_esc(w)}", body))
    doc.build(story)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=report.pdf; filename*=UTF-8''{quote(f'{标题}.pdf')}"},
    )


@router.delete("/{report_id}")
def delete_report(report_id: str, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """删除一份报表（仅限归属用户）。"""
    from repositories import report_repo
    if not report_repo.删除报表(user["user_id"], report_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表不存在")
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "删除报表", target_type="report", target_id=report_id)
    return {"message": "已删除"}


# ── 分享（批次 6：带权限的只读分享链接）──────────────────────────────────────


def _确认报表归属(user_id: str, report_id: str) -> None:
    """校验报表存在且归属该用户；否则 404。"""
    from repositories import report_repo
    if not report_repo.读取报表(user_id, report_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表不存在")


@router.post("/{report_id}/share")
def 创建分享链接(
    report_id: str,
    有效小时数: int = Query(24, ge=1, le=720),
    密码: str = Query("", max_length=32, description="可选访问密码，空=无需密码"),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """为报表创建分享链接（仅创建者）。返回可公开访问的只读链接。"""
    _确认报表归属(user["user_id"], report_id)
    from repositories import share_repo
    info = share_repo.创建分享(user["user_id"], report_id, 有效小时数, 密码.strip())
    return {
        "链接ID": info["share_id"],
        "分享链接": f"/s/{info['share_id']}",
        "过期时间": info["过期时间"],
        "需密码": info["需密码"],
    }


@router.get("/{report_id}/shares")
def 列出分享链接(
    report_id: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出报表的全部分享链接（仅创建者）。"""
    _确认报表归属(user["user_id"], report_id)
    from repositories import share_repo
    return {"分享列表": share_repo.按报表列出(user["user_id"], report_id)}


@router.delete("/{report_id}/share/{share_id}")
def 撤销分享链接(
    report_id: str,
    share_id: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, str]:
    """撤销分享（仅创建者）；报表或链接不存在 → 404。"""
    _确认报表归属(user["user_id"], report_id)
    from repositories import share_repo
    if not share_repo.撤销分享(user["user_id"], share_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享链接不存在")
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "撤销分享", target_type="share", target_id=share_id, detail=report_id)
    return {"message": "已撤销"}


# ── 重放（批次 7：分析历史重放）───────────────────────────────────────────────


@router.post("/{report_id}/replay", response_model=ReportGenerateResponse)
def 重放报表(
    report_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> ReportGenerateResponse:
    """用原报表的分析需求与字段配置重新执行生成（复现分析过程）。

    读取原报表（归属校验）→ 用其 分析需求/图表类型/X轴/Y轴/分组 走标准生成链路，
    生成一份全新的报表（保留原 trace 语义、产生新 trace）。数据集已删 → 404。
    """
    from repositories import report_repo

    item = report_repo.读取报表(user["user_id"], report_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表不存在")

    prev = item["报表"]
    配置 = prev.get("图表配置", {})
    payload = ReportGenerateRequest(
        数据集ID=item["数据集ID"],
        分析需求=prev.get("分析需求") or prev.get("标题", ""),
        图表类型=prev.get("图表类型", "自动推荐"),
        x轴=配置.get("X轴") or None,
        y轴=list(配置.get("Y轴") or []),
        分组字段=配置.get("颜色") or None,
        聚合方式="求和",
        # 保留原生成模式（多智能体报表重放不再降级为单 Agent）
        agent_mode=prev.get("agent_mode", "single"),
    )

    # P0 加固：与流式共享并发信号量（replay 同样消耗 LLM/线程资源）
    if not _STREAM_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="当前分析任务已满（并发上限 4），请稍后重试",
        )
    try:
        df, llm_config = _准备上下文(payload, request, user)
        try:
            new_id, new_report = _生成报表流式(payload, df, llm_config, user)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return _构建响应(payload, new_report, new_id)
    finally:
        _STREAM_SEMAPHORE.release()


# ── 生成 ──────────────────────────────────────────────────────────────────────


def _单Agent报表(
    df: Any,
    payload: ReportGenerateRequest,
    llm_config: LLMRequestConfig,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    user_id: str = "",
) -> Dict[str, Any]:
    """标准单 Agent 生成报表。"""
    return 生成报表数据(
        df=df,
        分析需求=payload.分析需求,
        图表类型=payload.图表类型,
        x轴=payload.x轴,
        y轴=payload.y轴,
        分组字段=payload.分组字段,
        聚合方式=payload.聚合方式,
        llm_config=llm_config,
        on_event=on_event,
        user_id=user_id,
    )


def _多智能体报表(
    df: Any,
    payload: ReportGenerateRequest,
    llm_config: LLMRequestConfig,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    user_id: str = "",
) -> Dict[str, Any]:
    """多智能体模式生成报表。"""
    from 后端_核心.数据画像 import 生成数据画像
    画像 = 生成数据画像(df)
    result = 多智能体分析(画像, payload.分析需求, df, llm_config=llm_config, on_event=on_event)
    if not result:
        # 降级到单 Agent
        logger.warning("多智能体失败，降级到单 Agent")
        return 生成报表数据(
            df=df,
            分析需求=payload.分析需求,
            图表类型=payload.图表类型,
            x轴=payload.x轴,
            y轴=payload.y轴,
            分组字段=payload.分组字段,
            聚合方式=payload.聚合方式,
            llm_config=llm_config,
            on_event=on_event,
            user_id=user_id,
        )

    # 用多智能体返回的意图走标准报表链路
    return 生成报表数据(
        df=df,
        分析需求=payload.分析需求,
        图表类型=result.get("图表类型", "自动推荐"),
        x轴=result.get("x轴"),
        y轴=result.get("y轴", []),
        分组字段=result.get("分组字段"),
        聚合方式=result.get("聚合方式", "求和"),
        llm_config=llm_config,
        on_event=on_event,
        user_id=user_id,
    )


# ── 响应构建 ──────────────────────────────────────────────────────────────────


def _构建响应(payload: ReportGenerateRequest, report: Dict[str, Any], report_id: str = "") -> ReportGenerateResponse:
    报告_rows = report["报表数据"]
    return ReportGenerateResponse(
        报表ID=report_id or uuid4().hex,
        数据集ID=payload.数据集ID,
        标题=report["标题"],
        图表类型=report["图表类型"],
        图表配置=report["图表配置"],
        报表数据=报告_rows,
        数据画像=report["数据画像"],
        推荐说明=report["推荐说明"],
        风险提示=report["风险提示"],
        **{"Agent Trace": report["Agent Trace"]},
        导出数据=report["导出数据"],
        结论=report["结论"],
        意图来源=report.get("意图来源", "无"),
        LLM失败原因=report.get("LLM失败原因", ""),
        agent_mode=payload.agent_mode,
    )
