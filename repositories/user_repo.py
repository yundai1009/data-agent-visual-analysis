"""用户仓储：users 表的 CRUD。

复用 后端_核心/存储/sqlite_repo.py 的连接管理（_get_conn / _write_lock），
避免重复实现 SQLite 连接逻辑。
"""

from __future__ import annotations

import logging
import secrets
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
        # 账号级 LLM Key（BYOK 后端存储）：旧库幂等迁移
        if "llm_api_key" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN llm_api_key TEXT")
            logger.info("users 表已迁移：新增 llm_api_key 列")
        # 用户自定义 LLM 供应商（JSON 数组，阶段 13.6）
        if "llm_custom_providers" not in columns:
            conn.execute("ALTER TABLE users ADD COLUMN llm_custom_providers TEXT")
            logger.info("users 表已迁移：新增 llm_custom_providers 列")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)"
        )


def 创建用户(username: str, password_hash: str, role: str = "analyst", email: Optional[str] = None) -> Dict[str, Any]:
    """创建用户，返回用户信息。用户名或邮箱冲突抛 ValueError（含具体原因）。"""
    初始化用户表()
    user_id = f"u_{secrets.token_hex(8)}"
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


# ---- 账号级 LLM Key（BYOK 后端存储）----


def 保存LLMKey(user_id: str, api_key: str) -> None:
    """保存账号级 LLM Key（明文存库，仅服务端使用，不回传前端）。"""
    初始化用户表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE users SET llm_api_key = ?, updated_at = ? WHERE user_id = ?",
            (api_key.strip(), _now_iso(), user_id),
        )


def 读取LLMKey(user_id: str) -> str:
    """读取账号级 LLM Key；未配置返回空串。"""
    初始化用户表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT llm_api_key FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return (row["llm_api_key"] or "") if row else ""


def 清除LLMKey(user_id: str) -> None:
    """清除账号级 LLM Key。"""
    初始化用户表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE users SET llm_api_key = NULL, updated_at = ? WHERE user_id = ?",
            (_now_iso(), user_id),
        )


# ---- 用户自定义 LLM 供应商（阶段 13.6，参考 Reasonix 自定义供应商）----

import json as _json


def 读取自定义供应商(user_id: str) -> list:
    """读取用户自定义 LLM 供应商列表（JSON 数组）。"""
    初始化用户表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT llm_custom_providers FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    raw = (row["llm_custom_providers"] if row else "") or ""
    try:
        data = _json.loads(raw)
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


def 保存自定义供应商(user_id: str, providers: list) -> None:
    """整体保存用户自定义 LLM 供应商列表（JSON 数组）。"""
    初始化用户表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE users SET llm_custom_providers = ?, updated_at = ? WHERE user_id = ?",
            (_json.dumps(providers, ensure_ascii=False), _now_iso(), user_id),
        )
