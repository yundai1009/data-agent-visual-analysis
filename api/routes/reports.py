from __future__ import annotations

import logging
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status

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
    item = _仓储.读取(payload.数据集ID)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")

    df = item["数据"]

    # 用户自配 LLM 配置（从前端请求头传入）
    user_base_url = request.headers.get("x-llm-base-url")
    user_api_key = request.headers.get("x-llm-api-key")
    user_model = request.headers.get("x-llm-model") or payload.model

    # 临时覆盖 EnvConfig
    original_base_url = getattr(EnvConfig, "LLM_BASE_URL", None)
    original_key = getattr(EnvConfig, "LLM_API_KEY", None)
    original_model = getattr(EnvConfig, "LLM_MODEL", None)
    if user_base_url:
        EnvConfig.LLM_BASE_URL = user_base_url
    if user_api_key:
        EnvConfig.LLM_API_KEY = user_api_key
    if user_model:
        EnvConfig.LLM_MODEL = user_model

    try:
        if payload.agent_mode == "multi":
            report = _多智能体报表(df, payload)
        else:
            report = _单Agent报表(df, payload)
    finally:
        if user_base_url and original_base_url:
            EnvConfig.LLM_BASE_URL = original_base_url
        if user_api_key and original_key:
            EnvConfig.LLM_API_KEY = original_key
        if user_model and original_model:
            EnvConfig.LLM_MODEL = original_model

    return _构建响应(payload, report)


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


def _构建响应(payload: ReportGenerateRequest, report: Dict[str, Any]) -> ReportGenerateResponse:
    报告_rows = report["报表数据"]
    return ReportGenerateResponse(
        报表ID=uuid4().hex,
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
