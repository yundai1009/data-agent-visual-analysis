"""公开分享只读数据端点：GET /share-data/{share_id}。

无需登录，凭分享令牌读取报表的只读数据（图表配置/报表数据/结论/风险提示）。
令牌过期或已撤销 → 404；报表已被删除 → 404。

注意：分享页面本身在 /s/{share_id}（SPA 路由，由前端渲染，本端点只供其 fetch 数据）——
曾把数据端点放在 /s/{id} 导致浏览器直连时返回 JSON 而非页面。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, status

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
def 公开查看报表(share_id: str, request: Request) -> Dict[str, Any]:
    """按分享令牌读取报表只读视图；过期/撤销/报表已删 → 404；设置了密码需凭密码（401）。

    P0 加固：密码以 HMAC 哈希存储、恒定时间比对、失败限频（10 分钟 10 次 → 429）。
    """
    share = share_repo.读取有效分享(share_id)
    if not share:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="分享链接不存在或已过期")

    # 密码保护：分享设置了密码时，请求需带 ?password= 且匹配，否则 401；连续失败限频 429
    if share["需密码"]:
        if _密码尝试超限(share_id):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="尝试次数过多，请稍后再试")
        given = (request.query_params.get("password") or "").strip()
        import hashlib
        import hmac as _hmac
        from config.settings import EnvConfig
        calc = _hmac.new(EnvConfig.JWT_SECRET_KEY.encode(), given.encode(), hashlib.sha256).hexdigest()
        if not _hmac.compare_digest(calc, share["密码哈希"]):
            _记录密码失败(share_id)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="需要访问密码")

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