"""管理后台路由：平台用量统计与监控指标（管理员专属）。

移除过占位的 golden-set / eval 评测端点（与本项目主线无关，未实现则不留假数据），
metrics 改为返回真实用量；statistics / users 为用户与用量统计。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from api.dependencies import require_admin
from repositories import admin_repo

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/export-events")
def export_events(user: dict = Depends(require_admin)) -> Dict[str, Any]:
    """导出预测数据四张表 CSV 到 data/export/（会员开通预测系统 data/raw 直接用）。

    中文表头 + 东八区 YYYY-MM-DD HH:MM:SS + u_ 脱敏用户编号，符合预测系统数据规范。
    """
    from repositories import event_repo
    out_dir = Path("data/export")
    exported = event_repo.导出全部事件CSV(out_dir)
    return {
        "导出目录": str(out_dir),
        "文件": {table: {"路径": str(p), "行数": 0} for table, p in exported.items()},
        "提示": "把 data/export/ 下四张 CSV 复制到预测系统 data/raw/ 后运行 run-all --no-generate",
    }


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


@router.post("/users/{user_id}/ban")
def ban_user(user_id: str, payload: dict, user: dict = Depends(require_admin)) -> Dict[str, Any]:
    """封禁用户：status → banned，吊销其全部会话（token_version +1）。

    安全约束：
    - 不能封禁自己（管理员自杀式操作，锁死管理入口）
    - 不能封禁 admin 角色（防止一个管理员封掉全部管理员导致无人能解封）
    """
    from repositories import user_repo
    target = user_repo.按用户ID查询(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if target["user_id"] == user["user_id"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能封禁自己")
    if target["role"] == "admin":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能封禁管理员账号")
    reason = str(payload.get("reason") or "").strip()[:200]
    try:
        user_repo.封禁用户(user_id, reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "封禁用户", username=user.get("username", ""), target_type="user", target_id=user_id, detail=reason)
    return {"message": f"已封禁用户 {target['username']}", "用户ID": user_id, "状态": "banned"}


@router.post("/users/{user_id}/unban")
def unban_user(user_id: str, user: dict = Depends(require_admin)) -> Dict[str, Any]:
    """解封用户：status → active，恢复登录。"""
    from repositories import user_repo
    target = user_repo.按用户ID查询(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    try:
        user_repo.解封用户(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "解封用户", username=user.get("username", ""), target_type="user", target_id=user_id, detail="")
    return {"message": f"已解封用户 {target['username']}", "用户ID": user_id, "状态": "active"}


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