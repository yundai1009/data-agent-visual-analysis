"""用户反馈路由（B8 修复：反馈落库，不再假实现丢弃）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.contracts import FeedbackRequest
from api.dependencies import get_current_user
from repositories import feedback_repo

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("")
async def submit_feedback(
    payload: FeedbackRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """保存一条用户反馈并返回反馈 id（可作后续知识库同步的触发点）。"""
    feedback_id = feedback_repo.保存反馈(
        user_id=user["user_id"],
        task_id=payload.任务ID,
        score=payload.评分,
        correction=payload.纠错内容 or "",
        sync_kb=payload.同步知识库,
    )
    return {
        "反馈ID": feedback_id,
        "任务ID": payload.任务ID,
        "评分": payload.评分,
        "同步知识库": payload.同步知识库,
        "状态": "saved",
    }


@router.get("/{task_id}")
async def get_feedback(task_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """查询指定任务的反馈列表（S5：需登录且仅返回本人反馈，防 IDOR 越权读取他人纠错内容）。"""
    return {"任务ID": task_id, "反馈列表": feedback_repo.按任务查询(task_id, user["user_id"])}