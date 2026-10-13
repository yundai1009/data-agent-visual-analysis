# 一句话定位：用户反馈路由（HTTP 边界，B8 修复后不再是假实现）——把反馈真正落库，并允许按任务回查。
#
# 做了什么：`submit_feedback` 收 `FeedbackRequest`，把 `任务ID`/`评分`/`纠错内容`/`同步知识库` 交给
# `feedback_repo.保存反馈`，返回 `反馈ID` 与 `状态="saved"`；`get_feedback` 按 `task_id` 调
# `feedback_repo.按任务查询` 返回 `反馈列表`。
#
# 为什么这么做：
#   - 两个接口都显式 `Depends(get_current_user)` 而不把鉴权挂在 `APIRouter` 上：让 OpenAPI 里每个端点的安全要求一目了然，也不给后来者"router 已经鉴权"的误判空间。
#   - 归属过滤下沉到 repo（`按任务查询(task_id, user_id)`）而不是路由里先查再比对：少一次往返，也让 S5 的防 IDOR 约束无法被"忘了加判断"绕过。
#   - 写入路径不直接触发知识库同步：`同步知识库` 只作为标记存库，避免反馈接口被外部服务拖成慢请求。
#
# 关键约定与坑：
#   - `correction` 传的是 `payload.纠错内容 or ""`：空值被规整成空串而非 NULL。
#   - 响应字段是中文键（`反馈ID`/`任务ID`/`评分`/`同步知识库`/`状态`），前端与测试都按此契约解析。
#   - `GET /feedback/{task_id}` 只能看到本人的反馈；改 `按任务查询` 的签名会直接破坏这条安全约束。
"""用户反馈路由（B8 修复：反馈落库，不再假实现丢弃）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from api.contracts import FeedbackRequest
from api.dependencies import get_current_user
from repositories import feedback_repo

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("")
def submit_feedback(
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
def get_feedback(task_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """查询指定任务的反馈列表（S5：需登录且仅返回本人反馈，防 IDOR 越权读取他人纠错内容）。"""
    return {"任务ID": task_id, "反馈列表": feedback_repo.按任务查询(task_id, user["user_id"])}