"""看板仓储：dashboards 表的 CRUD。

看板 = 用户命名的一批报表（report_ids JSON 数组列），用户按 user_id 隔离。
删除报表时看板中的引用会悬空，读取看板详情时后端会跳过已删除的报表。
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化看板表() -> None:
    """幂等创建 dashboards 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboards (
                dashboard_id TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                name         TEXT NOT NULL,
                report_ids   TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_dashboards_user_created_at
            ON dashboards (user_id, created_at)
            """
        )


def 保存看板(user_id: str, name: str, report_ids: List[str]) -> str:
    """新建看板，返回 dashboard_id。"""
    初始化看板表()
    dashboard_id = uuid.uuid4().hex
    now = _now_iso()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO dashboards (dashboard_id, user_id, name, report_ids, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (dashboard_id, user_id, name,
             json.dumps(report_ids, ensure_ascii=False), now, now),
        )
    logger.info("保存看板 %s（用户 %s，%d 张报表）", dashboard_id, user_id, len(report_ids))
    return dashboard_id


def 更新看板(user_id: str, dashboard_id: str, name: str, report_ids: List[str]) -> bool:
    """更新已有看板（名称 + 报表列表），仅限归属用户。"""
    初始化看板表()
    now = _now_iso()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            "UPDATE dashboards SET name = ?, report_ids = ?, updated_at = ? "
            "WHERE dashboard_id = ? AND user_id = ?",
            (name, json.dumps(report_ids, ensure_ascii=False), now, dashboard_id, user_id),
        )
        updated = cur.rowcount > 0
    if updated:
        logger.info("更新看板 %s（用户 %s）", dashboard_id, user_id)
    return updated


def 列出看板(user_id: str) -> List[Dict[str, Any]]:
    """列出某用户的看板（按创建时间倒序）。"""
    初始化看板表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT dashboard_id, name, report_ids, created_at "
            "FROM dashboards WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [
        {
            "看板ID": row["dashboard_id"],
            "名称": row["name"],
            "报表数": len(json.loads(row["report_ids"])),
            "创建时间": row["created_at"],
        }
        for row in rows
    ]


def 读取看板(user_id: str, dashboard_id: str) -> Optional[Dict[str, Any]]:
    """读取一份看板（仅限归属用户）。"""
    初始化看板表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT dashboard_id, name, report_ids, created_at "
            "FROM dashboards WHERE dashboard_id = ? AND user_id = ?",
            (dashboard_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "看板ID": row["dashboard_id"],
        "名称": row["name"],
        "报表ID列表": json.loads(row["report_ids"]),
        "创建时间": row["created_at"],
    }


def 删除看板(user_id: str, dashboard_id: str) -> bool:
    """删除一份看板（仅限归属用户）。"""
    初始化看板表()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM dashboards WHERE dashboard_id = ? AND user_id = ?",
            (dashboard_id, user_id),
        )
        deleted = cur.rowcount > 0
    if deleted:
        logger.info("删除看板 %s（用户 %s）", dashboard_id, user_id)
    return deleted