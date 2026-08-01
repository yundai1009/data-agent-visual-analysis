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
    """幂等创建 users 表，并对旧库做 email 列幂等迁移。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL,
                email         TEXT,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """
        )
        # 旧库幂等迁移：缺 email 列则补列（SQLite 的 ALTER TABLE ADD COLUMN
        # 不允许带 UNIQUE 约束，因此用唯一索引实现邮箱唯一；多个 NULL 不冲突）
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
        if "email" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            logger.info("users 表已迁移：新增 email 列")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)"
        )


def 创建用户(username: str, password_hash: str, role: str = "analyst", email: Optional[str] = None) -> Dict[str, Any]:
    """创建用户，返回用户信息。用户名或邮箱冲突抛 ValueError（含具体原因）。"""
    初始化用户表()
    user_id = f"u_{__import__('secrets').token_hex(8)}"
    now = _now_iso()
    try:
        with _write_lock, _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, username, password_hash, role, email, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username, password_hash, role, email, now, now),
            )
    except Exception as exc:
        message = str(exc)
        if "UNIQUE" in message:
            if "email" in message:
                raise ValueError(f"邮箱已被注册：{email}") from exc
            raise ValueError(f"用户名已存在：{username}") from exc
        raise
    logger.info("创建用户 %s (%s)", username, role)
    return {
        "user_id": user_id,
        "username": username,
        "role": role,
        "email": email,
        "created_at": now,
    }


def 按用户名查询(username: str) -> Optional[Dict[str, Any]]:
    """按用户名查用户（含密码哈希，仅认证用）。"""
    初始化用户表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, username, password_hash, role, email, created_at, updated_at "
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
        "email": row["email"],
        "created_at": row["created_at"],
    }


def 按邮箱查询(email: str) -> Optional[Dict[str, Any]]:
    """按邮箱查用户（含密码哈希，仅认证用）。"""
    初始化用户表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, username, password_hash, role, email, created_at, updated_at "
            "FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if row is None:
        return None
    return {
        "user_id": row["user_id"],
        "username": row["username"],
        "password_hash": row["password_hash"],
        "role": row["role"],
        "email": row["email"],
        "created_at": row["created_at"],
    }


def 确保管理员存在(username: str, password_hash: str) -> Dict[str, Any]:
    """幂等确保指定用户名的种子管理员存在。

    按 SEED_ADMIN_USERNAME 精确匹配（而非"任意 admin 存在就跳过"）：
    - 存在：角色已是 admin 则不动；否则升级为 admin 并告警
    - 不存在：创建 admin 用户
    """
    初始化用户表()
    user = 按用户名查询(username)
    if user:
        if user["role"] != "admin":
            with _write_lock, _get_conn() as conn:
                conn.execute(
                    "UPDATE users SET role = 'admin', updated_at = ? WHERE user_id = ?",
                    (_now_iso(), user["user_id"]),
                )
            logger.warning("用户 %s 已存在但角色非 admin，已升级为 admin", username)
        return user
    return 创建用户(username, password_hash, role="admin")
