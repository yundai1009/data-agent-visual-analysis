"""分享链接仓储：share_links 表的 CRUD。

分享链接 = 创建者为某份报表生成一条有时效的只读访问令牌（share_id）。
访问者凭 /s/{share_id} 公开访问，无需登录；过期或撤销后失效。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化分享表() -> None:
    """幂等创建 share_links 表（含 password 列；旧表自动迁移补列）。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS share_links (
                share_id   TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                report_id  TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                password   TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_share_links_report
            ON share_links (report_id)
            """
        )
        # 迁移：旧表没有 password 列时补列（ALTER TABLE 幂等由列检查保证）
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(share_links)").fetchall()}
        if "password" not in cols:
            conn.execute("ALTER TABLE share_links ADD COLUMN password TEXT")
        # 阶段 31：协作者白名单（JSON 数组：允许访问的 username 列表；空 = 公开/仅密码）
        if "collaborators" not in cols:
            conn.execute("ALTER TABLE share_links ADD COLUMN collaborators TEXT DEFAULT '[]'")


def _密码哈希(password: str) -> str:
    """HMAC-SHA256（密钥复用 JWT_SECRET_KEY，与验证码同款方案）：分享密码不落明文。"""
    import hashlib
    import hmac as _hmac
    from config.settings import EnvConfig
    return _hmac.new(EnvConfig.JWT_SECRET_KEY.encode(), password.encode(), hashlib.sha256).hexdigest()


def 创建分享(user_id: str, report_id: str, hours: int = 24, password: str = "", collaborators: Optional[List[str]] = None) -> Dict[str, Any]:
    """为指定报表创建分享链接，可设访问密码（password 非空时访问需凭密码，落库仅存哈希）。

    阶段 31：collaborators 为协作者 username 白名单（空 = 公开链接 / 仅密码保护）。
    """
    初始化分享表()
    share_id = uuid.uuid4().hex
    now = _now_iso()
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    password_hash = _密码哈希(password) if password else None
    collaborators_json = json.dumps(list(dict.fromkeys(collaborators or [])), ensure_ascii=False)
    with _write_lock, _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO share_links (share_id, user_id, report_id, expires_at, created_at, password, collaborators)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (share_id, user_id, report_id, expires, now, password_hash, collaborators_json),
        )
    logger.info("创建分享 %s → 报表 %s（%dh%s%s）", share_id, report_id, hours,
               "，带密码" if password else "",
               f"，协作者 {len(collaborators or [])} 人" if collaborators else "")
    return {
        "share_id": share_id, "过期时间": expires, "创建时间": now,
        "需密码": bool(password), "协作者": collaborators or [],
    }


def 读取有效分享(share_id: str) -> Optional[Dict[str, Any]]:
    """读取未过期的分享链接（公开接口用，无需 user_id）。返回 None 表示不存在或已过期。"""
    初始化分享表()
    now = _now_iso()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT share_id, user_id, report_id, expires_at, created_at, password, collaborators "
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
        "密码哈希": row["password"] or "",
        "需密码": bool(row["password"]),
        # 阶段 31：协作者白名单（JSON 列解析；非法 JSON 视为空白名单）
        "协作者": _解析协作者(row["collaborators"]),
    }


def _解析协作者(raw: Optional[str]) -> List[str]:
    try:
        val = json.loads(raw) if raw else []
        return [str(u) for u in val] if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


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