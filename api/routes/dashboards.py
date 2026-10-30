# 一句话定位：看板路由（HTTP 边界）——把用户自己的多份报表组成"图表看板"，用于多图并排对比。
#
# 做了什么：`_校验报表归属` 用 `report_repo.批量读取报表` 一次 IN 查询校验报表存在且属于本人；
# `新建看板`/`列表看板`/`看板详情`/`更新看板`/`删除看板` 全套 CRUD 都经 `dashboard_repo` 并带
# `user["user_id"]`；`分享看板` 复用 `share_repo.创建分享` 生成只读链接（`target_type="dashboard"`）。
#
# 为什么这么做：
#   - 报表归属用单次批量 IN 查询而不是逐份 `读取报表`：优化⑨ 之前是 N+1，挂 20 份报表就 20 次查询。
#   - 报表不存在或不属于本人一律 400「报表不存在或无权访问」而非 403/404：保存看板是写入动作，用户需要立刻知道是哪个 ID 有问题（响应里带前 3 个 ID），此处也没有可被探测的受保护资源状态。
#   - 查不到看板时返回 404 而非 403（`dashboard_repo` 全以 `user_id` 为条件，不区分"非本人"与"不存在"，避免用状态码探测他人看板 ID）；详情里已删除的报表引用直接 `continue`，松引用不该让整页报错。
#
# 关键约定与坑：
#   - 每个 repo 调用都必须带 `user["user_id"]`——这是本模块唯一的越权防线，漏一个就是 IDOR。
#   - `POST`/`GET` 的 `/dashboards/` 与 `/dashboards` 都注册了；`分享看板` 的 `有效小时数` 非数字返回 400 而非 500，范围校验 1-720；`删除看板` 会顺带写 `audit_repo` 审计，改删除逻辑别把审计一起删了。
"""看板路由：多报表并排对比（图表看板）。

看板 = 用户从自己的历史报表中挑选多份，命名保存，用于多图对比查看。
所有读写均按 user_id 隔离；报表引用在保存/更新时校验归属。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

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
    """新建看板（名称 + 报表ID列表 + 可选自由画布布局）。"""
    _校验报表归属(user["user_id"], payload.报表ID列表)
    dashboard_id = dashboard_repo.保存看板(
        user["user_id"], payload.名称.strip(), payload.报表ID列表, payload.布局
    )
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
        "布局": item["布局"],
        "报表列表": reports,
    }


@router.get("/{dashboard_id}/export")
def 导出看板(
    dashboard_id: str,
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """阶段八十五：看板导出——把当前看板内全部报表打包成一个 ZIP（仅限归属用户）。

    与 `GET /reports/export-all`（导出全部报表）的区别：只打包**当前看板选中的报表**。
    复用 `reports._导出格式化行` / `_导出并发配额`，导出格式与批量导出完全一致。
    """
    item = dashboard_repo.读取看板(user["user_id"], dashboard_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="看板不存在")
    report_ids = item["报表ID列表"]
    if not report_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="看板为空，无法导出")

    from api.routes.reports import _导出格式化行, _导出并发配额

    with _导出并发配额():
        import io
        import os
        import zipfile
        from urllib.parse import quote

        import pandas as pd

        from repositories import audit_repo

        audit_repo.记录(user["user_id"], "导出看板", target_type="dashboard", target_id=dashboard_id, detail=f"format={format}")

        buf = io.BytesIO()
        已用名: Dict[str, int] = {}
        标题 = (item["名称"] or "看板").replace('"', '').replace('\\', '_').replace('/', '_')
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rid in report_ids:
                r = report_repo.读取报表(user["user_id"], rid)
                if not r:
                    continue
                rows = (r["报表"] or {}).get("报表数据", [])
                报表标题 = (r["标题"] or "报表").replace('"', '').replace('\\', '_').replace('/', '_')
                基础名 = f"{报表标题}.{format}"
                if 基础名 in 已用名:
                    已用名[基础名] += 1
                    根, ext = os.path.splitext(基础名)
                    基础名 = f"{根}({已用名[基础名]}){ext}"
                else:
                    已用名[基础名] = 1
                单份 = io.BytesIO()
                fmt_rows = [_导出格式化行(row) for row in rows]
                if format == "xlsx":
                    pd.DataFrame(fmt_rows).to_excel(单份, index=False, engine="openpyxl")
                else:
                    pd.DataFrame(fmt_rows).to_csv(单份, index=False, encoding="utf-8-sig")
                zf.writestr(基础名, 单份.getvalue())
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=dashboard.zip; filename*=UTF-8''{quote(标题 + '.zip')}"},
        )


@router.put("/{dashboard_id}")
def 更新看板(
    dashboard_id: str,
    payload: DashboardRequest,
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """更新看板（名称 + 报表ID列表 + 可选布局），仅限归属用户。"""
    if not dashboard_repo.读取看板(user["user_id"], dashboard_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="看板不存在")
    _校验报表归属(user["user_id"], payload.报表ID列表)
    ok = dashboard_repo.更新看板(
        user["user_id"], dashboard_id, payload.名称.strip(), payload.报表ID列表, payload.布局
    )
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