"""邮箱验证码仓储：email_codes 表的 CRUD。

表以 email 为主键（同邮箱覆盖旧码），验证码存哈希（code_hash），
防数据库泄露后被直接重放。复用 sqlite_repo 的连接管理。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化验证码表() -> None:
    """幂等创建 email_codes 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS email_codes (
                email           TEXT PRIMARY KEY,
                code_hash       TEXT NOT NULL,
                expires_at      TEXT NOT NULL,
                used            INTEGER NOT NULL DEFAULT 0,
                verify_attempts INTEGER NOT NULL DEFAULT 0,
                last_sent_at    TEXT NOT NULL,
                created_at      TEXT NOT NULL
            )
            """
        )


def 保存验证码(email: str, code_hash: str, expires_at: str) -> None:
    """保存验证码（同邮箱覆盖旧码）。"""
    初始化验证码表()
    now = _now_iso()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO email_codes (email, code_hash, expires_at, used, verify_attempts, last_sent_at, created_at)
            VALUES (?, ?, ?, 0, 0, ?, ?)
            ON CONFLICT(email) DO UPDATE SET
                code_hash = excluded.code_hash,
                expires_at = excluded.expires_at,
                used = 0,
                verify_attempts = 0,
                last_sent_at = excluded.last_sent_at
            """,
            (email, code_hash, expires_at, now, now),
        )


def 查询验证码(email: str) -> Optional[Dict[str, Any]]:
    """按邮箱取最新验证码记录（含哈希、有效期、使用状态、尝试次数）。"""
    初始化验证码表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT email, code_hash, expires_at, used, verify_attempts, last_sent_at, created_at "
            "FROM email_codes WHERE email = ?",
            (email,),
        ).fetchone()
    if row is None:
        return None
    return {
        "email": row["email"],
        "code_hash": row["code_hash"],
        "expires_at": row["expires_at"],
        "used": bool(row["used"]),
        "verify_attempts": row["verify_attempts"],
        "last_sent_at": row["last_sent_at"],
    }


def 标记已用(email: str) -> None:
    """验证码校验通过后标记已用（防重放）。"""
    初始化验证码表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE email_codes SET used = 1 WHERE email = ?",
            (email,),
        )


def 增加尝试次数(email: str) -> None:
    """验证码校验失败时累计尝试次数（用于校验限频）。"""
    初始化验证码表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE email_codes SET verify_attempts = verify_attempts + 1 WHERE email = ?",
            (email,),
        )


def 清理过期记录() -> int:
    """删除已过期且未使用的验证码记录，返回清理条数。"""
    初始化验证码表()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute("DELETE FROM email_codes WHERE expires_at < ?", (_now_iso(),))
        return cur.rowcount
