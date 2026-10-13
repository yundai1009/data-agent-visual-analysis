# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】email_codes 表的唯一出入口：邮箱验证码的签发、核销与失败计数（防重放、防爆破的状态机）。
# ============================================================
# 【做了什么】
#   1. 建 email_codes 表，以 email 为主键，另有 code_hash / expires_at / used / verify_attempts / last_sent_at / created_at。
#   2. 保存验证码：同邮箱 upsert 覆盖旧码并把 used、verify_attempts 重置为 0（方言收敛走 backend.冲突更新SQL）。
#   3. 查询验证码（回哈希与状态）、标记已用（防重放）、增加尝试次数（供限频）、清理过期记录（回删条数）。
# 【为什么这么做】
#   - 只存哈希不存明文：库一旦泄露也不能直接拿去登录，哈希由路由调 email_service.验证码哈希 算好传入；覆盖式 upsert 而不是每邮箱多行取最新，是为了让同一邮箱同时只有一个有效码，用主键把约束交给数据库。
# 【关键约定与坑】
#   - 本表按邮箱而非 user_id 归属（未注册用户也要发码），发信间隔与校验限频判定在路由层；冲突更新 SQL 由 存储/backend.冲突更新SQL 生成（sqlite ON CONFLICT / mysql ON DUPLICATE KEY UPDATE），别手写方言。
#   - 连接走 存储/连接._get_conn，写操作加 backend.写锁；其余 SQL 全 ? 参数化。
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from 后端_核心.存储.backend import 写锁 as _write_lock
from 后端_核心.存储.backend import 冲突更新SQL as _冲突更新SQL, 当前后端 as _后端
from 后端_核心.存储.连接 import _get_conn   # 阶段 54-8：统一连接入口（按 DB_BACKEND 分发）

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化验证码表() -> None:
    """幂等创建 email_codes 表。"""
    if _后端() == "mysql":
        return  # 阶段 54-8：表结构由 mysql_repo.初始化数据库 统一管理（sqlite DDL 在 MySQL 下语义校验即报错）
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
        # upsert（同邮箱覆盖旧码）：方言收敛——sqlite ON CONFLICT / mysql ON DUPLICATE KEY UPDATE
        conn.execute(
            _冲突更新SQL(
                _后端(),
                "email_codes",
                "(email, code_hash, expires_at, used, verify_attempts, last_sent_at, created_at)",
                "(?, ?, ?, 0, 0, ?, ?)",
                "email",
                ["code_hash", "expires_at", "used", "verify_attempts", "last_sent_at"],
            ),
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
