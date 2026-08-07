from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status

from api.contracts import GoldenSetItem
from api.dependencies import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/golden-set", response_model=List[GoldenSetItem])
async def list_golden_set(user: dict = Depends(require_admin)) -> List[GoldenSetItem]:
    # TODO: 接入真实 Golden Set 存储
    return []


@router.post("/golden-set", response_model=GoldenSetItem)
async def create_golden_set(
    item: GoldenSetItem, user: dict = Depends(require_admin)
) -> GoldenSetItem:
    # TODO: 持久化并版本化
    return item


@router.post("/eval/run")
async def trigger_eval(user: dict = Depends(require_admin)) -> dict[str, Any]:
    # TODO: 触发全量评测回归
    return {"status": "queued"}


@router.get("/metrics")
async def get_metrics(user: dict = Depends(require_admin)) -> dict[str, Any]:
    # TODO: 聚合监控指标
    return {"qps": 0, "p99_latency_ms": 0, "error_rate": 0.0}


@router.get("/statistics")
async def get_statistics(user: dict = Depends(require_admin)) -> dict[str, Any]:
    """平台用量总览：资源总数 + 最近 7 天报表生成趋势。"""
    from repositories import admin_repo
    return {
        "总览": admin_repo.总览统计(),
        "趋势": admin_repo.报表趋势(7),
    }


@router.get("/users")
async def list_users(user: dict = Depends(require_admin)) -> dict[str, Any]:
    """用户列表与用量（已剥离密码与密钥字段）。"""
    from repositories import admin_repo
    return {"用户列表": admin_repo.用户用量列表()}
