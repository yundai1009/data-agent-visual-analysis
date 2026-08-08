"""操作审计日志仓储（P2 加固：合规与问题追溯）。

记录关键安全操作（登录/改密/删除/导出/分享撤销等）的 who/what/when；
管理员可查询最近 N 条。只追加、不删除（审计完整性）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化审计表() -> None:
    """幂等创建 audit_log 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                username    TEXT NOT NULL DEFAULT '',
                action      TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT '',
                target_id   TEXT NOT NULL DEFAULT '',
                detail      TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_created
            ON audit_log (created_at)
            """
        )


def 记录(
    user_id: str,
    action: str,
    username: str = "",
    target_type: str = "",
    target_id: str = "",
    detail: str = "",
) -> None:
    """追加一条审计记录（失败不阻塞业务）。"""
    try:
        初始化审计表()
        with _write_lock, _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (user_id, username, action, target_type, target_id, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username[:50], action[:50], target_type[:30], target_id[:64],
                 str(detail)[:300], _now_iso()),
            )
    except Exception as exc:
        logger.warning("审计记录失败（不影响业务）: %s", exc)


def 查询(limit: int = 50, offset: int = 0, user_id: str = "") -> List[Dict[str, Any]]:
    """查询审计日志（管理员用，默认最近 50 条；可按 user_id 过滤）。"""
    初始化审计表()
    sql = "SELECT id, user_id, username, action, target_type, target_id, detail, created_at FROM audit_log"
    params: list = []
    if user_id:
        sql += " WHERE user_id = ?"
        params.append(user_id)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": row["id"],
            "用户ID": row["user_id"],
            "用户名": row["username"],
            "操作": row["action"],
            "对象类型": row["target_type"],
            "对象ID": row["target_id"],
            "详情": row["detail"],
            "时间": row["created_at"],
        }
        for row in rows
    ]