"""分享链接仓储：share_links 表的 CRUD。

分享链接 = 创建者为某份报表生成一条有时效的只读访问令牌（share_id）。
访问者凭 /s/{share_id} 公开访问，无需登录；过期或撤销后失效。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化分享表() -> None:
    """幂等创建 share_links 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS share_links (
                share_id   TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                report_id  TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_share_links_report
            ON share_links (report_id)
            """
        )


def 创建分享(user_id: str, report_id: str, hours: int = 24) -> Dict[str, Any]:
    """为指定报表创建分享链接，返回 {share_id, expires_at, created_at}。"""
    初始化分享表()
    share_id = uuid.uuid4().hex
    now = _now_iso()
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO share_links (share_id, user_id, report_id, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (share_id, user_id, report_id, expires, now),
        )
    logger.info("创建分享 %s → 报表 %s（%dh）", share_id, report_id, hours)
    return {"share_id": share_id, "过期时间": expires, "创建时间": now}


def 读取有效分享(share_id: str) -> Optional[Dict[str, Any]]:
    """读取未过期的分享链接（公开接口用，无需 user_id）。返回 None 表示不存在或已过期。"""
    初始化分享表()
    now = _now_iso()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT share_id, user_id, report_id, expires_at, created_at "
            "FROM share_links WHERE share_id = ? AND expires_at > ?",
            (share_id, now),
        ).fetchone()
    if row is None:
        return None
    return {
        "share_id": row["share_id"],
        "user_id": row["user_id"],
        "report_id": row["report_id"],
        "过期时间": row["expires_at"],
        "创建时间": row["created_at"],
    }


def 按报表列出(user_id: str, report_id: str) -> List[Dict[str, Any]]:
    """列出指定报表的分享链接（仅创建者）。"""
    初始化分享表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT share_id, expires_at, created_at FROM share_links "
            "WHERE user_id = ? AND report_id = ? ORDER BY created_at DESC",
            (user_id, report_id),
        ).fetchall()
    return [
        {"链接ID": row["share_id"], "过期时间": row["expires_at"], "创建时间": row["created_at"]}
        for row in rows
    ]


def 撤销分享(user_id: str, share_id: str) -> bool:
    """撤销分享（仅创建者）。返回 True 表示成功删除。"""
    初始化分享表()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM share_links WHERE share_id = ? AND user_id = ?",
            (share_id, user_id),
        )
        deleted = cur.rowcount > 0
    if deleted:
        logger.info("撤销分享 %s（用户 %s）", share_id, user_id)
    return deleted