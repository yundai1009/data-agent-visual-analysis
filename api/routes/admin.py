"""管理后台路由：平台用量统计与监控指标（管理员专属）。

移除过占位的 golden-set / eval 评测端点（与本项目主线无关，未实现则不留假数据），
metrics 改为返回真实用量；statistics / users 为用户与用量统计。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from api.dependencies import require_admin
from repositories import admin_repo

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/metrics")
def get_metrics(user: dict = Depends(require_admin)) -> Dict[str, Any]:
    """平台用量指标：资源总数 + 近 7 天与今日生成报表数。"""
    stats = admin_repo.总览统计()
    trend = admin_repo.报表趋势(7)
    return {
        "用户数": stats["用户数"],
        "数据集数": stats["数据集数"],
        "报表数": stats["报表数"],
        "看板数": stats["看板数"],
        "今日生成报表": trend[-1]["数量"],
        "近7天生成报表": sum(t["数量"] for t in trend),
    }


@router.get("/statistics")
def get_statistics(user: dict = Depends(require_admin)) -> Dict[str, Any]:
    """平台用量总览：资源总数 + 最近 7 天报表生成趋势。"""
    return {
        "总览": admin_repo.总览统计(),
        "趋势": admin_repo.报表趋势(7),
    }


@router.get("/users")
def list_users(user: dict = Depends(require_admin)) -> Dict[str, Any]:
    """用户列表与用量（已剥离密码与密钥字段）。"""
    return {"用户列表": admin_repo.用户用量列表()}


@router.get("/usage")
def get_llm_usage(
    days: int = Query(7, ge=1, le=90),
    user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """LLM token 用量统计（P1 加固：成本可见性，近 N 天总量/按天/按 provider）。"""
    from repositories import usage_repo
    return usage_repo.统计用量(days=days)


@router.get("/audit")
def get_audit_log(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user_id: str = Query("", description="可选按用户过滤"),
    user: dict = Depends(require_admin),
) -> Dict[str, Any]:
    """操作审计日志（P2 加固：谁在何时做了什么，支持分页与按用户过滤）。"""
    from repositories import audit_repo
    return {"审计列表": audit_repo.查询(limit=limit, offset=offset, user_id=user_id.strip())}