# 一句话定位：全局搜索路由（HTTP 边界，优化⑧）——前端顶部搜索框的唯一后端入口，跨三类资源查关键词。
#
# 做了什么：`全局搜索` 收 `q`（`Query("", max_length=100)`），空串直接返回三个空列表；否则分别调
# `列出数据集`、`report_repo.搜索报表标题`、`template_repo.搜索模板名称`，各限 `limit=5`，再把结果
# 裁剪成 `数据集`/`报表`/`模板` 三个数组返回。
#
# 为什么这么做：
#   - 三个 repo 调用都带 `user["user_id"]`：全局搜索是最容易漏归属过滤的接口，这里从第一行就锁死只搜本人数据，不做"管理员可搜全站"的分支。
#   - 返回裁剪后的摘要（只留跳转必需的 ID/名称/行数）而不是完整记录：报表全文可能很大，下拉列表用不上，让前端按 ID 二次拉取更省带宽。
#   - `limit=5` 写死在路由层而不暴露成参数：这是搜索框下拉的形态约束，不是分页接口，真要翻页应走各资源自己的列表接口。
#
# 关键约定与坑：
#   - `q` 是 `max_length=100` 的 query 参数，超长会被 FastAPI 拦成 422。
#   - 空关键词返回三个空数组（不是 404），前端据此显示"无结果"。
#   - `列出数据集`/`report_repo`/`template_repo` 都在函数内 import；搬到模块顶层前先确认不会引入循环导入。
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
