from __future__ import annotations

import logging
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from api.contracts import ReportGenerateRequest, ReportGenerateResponse
from api.dependencies import get_current_user
from api.routes.datasets import _仓储
from 后端_核心.上传报表生成器 import 生成报表数据
from 后端_核心.agent.多智能体 import 多智能体分析
from config.settings import EnvConfig

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate", response_model=ReportGenerateResponse)
async def generate_report(
    payload: ReportGenerateRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> ReportGenerateResponse:
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

    # 临时覆盖 EnvConfig（仅 base_url 和 model；api_key 始终用服务端 .env，不接收用户传入）
    original_base_url = getattr(EnvConfig, "LLM_BASE_URL", None)
    original_model = getattr(EnvConfig, "LLM_MODEL", None)
    EnvConfig.LLM_BASE_URL = provider_conf["base_url"]
    if user_model:
        EnvConfig.LLM_MODEL = user_model

    try:
        if payload.agent_mode == "multi":
            report = _多智能体报表(df, payload)
        else:
            report = _单Agent报表(df, payload)
    finally:
        if original_base_url is not None:
            EnvConfig.LLM_BASE_URL = original_base_url
        if original_model is not None:
            EnvConfig.LLM_MODEL = original_model

    # 报表持久化到后端（阶段 6）
    from repositories import report_repo
    report_id = report_repo.保存报表(
        user_id=user["user_id"],
        dataset_id=payload.数据集ID,
        title=report.get("标题", ""),
        chart_type=report.get("图表类型", ""),
        report=report,
    )

    return _构建响应(payload, report, report_id)


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


def _单Agent报表(df: Any, payload: ReportGenerateRequest) -> Dict[str, Any]:
    """标准单 Agent 生成报表。"""
    return 生成报表数据(
        df=df,
        分析需求=payload.分析需求,
        图表类型=payload.图表类型,
        x轴=payload.x轴,
        y轴=payload.y轴,
        分组字段=payload.分组字段,
        聚合方式=payload.聚合方式,
    )


def _多智能体报表(df: Any, payload: ReportGenerateRequest) -> Dict[str, Any]:
    """多智能体模式生成报表。"""
    from 后端_核心.数据画像 import 生成数据画像
    画像 = 生成数据画像(df)
    result = 多智能体分析(画像, payload.分析需求, df)
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
    )


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
