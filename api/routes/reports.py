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
    if not provider_conf:
        from repositories import user_repo as _ur
        custom_conf = next(
            (p for p in _ur.读取自定义供应商(user["user_id"]) if p.get("name") == user_provider),
            None,
        )
        if custom_conf:
            provider_conf = {
                "base_url": custom_conf["base_url"],
                "default_model": custom_conf.get("default", "") or "",
                "models": custom_conf.get("models") or [],
            }
            custom_api_key = custom_conf.get("api_key", "")
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
    """多轮追问：带 上一报表ID 时读取上一份报表摘要，作为上下文拼进分析需求。

    追问是「针对上一轮继续分析」——携带上一轮标题 / 图表配置 / 结论 / 数据样例，
    让 LLM 与规则匹配都能接着上一轮的语境作答（如"那华南呢？"→ 沿用维度换过滤条件）。
    跨用户读取上一报表 → 404。
    """
    if not payload.上一报表ID:
        return payload

    from repositories import report_repo
    item = report_repo.读取报表(user["user_id"], payload.上一报表ID)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="上一轮报表不存在或无权访问")

    prev = item["报表"]
    配置 = prev.get("图表配置", {})
    lines = ["【上一轮分析上下文】（本次是针对上一轮的追问，可参考但不能照抄）"]
    lines.append(f"- 标题：{(item.get('标题') or '') or '未命名'}")
    lines.append(
        f"- 图表：{prev.get('图表类型', '') or '自动'}（X 轴：{配置.get('x轴') or '-'}，"
        f"Y 轴：{'、'.join(配置.get('y轴') or []) or '-'}，分组：{配置.get('分组字段') or '-'}，"
        f"聚合：{配置.get('聚合方式') or '-'}）"
    )
    结论 = prev.get("结论")
    if 结论:
        lines.append(f"- 上一轮结论：{结论}")
    数据 = prev.get("报表数据", [])
    if 数据:
        import json
        lines.append(f"- 上一轮数据样例（前 5 条）：{json.dumps(数据[:5], ensure_ascii=False)}")

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
        report = _多智能体报表(df, payload, llm_config, on_event=on_event)
    else:
        report = _单Agent报表(df, payload, llm_config, on_event=on_event)

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
    df, llm_config = _准备上下文(payload, request, user)
    try:
        report_id, report = _生成报表流式(payload, df, llm_config, user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _构建响应(payload, report, report_id)


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
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """列出当前用户的报表历史。"""
    from repositories import report_repo
    return {"报表列表": report_repo.列出报表(user["user_id"], limit=limit)}


@router.get("/{report_id}")
def get_report(report_id: str, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """读取一份报表详情（仅限归属用户）。"""
    from repositories import report_repo
    item = report_repo.读取报表(user["user_id"], report_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表不存在")
    return item


@router.get("/{report_id}/export")
def export_report(
    report_id: str,
    format: str = Query("xlsx", pattern="^(xlsx|csv|pdf)$"),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """导出报表：xlsx / csv / pdf（仅限归属用户）。"""
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
        pd.DataFrame(rows).to_csv(buf, index=False)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename=report.csv; filename*=UTF-8''{quote(f'{标题}.csv')}"},
        )
    # PDF（reportlab + 微软雅黑中文字体）
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    pdfmetrics.registerFont(TTFont("MSYH", "C:/Windows/Fonts/msyh.ttc"))
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["Normal"], fontName="MSYH", fontSize=10, leading=15)
    title = ParagraphStyle("Title", parent=styles["Title"], fontName="MSYH", fontSize=16, leading=22)
    head = ParagraphStyle("Head", parent=styles["Heading2"], fontName="MSYH", fontSize=11, leading=16, spaceBefore=10)

    doc = SimpleDocTemplate(buf, pagesize=A4)
    story = [Paragraph(f"报表：{标题}", title), Spacer(1, 8)]
    story.append(Paragraph(f"图表类型：{report.get('图表类型', '')} · 意图来源：{report.get('意图来源', '')}", body))
    story.append(Spacer(1, 6))
    if report.get("结论"):
        story.append(Paragraph("分析结论", head))
        story.append(Paragraph(str(report["结论"]), body))
    if rows:
        story.append(Paragraph("数据明细", head))
        cols = list(rows[0].keys())
        data = [[Paragraph(str(c), body) for c in cols]]
        for row in rows[:200]:
            data.append([Paragraph(str(row.get(c, "")), body) for c in cols])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5")),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cbd5e1")),
            ("FONTNAME", (0, 0), (-1, -1), "MSYH"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
        ]))
        story.append(table)
    推荐 = report.get("推荐说明", {}).get("理由", [])
    if 推荐:
        story.append(Paragraph("推荐依据", head))
        for r in 推荐:
            story.append(Paragraph(f"· {r}", body))
    风险 = report.get("风险提示", [])
    if 风险:
        story.append(Paragraph("注意事项", head))
        for w in 风险:
            story.append(Paragraph(f"· {w}", body))
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
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """为报表创建分享链接（仅创建者）。返回可公开访问的只读链接。"""
    _确认报表归属(user["user_id"], report_id)
    from repositories import share_repo
    info = share_repo.创建分享(user["user_id"], report_id, 有效小时数)
    return {
        "链接ID": info["share_id"],
        "分享链接": f"/s/{info['share_id']}",
        "过期时间": info["过期时间"],
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
        agent_mode="single",
    )

    df, llm_config = _准备上下文(payload, request, user)
    try:
        new_id, new_report = _生成报表流式(payload, df, llm_config, user)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return _构建响应(payload, new_report, new_id)


# ── 生成 ──────────────────────────────────────────────────────────────────────


def _单Agent报表(
    df: Any,
    payload: ReportGenerateRequest,
    llm_config: LLMRequestConfig,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
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
    )


def _多智能体报表(
    df: Any,
    payload: ReportGenerateRequest,
    llm_config: LLMRequestConfig,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
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
