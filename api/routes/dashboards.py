"""看板路由：多报表并排对比（图表看板）。

看板 = 用户从自己的历史报表中挑选多份，命名保存，用于多图对比查看。
所有读写均按 user_id 隔离；报表引用在保存/更新时校验归属。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.contracts import DashboardRequest
from api.dependencies import get_current_user
from repositories import dashboard_repo, report_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboards", tags=["dashboards"])


def _校验报表归属(user_id: str, report_ids: List[str]) -> None:
    """优化⑨：批量校验报表存在且归属该用户（单次 IN 查询，替代逐份读取 N+1）。"""
    if not report_ids:
        return
    found = report_repo.批量读取报表(user_id, report_ids)
    missing = [rid for rid in report_ids if rid not in found]
    if missing:
        shown = "、".join(missing[:3]) + ("…" if len(missing) > 3 else "")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"报表不存在或无权访问：{shown}",
        )


@router.post("/")
@router.post("")
def 新建看板(
    payload: DashboardRequest,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """新建看板（名称 + 报表ID列表）。"""
    _校验报表归属(user["user_id"], payload.报表ID列表)
    dashboard_id = dashboard_repo.保存看板(user["user_id"], payload.名称.strip(), payload.报表ID列表)
    return {"看板ID": dashboard_id, "名称": payload.名称.strip()}


@router.get("/")
@router.get("")
def 列表看板(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """列出当前用户的看板。"""
    return {"看板列表": dashboard_repo.列出看板(user["user_id"])}


@router.get("/{dashboard_id}")
def 看板详情(
    dashboard_id: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """看板详情：名称 + 每份报表的完整内容（图表配置/结论/数据）。

    已删除的报表引用自动跳过（保留看板本身不报错）。
    """
    item = dashboard_repo.读取看板(user["user_id"], dashboard_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="看板不存在")
    reports: List[Dict[str, Any]] = []
    for rid in item["报表ID列表"]:
        r = report_repo.读取报表(user["user_id"], rid)
        if not r:
            continue
        reports.append({
            "报表ID": rid,
            "标题": r["标题"],
            "图表类型": r["图表类型"],
            "创建时间": r["创建时间"],
            "报表": r["报表"],
        })
    return {
        "看板ID": item["看板ID"],
        "名称": item["名称"],
        "创建时间": item["创建时间"],
        "报表列表": reports,
    }


@router.put("/{dashboard_id}")
def 更新看板(
    dashboard_id: str,
    payload: DashboardRequest,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """更新看板（名称 + 报表ID列表），仅限归属用户。"""
    if not dashboard_repo.读取看板(user["user_id"], dashboard_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="看板不存在")
    _校验报表归属(user["user_id"], payload.报表ID列表)
    ok = dashboard_repo.更新看板(user["user_id"], dashboard_id, payload.名称.strip(), payload.报表ID列表)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="看板不存在")
    return {"看板ID": dashboard_id, "名称": payload.名称.strip()}


@router.delete("/{dashboard_id}")
def 删除看板(
    dashboard_id: str,
    user: dict = Depends(get_current_user),
) -> Dict[str, str]:
    """删除看板（仅限归属用户）。"""
    if not dashboard_repo.删除看板(user["user_id"], dashboard_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="看板不存在")
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "删除看板", target_type="dashboard", target_id=dashboard_id)
    return {"看板ID": dashboard_id, "status": "deleted"}


@router.post("/{dashboard_id}/share")
def 分享看板(
    dashboard_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """优化⑦：生成看板只读分享链接（复用 share_links 体系，target_type=dashboard）。

    query 参数：有效小时数（默认 24）、密码（可选）、协作者（可选，逗号分隔）。
    """
    from repositories import dashboard_repo, share_repo
    item = dashboard_repo.读取看板(user["user_id"], dashboard_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="看板不存在")

    # security review：非数字 hours 参数 → 400 而非 500
    try:
        hours = int(request.query_params.get("有效小时数") or 24)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="有效小时数必须是数字")
    password = (request.query_params.get("密码") or "").strip()
    协作者 = [c.strip() for c in (request.query_params.get("协作者") or "").split(",") if c.strip()]
    if hours < 1 or hours > 720:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="有效小时数需在 1-720 之间")

    result = share_repo.创建分享(
        user["user_id"], dashboard_id, hours=hours, password=password,
        collaborators=协作者, target_type="dashboard",
    )
    return {**result, "类型": "dashboard"}