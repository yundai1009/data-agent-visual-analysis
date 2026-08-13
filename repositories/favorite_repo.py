"""报表收藏仓储：favorites 表的 CRUD（阶段 31 · 收藏）。

收藏 = 报表的星标（user_id + report_id 唯一），用于"常用报表快速找"；
列表接口配合 favorites=1 过滤"只看收藏"。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化收藏表() -> None:
    """幂等创建 favorites 表（唯一约束防重复收藏）。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                user_id    TEXT NOT NULL,
                report_id  TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, report_id)
            )
            """
        )


def 切换收藏(user_id: str, report_id: str) -> bool:
    """收藏/取消收藏（存在则删、不存在则加），返回切换后是否已收藏。"""
    初始化收藏表()
    with _write_lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND report_id = ?",
            (user_id, report_id),
        ).fetchone()
        if row:
            conn.execute(
                "DELETE FROM favorites WHERE user_id = ? AND report_id = ?",
                (user_id, report_id),
            )
            return False
        conn.execute(
            "INSERT INTO favorites (user_id, report_id, created_at) VALUES (?, ?, ?)",
            (user_id, report_id, _now_iso()),
        )
        return True


def 是否已收藏(user_id: str, report_id: str) -> bool:
    初始化收藏表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND report_id = ?",
            (user_id, report_id),
        ).fetchone()
    return row is not None


def 已收藏集合(user_id: str) -> set:
    """某用户全部收藏的 report_id 集合（列表接口批量标记用）。"""
    初始化收藏表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT report_id FROM favorites WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    return {row["report_id"] for row in rows}