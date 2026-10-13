# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】reports 表的唯一出入口：整块存取「一份图表分析结果」，隔离维度是 user_id。
# ============================================================
# 【做了什么】
#   1. 建 reports 表 + idx_reports_user_created_at 索引（进程级一次性、按 DB 路径分键缓存），供 保存/读取/删除报表；整份图表配置序列化进 report_json 列。
#   2. 列出报表（created_at 倒序 + LIMIT/OFFSET，列表不取 report_json 瘦身）、搜索报表标题（title LIKE %q%）、批量读取报表（一条 IN 查多份，消除看板与公开分享的 N+1）。
#   3. 删除报表时在同一事务里级联清 favorites / share_links（M8），防悬空引用。
# 【为什么这么做】
#   - 报告内容整体存 JSON 列而不拆子表：字段由 LLM 生成、形状不稳定，拆表要么频繁 DDL 要么一堆稀疏列；越权也一律查不到（读 None、删 False）再由路由转 404，不区分「不存在」与「不是你的」。
# 【关键约定与坑】
#   - user_id 过滤是硬约定，每个对外函数都带（新增照做）；SQL 一律 ? 参数化——批量读取的 f-string 只拼占位符个数、不拼值。
#   - 连接只从 存储/连接._get_conn 取（按 DB_BACKEND 分发），写操作加 backend.写锁；report_json 损坏按空报表返回而非 500（M11）。
# ============================================================

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from 后端_核心.存储.backend import 写锁 as _write_lock
from 后端_核心.存储.backend import 创建索引SQL as _建索引SQL, 表存在SQL as _表存在SQL, 当前后端 as _后端
from 后端_核心.存储.连接 import _get_conn   # 阶段 54-8：统一连接入口（按 DB_BACKEND 分发）

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Fix E1（阶段54-9 · 压测 P1-4）：初始化报表表 与 初始化用户表 同批改造——
# 进程级一次性 + 按 DB 路径分键缓存（隔离测试各 tmp_path 各自首次初始化），
# 失败不缓存下次重试；threading.Lock 双重检查防并发重复建表。
_报表表已初始化: Dict[str, bool] = {}
_报表表初始化锁 = threading.Lock()


def _当前db键() -> str:
    """初始化缓存键：SQLite 文件路径（MySQL 分支提前 return，不参与缓存）。"""
    from 后端_核心.存储.sqlite_backend import 解析db路径
    return str(解析db路径())


def _初始化报表表全量() -> None:
    """完整执行 reports 表 DDL（仅首次/失败重试时调用）。"""
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
        _sql = _建索引SQL(_后端(), "idx_reports_user_created_at", "reports", "(user_id, created_at)")
        if _sql:
            conn.execute(_sql)


def 初始化报表表() -> None:
    """幂等创建 reports 表。

    Fix E1：进程级一次性——首次调用（或上次失败后重试）完整执行 DDL，
    之后按 DB 路径直接 return（报表读/写前不再每次跑 DDL 检查）。
    """
    if _后端() == "mysql":
        return  # 阶段 54-8：表结构由 mysql_repo.初始化数据库 统一管理（sqlite DDL 在 MySQL 下语义校验即报错）
    key = _当前db键()
    if _报表表已初始化.get(key):
        return
    with _报表表初始化锁:
        if _报表表已初始化.get(key):
            return
        # 失败回退：异常向上抛且不置标志，下次调用重试
        _初始化报表表全量()
        _报表表已初始化[key] = True


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
    try:
        报表_json = json.loads(row["report_json"])
    except (ValueError, TypeError):
        # M11：report_json 损坏（旧版本/异常写入）→ 返回空报表结构而非 500
        logger.warning("报表 %s 的 report_json 损坏，按空报表返回", row["report_id"])
        报表_json = {}
    return {
        "报表ID": row["report_id"],
        "数据集ID": row["dataset_id"],
        "标题": row["title"],
        "图表类型": row["chart_type"],
        "报表": 报表_json,
        "创建时间": row["created_at"],
    }


def 列出报表(user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """列出某用户最近的报表（按创建时间倒序，支持分页）。"""
    初始化报表表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT report_id, dataset_id, title, chart_type, created_at "
            "FROM reports WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
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


def 批量读取报表(user_id: str, report_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """优化⑨：一次查询读取多份报表（按 report_id 索引）；消除看板校验的 N+1。"""
    初始化报表表()
    if not report_ids:
        return {}
    placeholders = ",".join("?" * len(report_ids))
    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT report_id, dataset_id, title, chart_type, report_json, created_at "
            f"FROM reports WHERE user_id = ? AND report_id IN ({placeholders})",
            [user_id, *report_ids],
        ).fetchall()
    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        try:
            报表_json = json.loads(row["report_json"])
        except (ValueError, TypeError):
            报表_json = {}
        result[row["report_id"]] = {
            "报表ID": row["report_id"],
            "数据集ID": row["dataset_id"],
            "标题": row["title"],
            "图表类型": row["chart_type"],
            "报表": 报表_json,
            "创建时间": row["created_at"],
        }
    return result


def 搜索报表标题(user_id: str, q: str, limit: int = 5) -> List[Dict[str, Any]]:
    """优化⑧：按标题模糊搜索报表（供全局搜索）。"""
    初始化报表表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT report_id, dataset_id, title, chart_type, created_at "
            "FROM reports WHERE user_id = ? AND title LIKE ? ORDER BY created_at DESC LIMIT ?",
            (user_id, f"%{q}%", limit),
        ).fetchall()
    return [
        {"报表ID": row["report_id"], "数据集ID": row["dataset_id"], "标题": row["title"],
         "图表类型": row["chart_type"], "创建时间": row["created_at"]}
        for row in rows
    ]


def 删除报表(user_id: str, report_id: str) -> bool:
    """删除一份报表（仅限归属用户）。"""
    初始化报表表()
    with _write_lock, _get_conn() as conn:
        # M8 修复：级联清理收藏/分享，防悬空引用（表可能尚未初始化，先查存在性；方言收敛：sqlite_master/information_schema）
        tables = {r["name"] for r in conn.execute(_表存在SQL(_后端())).fetchall()}
        if "favorites" in tables:
            conn.execute("DELETE FROM favorites WHERE report_id = ? AND user_id = ?", (report_id, user_id))
        if "share_links" in tables:
            conn.execute("DELETE FROM share_links WHERE report_id = ? AND user_id = ?", (report_id, user_id))
        cur = conn.execute(
            "DELETE FROM reports WHERE report_id = ? AND user_id = ?",
            (report_id, user_id),
        )
        deleted = cur.rowcount > 0
    if deleted:
        logger.info("删除报表 %s（用户 %s）", report_id, user_id)
    return deleted
