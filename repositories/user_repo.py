"""用户仓储：users 表的 CRUD。

复用 后端_核心/存储/sqlite_repo.py 的连接管理（_get_conn / _write_lock），
避免重复实现 SQLite 连接逻辑。
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化用户表() -> None:
    """幂等创建 users 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """
        )


def 创建用户(username: str, password_hash: str, role: str = "analyst") -> Dict[str, Any]:
    """创建用户，返回用户信息。用户名冲突抛 ValueError。"""
    初始化用户表()
    user_id = f"u_{__import__('secrets').token_hex(8)}"
    now = _now_iso()
    try:
        with _write_lock, _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, password_hash, role, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, password_hash, role, now, now),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise ValueError(f"用户名已存在：{username}") from exc
        raise
    logger.info("创建用户 %s (%s)", username, role)
    return {
        "user_id": user_id,
        "username": username,
        "role": role,
        "created_at": now,
    }


def 按用户名查询(username: str) -> Optional[Dict[str, Any]]:
    """按用户名查用户（含密码哈希，仅认证用）。"""
    初始化用户表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, username, password_hash, role, created_at, updated_at "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "password_hash": row["password_hash"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def 按ID查询(user_id: str) -> Optional[Dict[str, Any]]:
    """按 ID 查用户（不含密码哈希，供 /auth/me 用）。"""
    初始化用户表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, username, role, created_at, updated_at "
            "FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "role": row["role"],
        "created_at": row["created_at"],
    }
