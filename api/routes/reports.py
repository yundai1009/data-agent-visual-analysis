from __future__ import annotations

from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status

from api.contracts import ReportGenerateRequest, ReportGenerateResponse
from api.dependencies import get_current_user
# 兼容历史：仍允许从 datasets 模块导入 _DATASET_DB 符号（已不再使用，留作过渡）
from api.routes.datasets import _仓储
from 后端_核心.上传报表生成器 import 生成报表数据

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/generate", response_model=ReportGenerateResponse)
async def generate_report(
    payload: ReportGenerateRequest,
    user: dict = Depends(get_current_user),
) -> ReportGenerateResponse:
    # 阶段 2：从 SQLite 仓储读数据集；进程重启后仍可生成报表
    item = _仓储.读取(payload.数据集ID)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在")

    df = item["数据"]
    report = 生成报表数据(
        df=df,
        分析需求=payload.分析需求,
        图表类型=payload.图表类型,
        x轴=payload.x轴,
        y轴=payload.y轴,
        分组字段=payload.分组字段,
        聚合方式=payload.聚合方式,
    )
    report_rows = report["报表数据"]

    return ReportGenerateResponse(
        报表ID=uuid4().hex,
        数据集ID=payload.数据集ID,
        标题=report["标题"],
        图表类型=report["图表类型"],
        图表配置=report["图表配置"],
        报表数据=report_rows,
        数据画像=report["数据画像"],
        推荐说明=report["推荐说明"],
        风险提示=report["风险提示"],
        **{
            "Agent Trace": report["Agent Trace"],
        },
        导出数据=report["导出数据"],
        结论=report["结论"],
        意图来源=report.get("意图来源", "无"),
    )
