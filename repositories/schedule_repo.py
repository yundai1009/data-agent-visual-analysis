"""定时任务仓储：scheduled_jobs 表的 CRUD（阶段 30 · 定时生成）。

定时任务 = 模板 + cron 表达式：到点自动用模板配置 + 数据集最新数据生成报表，
报表落入用户自己的报表历史（与手动生成完全一致）。
用户按 user_id + job_id 隔离。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化任务表() -> None:
    """幂等创建 scheduled_jobs 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id       TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                template_id  TEXT NOT NULL,
                cron_expr    TEXT NOT NULL,
                enabled      INTEGER NOT NULL DEFAULT 1,
                last_run_at  TEXT,
                last_status  TEXT,
                created_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_jobs_enabled
            ON scheduled_jobs (enabled)
            """
        )


def 创建任务(user_id: str, template_id: str, cron_expr: str) -> str:
    """创建定时任务（默认启用）。"""
    初始化任务表()
    job_id = uuid.uuid4().hex
    now = _now_iso()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO scheduled_jobs (job_id, user_id, template_id, cron_expr, enabled, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (job_id, user_id, template_id, cron_expr, now),
        )
    logger.info("创建定时任务 %s（用户 %s，cron=%s）", job_id, user_id, cron_expr)
    return job_id


def 读取任务(user_id: str, job_id: str) -> Optional[Dict[str, Any]]:
    初始化任务表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT job_id, template_id, cron_expr, enabled, last_run_at, last_status, created_at "
            "FROM scheduled_jobs WHERE job_id = ? AND user_id = ?",
            (job_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "任务ID": row["job_id"],
        "模板ID": row["template_id"],
        "cron": row["cron_expr"],
        "启用": bool(row["enabled"]),
        "上次执行": row["last_run_at"],
        "上次状态": row["last_status"],
        "创建时间": row["created_at"],
    }


def 列出任务(user_id: str) -> List[Dict[str, Any]]:
    初始化任务表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT job_id, template_id, cron_expr, enabled, last_run_at, last_status, created_at "
            "FROM scheduled_jobs WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [
        {
            "任务ID": row["job_id"],
            "模板ID": row["template_id"],
            "cron": row["cron_expr"],
            "启用": bool(row["enabled"]),
            "上次执行": row["last_run_at"],
            "上次状态": row["last_status"],
            "创建时间": row["created_at"],
        }
        for row in rows
    ]


def 删除任务(user_id: str, job_id: str) -> bool:
    初始化任务表()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM scheduled_jobs WHERE job_id = ? AND user_id = ?",
            (job_id, user_id),
        )
        deleted = cur.rowcount > 0
    if deleted:
        logger.info("删除定时任务 %s（用户 %s）", job_id, user_id)
    return deleted


def 记录执行结果(user_id: str, job_id: str, status: str) -> None:
    """更新任务的 last_run_at / last_status（调度线程调用）。"""
    初始化任务表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "UPDATE scheduled_jobs SET last_run_at = ?, last_status = ? "
            "WHERE job_id = ? AND user_id = ?",
            (_now_iso(), status, job_id, user_id),
        )


def 查启用的任务() -> List[Dict[str, Any]]:
    """调度线程用：全部启用中的任务（跨用户）。"""
    初始化任务表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT job_id, user_id, template_id, cron_expr, last_run_at "
            "FROM scheduled_jobs WHERE enabled = 1",
        ).fetchall()
    return [
        {
            "任务ID": row["job_id"],
            "用户ID": row["user_id"],
            "模板ID": row["template_id"],
            "cron": row["cron_expr"],
            "上次执行": row["last_run_at"],
        }
        for row in rows
    ]