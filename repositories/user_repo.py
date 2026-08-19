"""用户仓储：users 表的 CRUD。

复用 后端_核心/存储/sqlite_repo.py 的连接管理（_get_conn / _write_lock），
避免重复实现 SQLite 连接逻辑。
"""

from __future__ import annotations

import logging
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
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
        # M9：ALTER 迁移加 try/except——冷启动多进程/多测试 client 并发执行
        # 迁移时，两个连接同时通过列检查后先后 ALTER，后者报 duplicate column；
        # 捕获该异常视为"列已存在"（幂等迁移语义）。
        if "email" not in columns:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN email TEXT")
            except Exception as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
            logger.info("users 表已迁移：新增 email 列")
        # 账号级 LLM Key（BYOK 后端存储）：旧库幂等迁移
        if "llm_api_key" not in columns:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN llm_api_key TEXT")
            except Exception as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
            logger.info("users 表已迁移：新增 llm_api_key 列")
        # 用户自定义 LLM 供应商（JSON 数组，阶段 13.6）
        if "llm_custom_providers" not in columns:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN llm_custom_providers TEXT")
            except Exception as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
        # P1 加固：token_version（改密/改用户名时 +1，旧 JWT 吊销）
        if "token_version" not in columns:
            try:
                conn.execute("ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 0")
            except Exception as exc:
                if "duplicate column" not in str(exc).lower():
                    raise
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
    - 存在且已是 admin：不动
    - 存在但角色非 admin：S3 修复——抛 ValueError 拒绝升级。
      旧行为"静默升级为 admin"存在提权漏洞：演示模式（AUTH_ENABLED=false）
      下注册的同名普通用户（保留原密码）会在正式启动时被悄悄提权为管理员。
      正确姿势是拒绝并让运维更换种子管理员用户名，而不是改写他人账号角色。
    - 不存在：创建 admin 用户
    """
    初始化用户表()
    user = 按用户名查询(username)
    if user:
        if user["role"] != "admin":
            raise ValueError(
                f"种子管理员用户名「{username}」已被同名非管理员用户占用，"
                "拒绝静默提权；请更换 SEED_ADMIN_USERNAME 后重启"
            )
        return user
    return 创建用户(username, password_hash, role="admin")


# ---- 账号级 LLM Key（BYOK 后端存储）----


def 保存LLMKey(user_id: str, api_key: str) -> None:
    """保存账号级 LLM Key（P1 加固：加密后落库，仅服务端使用，不回传前端）。"""
    初始化用户表()
    from services.crypto import 加密
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE users SET llm_api_key = ?, updated_at = ? WHERE user_id = ?",
            (加密(api_key.strip()), _now_iso(), user_id),
        )


def 读取LLMKey(user_id: str) -> str:
    """读取账号级 LLM Key（解密返回）；未配置返回空串；历史明文兼容。"""
    初始化用户表()
    from services.crypto import 解密
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT llm_api_key FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    stored = (row["llm_api_key"] or "") if row else ""
    if not stored:
        return ""
    try:
        return 解密(stored)
    except ValueError:
        # M6：解密失败（历史明文/密钥轮换）→ 视为未配置，安全降级不泄露
        logger.warning("LLM Key 解密失败，按未配置处理（user=%s）", user_id)
        return ""


def 清除LLMKey(user_id: str) -> None:
    """清除账号级 LLM Key。"""
    初始化用户表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE users SET llm_api_key = NULL, updated_at = ? WHERE user_id = ?",
            (_now_iso(), user_id),
        )


def 读取token版本(user_id: str) -> Optional[int]:
    """读取用户 token_version（P1 加固：JWT 吊销用）。

    S4 修复：用户不存在返回 None（而非 0）——旧行为使删号用户的旧 JWT
    （ver=0）仍能通过吊销对账，形成"删号后旧 token 继续有效"的漏洞；
    调用方拿到 None 必须拒绝（401）。
    """
    初始化用户表()
    with _get_conn() as conn:
        row = conn.execute("SELECT token_version FROM users WHERE user_id = ?", (user_id,)).fetchone()
    return int(row["token_version"] or 0) if row else None


def 增加token版本(user_id: str) -> None:
    """token_version +1：使已签发的旧 JWT 全部失效（改密/改用户名时调用）。"""
    初始化用户表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE users SET token_version = token_version + 1, updated_at = ? WHERE user_id = ?",
            (_now_iso(), user_id),
        )


def 删除用户及数据(user_id: str) -> None:
    """D：注销——删除用户及其全部业务数据（数据集/报表/看板/分享/反馈/审计）。

    事务内多表删除（注销请求一并清除审计中的个人标识）；chromadb 记忆同步按 user 清理。
    """
    初始化用户表()
    try:
        from 后端_核心.agent.记忆 import 删除用户记忆
        删除用户记忆(user_id)  # 记忆向量库按 user 清理
    except Exception as _exc:
        logger.warning("删除记忆失败（不影响主库删除）: %s", _exc)
    with _write_lock, _get_conn() as conn:
        # 确保所有表存在（用户可能从未使用某功能，表未初始化时 DELETE 报 no such table）
        from 后端_核心.存储.sqlite_repo import 初始化数据库
        from repositories import audit_repo, dashboard_repo, feedback_repo, report_repo, share_repo
        初始化数据库()
        report_repo.初始化报表表()
        dashboard_repo.初始化看板表()
        share_repo.初始化分享表()
        feedback_repo.初始化反馈表()
        audit_repo.初始化审计表()
        for table in ("datasets", "reports", "dashboards", "share_links", "feedback", "audit_log", "users"):
            if table == "datasets":
                # P0 修复：级联删除数据集时同步清理 data/uploads/ 物理文件副本
                for row in conn.execute("SELECT stored_path FROM datasets WHERE user_id = ?", (user_id,)):
                    try:
                        Path(row["stored_path"]).unlink(missing_ok=True)
                    except Exception as exc:
                        logger.warning("注销清理数据集物理文件失败 %s: %s", row["stored_path"], exc)
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
    logger.info("已删除用户及全部数据: %s", user_id)
    return True


def 按用户ID查询(user_id: str) -> Optional[Dict[str, Any]]:
    """按 user_id 查询（含密码哈希）。"""
    初始化用户表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT user_id, username, password_hash, role, email, created_at, updated_at "
            "FROM users WHERE user_id = ?",
            (user_id,),
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


def 更新密码(user_id: str, new_hash: str) -> None:
    """更新用户密码哈希。"""
    初始化用户表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE user_id = ?",
            (new_hash, _now_iso(), user_id),
        )


def 更新用户名(user_id: str, new_username: str) -> None:
    """更新用户名；用户名唯一冲突抛 ValueError；用户不存在也抛异常（防假成功）。"""
    初始化用户表()
    try:
        with _write_lock, _get_conn() as conn:
            cur = conn.execute(
                "UPDATE users SET username = ?, updated_at = ? WHERE user_id = ?",
                (new_username, _now_iso(), user_id),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc):
            raise ValueError(f"用户名已存在：{new_username}") from exc
        raise
    # UPDATE 影响 0 行 = 用户不存在（此前静默"假成功"，演示模式 demo 用户改名即此场景）
    if cur.rowcount == 0:
        raise ValueError("用户不存在，无法修改")


# ---- 用户自定义 LLM 供应商（阶段 13.6，参考 Reasonix 自定义供应商）----

import json as _json


def 读取自定义供应商(user_id: str) -> list:
    """读取用户自定义 LLM 供应商列表（JSON 数组；api_key 解密，历史明文兼容）。"""
    初始化用户表()
    from services.crypto import 解密
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT llm_custom_providers FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    raw = (row["llm_custom_providers"] if row else "") or ""
    try:
        data = _json.loads(raw)
        if not isinstance(data, list):
            return []
        for p in data:
            if isinstance(p, dict) and p.get("api_key"):
                try:
                    p["api_key"] = 解密(p["api_key"])
                except ValueError:
                    # M6：历史明文/密钥轮换导致解密失败 → 该供应商 Key 视为无效
                    p["api_key"] = ""
        return data
    except (ValueError, TypeError):
        return []


def 保存自定义供应商(user_id: str, providers: list) -> None:
    """整体保存用户自定义 LLM 供应商列表（JSON 数组；api_key 加密落库）。"""
    初始化用户表()
    from services.crypto import 加密
    import copy as _copy
    stored = _copy.deepcopy(providers)
    for p in stored:
        if isinstance(p, dict) and p.get("api_key"):
            p["api_key"] = 加密(p["api_key"])
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE users SET llm_custom_providers = ?, updated_at = ? WHERE user_id = ?",
            (_json.dumps(stored, ensure_ascii=False), _now_iso(), user_id),
        )
