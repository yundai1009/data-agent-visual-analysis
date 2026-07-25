from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.contracts import FeedbackRequest
from api.dependencies import get_current_user

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("")
async def submit_feedback(
    payload: FeedbackRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    # TODO: 持久化反馈 + 触发知识库同步
    return {
        "任务ID": payload.任务ID,
        "评分": payload.评分,
        "同步知识库": payload.同步知识库,
        "状态": "accepted",
    }


@router.get("/{task_id}")
async def get_feedback(task_id: str) -> dict[str, Any]:
    return {"任务ID": task_id, "反馈列表": []}
