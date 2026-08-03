from __future__ import annotations

import json
import logging
import math
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

    # LLM 配置：只允许用户选 provider + model（白名单校验），禁止传任意 URL/Key
    user_provider = (request.headers.get("x-llm-provider") or "deepseek").strip().lower()
    user_model = (request.headers.get("x-llm-model") or "").strip() or payload.model or ""

    providers = getattr(EnvConfig, "LLM_PROVIDERS", {})
    provider_conf = providers.get(user_provider)
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

    # BYOK：不存后端、不进日志；不传则回退服务端 .env。URL 始终白名单，不允许用户指定。
    user_api_key = (request.headers.get("x-llm-api-key") or "").strip()
    if len(user_api_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API Key 格式不合法",
        )
    llm_config = LLMRequestConfig(
        provider=user_provider,
        base_url=provider_conf["base_url"],
        model=user_model or provider_conf.get("default_model", ""),
        api_key=user_api_key or EnvConfig.LLM_API_KEY,
    )
    return df, llm_config


def _生成报表流式(
    payload: ReportGenerateRequest,
    df: Any,
    llm_config: LLMRequestConfig,
    user: dict,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Tuple[str, Dict[str, Any]]:
    """生成报表 + 持久化；on_event 实时推送决策事件（SSE 直播）。返回 (report_id, report)。"""
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


@router.delete("/{report_id}")
def delete_report(report_id: str, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """删除一份报表（仅限归属用户）。"""
    from repositories import report_repo
    if not report_repo.删除报表(user["user_id"], report_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表不存在")
    return {"message": "已删除"}


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
        agent_mode=payload.agent_mode,
    )
