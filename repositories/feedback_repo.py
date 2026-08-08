"""用户反馈仓储（B8 修复：feedback 落库，不再假实现丢弃）。"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化反馈表() -> None:
    """幂等创建 feedback 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                task_id     TEXT NOT NULL DEFAULT '',
                score       INTEGER NOT NULL,
                correction  TEXT NOT NULL DEFAULT '',
                sync_kb     INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL
            )
            """
        )


def 保存反馈(user_id: str, task_id: str, score: int, correction: str, sync_kb: bool) -> int:
    """保存一条反馈，返回自增 id。"""
    初始化反馈表()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO feedback (user_id, task_id, score, correction, sync_kb, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, task_id, score, correction[:1000], 1 if sync_kb else 0, _now_iso()),
        )
        return int(cur.lastrowid)


def 按任务查询(task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """查询某任务的全部反馈（新→旧）。"""
    初始化反馈表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, user_id, task_id, score, correction, sync_kb, created_at "
            "FROM feedback WHERE task_id = ? ORDER BY id DESC LIMIT ?",
            (task_id, limit),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "任务ID": row["task_id"],
            "评分": row["score"],
            "纠错内容": row["correction"],
            "同步知识库": bool(row["sync_kb"]),
            "时间": row["created_at"],
        }
        for row in rows
    ]