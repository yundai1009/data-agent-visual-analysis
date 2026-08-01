"""报表仓储：reports 表的 CRUD。

报表以 JSON 全文存储（report_json 列），用户按 user_id + report_id 隔离。
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


def 初始化报表表() -> None:
    """幂等创建 reports 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reports (
                report_id    TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                dataset_id   TEXT NOT NULL,
                title        TEXT NOT NULL,
                chart_type   TEXT NOT NULL,
                report_json  TEXT NOT NULL,
                created_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reports_user_created_at
            ON reports (user_id, created_at)
            """
        )


def 保存报表(user_id: str, dataset_id: str, title: str, chart_type: str, report: Dict[str, Any]) -> str:
    """保存一份报表，返回 report_id。"""
    初始化报表表()
    report_id = uuid.uuid4().hex
    now = _now_iso()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO reports (report_id, user_id, dataset_id, title, chart_type, report_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (report_id, user_id, dataset_id, title, chart_type,
             json.dumps(report, ensure_ascii=False, default=str), now),
        )
    logger.info("保存报表 %s（用户 %s）", report_id, user_id)
    return report_id


def 读取报表(user_id: str, report_id: str) -> Optional[Dict[str, Any]]:
    """读取一份报表（仅限归属用户）。"""
    初始化报表表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT report_id, user_id, dataset_id, title, chart_type, report_json, created_at "
            "FROM reports WHERE report_id = ? AND user_id = ?",
            (report_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "报表ID": row["report_id"],
        "数据集ID": row["dataset_id"],
        "标题": row["title"],
        "图表类型": row["chart_type"],
        "报表": json.loads(row["report_json"]),
        "创建时间": row["created_at"],
    }


def 列出报表(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """列出某用户最近的报表（按创建时间倒序）。"""
    初始化报表表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT report_id, dataset_id, title, chart_type, created_at "
            "FROM reports WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [
        {
            "报表ID": row["report_id"],
            "数据集ID": row["dataset_id"],
            "标题": row["title"],
            "图表类型": row["chart_type"],
            "创建时间": row["created_at"],
        }
        for row in rows
    ]


def 删除报表(user_id: str, report_id: str) -> bool:
    """删除一份报表（仅限归属用户）。"""
    初始化报表表()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM reports WHERE report_id = ? AND user_id = ?",
            (report_id, user_id),
        )
        deleted = cur.rowcount > 0
    if deleted:
        logger.info("删除报表 %s（用户 %s）", report_id, user_id)
    return deleted
