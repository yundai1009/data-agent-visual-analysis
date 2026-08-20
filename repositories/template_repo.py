"""报表模板仓储：report_templates 表的 CRUD（阶段 30 · 报表模板）。

模板 = 一份"分析配置"的收藏（数据集 + 分析需求 + 字段/图表/筛选/TopN + 模式），
保存为 JSON 全文存储；定时任务（scheduled_jobs）引用模板 ID 按 cron 重复执行。
用户按 user_id + template_id 隔离。
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


def 初始化模板表() -> None:
    """幂等创建 report_templates 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS report_templates (
                template_id  TEXT PRIMARY KEY,
                user_id      TEXT NOT NULL,
                name         TEXT NOT NULL,
                dataset_id   TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_templates_user_created
            ON report_templates (user_id, created_at)
            """
        )


def 保存模板(user_id: str, name: str, payload: Dict[str, Any], template_id: Optional[str] = None) -> str:
    """保存模板（无 id 新增、有 id 覆盖更新），返回 template_id。"""
    初始化模板表()
    now = _now_iso()
    tid = template_id or uuid.uuid4().hex
    payload_json = json.dumps(payload, ensure_ascii=False, default=str)
    with _write_lock, _get_conn() as conn:
        # M12：SELECT-then-INSERT 存在 TOCTOU——并发同 id 保存时两个连接都查不到
        # 记录 → 双 INSERT 撞主键。改用单语句 UPSERT（ON CONFLICT DO UPDATE）原子化。
        conn.execute(
            """
            INSERT INTO report_templates (template_id, user_id, name, dataset_id, payload_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(template_id) DO UPDATE SET
                name = excluded.name,
                dataset_id = excluded.dataset_id,
                payload_json = excluded.payload_json,
                updated_at = excluded.updated_at
            """,
            (tid, user_id, name, payload.get("数据集ID", ""), payload_json, now, now),
        )
    logger.info("保存模板 %s（用户 %s）", tid, user_id)
    return tid


def 读取模板(user_id: str, template_id: str) -> Optional[Dict[str, Any]]:
    """读取一份模板（仅限归属用户）。"""
    初始化模板表()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT template_id, name, dataset_id, payload_json, created_at, updated_at "
            "FROM report_templates WHERE template_id = ? AND user_id = ?",
            (template_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return {
        "模板ID": row["template_id"],
        "名称": row["name"],
        "数据集ID": row["dataset_id"],
        "payload": json.loads(row["payload_json"]),
        "创建时间": row["created_at"],
        "更新时间": row["updated_at"],
    }


def 搜索模板名称(user_id: str, q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """优化⑧：按名称模糊搜索模板（供全局搜索）。"""
    初始化模板表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT template_id, name, dataset_id, updated_at "
            "FROM report_templates WHERE user_id = ? AND name LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (user_id, f"%{q}%", limit),
        ).fetchall()
    return [
        {"模板ID": row["template_id"], "名称": row["name"], "数据集ID": row["dataset_id"], "更新时间": row["updated_at"]}
        for row in rows
    ]


def 列出模板(user_id: str) -> List[Dict[str, Any]]:
    """列出某用户的全部模板（按更新时间倒序）。"""
    初始化模板表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT template_id, name, dataset_id, created_at, updated_at "
            "FROM report_templates WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [
        {
            "模板ID": row["template_id"],
            "名称": row["name"],
            "数据集ID": row["dataset_id"],
            "创建时间": row["created_at"],
            "更新时间": row["updated_at"],
        }
        for row in rows
    ]


def 删除模板(user_id: str, template_id: str) -> bool:
    """删除模板（仅限归属用户）。"""
    初始化模板表()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            "DELETE FROM report_templates WHERE template_id = ? AND user_id = ?",
            (template_id, user_id),
        )
        deleted = cur.rowcount > 0
    if deleted:
        logger.info("删除模板 %s（用户 %s）", template_id, user_id)
    return deleted