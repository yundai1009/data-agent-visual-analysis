"""公开分享只读端点：GET /s/{share_id}。

无需登录，凭分享令牌读取报表的只读视图（图表配置/报表数据/结论/风险提示）。
令牌过期或已撤销 → 404；报表已被删除 → 404。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from repositories import report_repo, share_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/s", tags=["share"])

# 公开视图只透传展示所需字段（不含 Agent Trace 等内部数据）
_公开字段 = ("标题", "图表类型", "图表配置", "报表数据", "结论", "风险提示", "数据画像")


@router.get("/{share_id}")
def 公开查看报表(share_id: str) -> Dict[str, Any]:
    """按分享令牌读取报表只读视图；过期/撤销/报表已删 → 404。"""
    share = share_repo.读取有效分享(share_id)
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享链接不存在或已过期")

    # 报表可能已被创建者删除：分享随之失效（不暴露内部信息）
    item = report_repo.读取报表(share["user_id"], share["report_id"])
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表已不存在")

    report = item["报表"]
    view = {k: report.get(k) for k in _公开字段 if k in report}
    view["标题"] = item["标题"]
    view["创建者"] = share["user_id"]
    view["过期时间"] = share["过期时间"]
    return view