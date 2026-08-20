"""公开分享只读数据端点：GET /share-data/{share_id}。

无需登录，凭分享令牌读取报表的只读数据（图表配置/报表数据/结论/风险提示）。
令牌过期或已撤销 → 404；报表已被删除 → 404。

注意：分享页面本身在 /s/{share_id}（SPA 路由，由前端渲染，本端点只供其 fetch 数据）——
曾把数据端点放在 /s/{id} 导致浏览器直连时返回 JSON 而非页面。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from api.dependencies import get_current_user_optional
from repositories import report_repo, share_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/share-data", tags=["share"])

# 公开视图只透传展示所需字段（不含 Agent Trace 等内部数据）
_公开字段 = ("标题", "图表类型", "图表配置", "报表数据", "结论", "风险提示", "数据画像")

# P0 加固：密码尝试限频（固定窗口：10 分钟最多 10 次失败，防在线暴破）
_PWD_WINDOW_SEC = 600
_PWD_MAX_FAILS = 10
_pwd_fails: Dict[str, tuple] = {}  # share_id -> (window_start, fail_count)



_MAX_LIMIT_ENTRIES = 5000  # 批次3：限频字典容量上限，防内存无限增长


def _密码尝试超限(share_id: str) -> bool:
    import time
    now = time.time()
    start, count = _pwd_fails.get(share_id, (now, 0))
    if now - start > _PWD_WINDOW_SEC:
        _pwd_fails[share_id] = (now, 0)
        return False
    return count >= _PWD_MAX_FAILS


def _记录密码失败(share_id: str) -> None:
    if len(_pwd_fails) >= _MAX_LIMIT_ENTRIES:
        _pwd_fails.clear()  # 容量上限：整体重置
    import time
    now = time.time()
    start, count = _pwd_fails.get(share_id, (now, 0))
    _pwd_fails[share_id] = (now if now - start > _PWD_WINDOW_SEC else start, count + 1)


@router.get("/{share_id}")
def 公开查看报表(
    share_id: str,
    request: Request,
    user: Optional[dict] = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """按分享令牌读取报表只读视图；过期/撤销/报表已删 → 404；设置了密码需凭密码（401）。

    阶段 31：分享设置了协作者白名单时，需登录且 username 在白名单内（否则 401）。
    P0 加固：密码以 HMAC 哈希存储、恒定时间比对、失败限频（10 分钟 10 次 → 429）。
    """
    share = share_repo.读取有效分享(share_id)
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享链接不存在或已过期")

    # 密码保护：分享设置了密码时，请求需带密码且匹配，否则 401；连续失败限频 429
    # M16：密码从 URL query 移入请求头 X-Share-Password（URL 会进浏览器历史/
    # 访问日志，明文泄露）；query 参数保留向后兼容（旧分享链接）。
    if share["需密码"]:
        if _密码尝试超限(share_id):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="尝试次数过多，请稍后再试")
        given = (request.headers.get("X-Share-Password") or request.query_params.get("password") or "").strip()
        import hashlib
        import hmac as _hmac
        from config.settings import EnvConfig
        calc = _hmac.new(EnvConfig.JWT_SECRET_KEY.encode(), given.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(calc, share["密码哈希"]):
            _记录密码失败(share_id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要访问密码")

    # 阶段 31：协作者白名单——非空时仅白名单内登录用户可看（公开访客/名单外 401）
    协作者 = share.get("协作者") or []
    if 协作者:
        if not user or user.get("username") not in 协作者:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="该分享仅对指定协作者开放，请登录协作者账号后访问",
            )

    # 报表可能已被创建者删除：分享随之失效（不暴露内部信息）
    # 优化⑦：target_type=dashboard 时返回看板只读元数据（名称 + 报表标题列表）
    if share.get("目标类型") == "dashboard":
        from repositories import dashboard_repo
        看板 = dashboard_repo.读取看板(share["user_id"], share["report_id"])
        if not 看板:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="看板已不存在")
        # 优化⑦：成功访问计一次浏览次数
        share_repo.增加浏览次数(share_id)
        report_ids = 看板.get("报表ID列表") or []
        items = report_repo.批量读取报表(share["user_id"], report_ids)
        return {
            "类型": "dashboard",
            "名称": 看板.get("名称", "未命名看板"),
            "报表列表": [{"报表ID": rid, "标题": items[rid].get("标题", "未命名") if rid in items else "（已删除）"} for rid in report_ids],
            "过期时间": share["过期时间"],
        }

    item = report_repo.读取报表(share["user_id"], share["report_id"])
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="报表已不存在")

    report = item["报表"]
    # 优化⑥：成功访问计一次浏览次数（分享者可见热度）
    share_repo.增加浏览次数(share_id)
    view = {k: report.get(k) for k in _公开字段 if k in report}
    view["标题"] = item["标题"]
    # M17：公开分享不再暴露内部 user_id（此前直接透传，可被用于跨账号枚举）——
    # 前端 ShareView 未使用该字段，直接移除。
    view["过期时间"] = share["过期时间"]
    return view