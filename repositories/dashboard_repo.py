# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】dashboards 表的唯一出入口：把用户命名的一批报表（report_ids JSON 数组）打包成看板。
# ============================================================
# 【做了什么】
#   1. 建 dashboards 表 + idx_dashboards_user_created_at(user_id, created_at) 索引。
#   2. 保存/更新/删除/读取/列出看板五个对外函数全部按 user_id 过滤，越权即查不到；列出只回「报表数」，读详情才回 ID 列表。
#   3. report_ids 存 JSON 数组文本，损坏数据由 _safe_loads 兜底而不是抛 500（M11）。
# 【为什么这么做】
#   - 用 JSON 数组列而不是关联表：成员有序、随看板整体读写、两种后端都能存文本；代价是不能 JOIN，详情接口改用 批量读取报表 一次取回消除 N+1，删报表也不反查清理（一份报表可属多看板），悬空引用由路由读不到就跳过。
# 【关键约定与坑】
#   - user_id 过滤是硬约定；更新与删除靠 cur.rowcount 判断成败，路由据此统一转 404。
#   - 初始化看板表 未做进程级缓存（每次跑 DDL 与索引检查），与 report_repo 的 Fix E1 不同；连接走 存储/连接._get_conn，写操作加 backend.写锁。
# ============================================================

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from 后端_核心.存储.backend import 写锁 as _write_lock
from 后端_核心.存储.backend import 创建索引SQL as _建索引SQL, 当前后端 as _后端
from 后端_核心.存储.连接 import _get_conn   # 阶段 54-8：统一连接入口（按 DB_BACKEND 分发）

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化看板表() -> None:
    """幂等创建 dashboards 表。"""
    if _后端() == "mysql":
        return  # 阶段 54-8：表结构由 mysql_repo.初始化数据库 统一管理（sqlite DDL 在 MySQL 下语义校验即报错）
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
        _sql = _建索引SQL(_后端(), "idx_dashboards_user_created_at", "dashboards", "(user_id, created_at)")
        if _sql:
            conn.execute(_sql)


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
            # M11：report_ids JSON 损坏时兜底为空列表（此前 json.loads 抛错 → 500）
            "报表数": len(_safe_loads(row["report_ids"])),
            "创建时间": row["created_at"],
        }
        for row in rows
    ]


def _safe_loads(raw: str, fallback: Any = None) -> Any:
    """M11：JSON 解析兜底——损坏数据返回 fallback 而非抛 500。"""
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return fallback


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
        # M11：损坏 JSON 兜底为空列表
        "报表ID列表": _safe_loads(row["report_ids"], []),
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