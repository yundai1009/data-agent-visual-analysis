"""全局搜索路由（优化⑧）：跨数据集/报表/模板的关键词搜索，统一入口。

前端顶部搜索框调用本接口，返回三类结果供下拉/跳转。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_current_user

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def 全局搜索(
    q: str = Query("", max_length=100, description="搜索关键词"),
    user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """跨 数据集文件名 / 报表标题 / 模板名称 搜索，各自最多返回 5 条。"""
    keyword = q.strip()
    if not keyword:
        return {"数据集": [], "报表": [], "模板": []}

    from 后端_核心.存储.sqlite_repo import 列出数据集
    from repositories import report_repo, template_repo

    datasets = 列出数据集(user["user_id"], limit=5, q=keyword)
    reports = report_repo.搜索报表标题(user["user_id"], keyword, limit=5)
    templates = template_repo.搜索模板名称(user["user_id"], keyword, limit=5)

    return {
        "数据集": [{"数据集ID": d["数据集ID"], "文件名": d["文件名"], "行数": d["行数"]} for d in datasets],
        "报表": [{"报表ID": r["报表ID"], "标题": r["标题"], "图表类型": r["图表类型"]} for r in reports],
        "模板": [{"模板ID": t["模板ID"], "名称": t["名称"]} for t in templates],
    }
