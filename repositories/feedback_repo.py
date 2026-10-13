# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】feedback 表的唯一出入口：分析结果的评分与人工纠错落库（B8 修复前是假实现、直接丢弃）。
# ============================================================
# 【做了什么】
#   1. 建 feedback 表（自增 id 主键）：user_id / task_id / score / correction / sync_kb / created_at。
#   2. 保存反馈()：correction 入库前截断 1000 字，sync_kb 布尔转 0/1，返回自增 lastrowid。
#   3. 按任务查询(task_id, user_id, limit)：按 id 倒序取某任务某用户的全部反馈（新到旧）。
# 【为什么这么做】
#   - sync_kb 单独存一列而不是塞进 correction：反馈既是纠错样本又是知识库来源，路由要按它决定是否触发同步；按任务查询强制带 user_id（S5 修复），task_id 由前端传入、不能当鉴权依据。
# 【关键约定与坑】
#   - 本文件只有「写」与「按用户+任务读」两条路径，加统计接口时别顺手去掉 user_id 条件。
#   - correction 的 1000 字截断在仓储层统一做：超长输入不报错但静默截断，排障先看库里实际长度；连接走 存储/连接._get_conn，写操作加 backend.写锁。
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from 后端_核心.存储.backend import 写锁 as _write_lock
from 后端_核心.存储.backend import 当前后端 as _后端
from 后端_核心.存储.连接 import _get_conn   # 阶段 54-8：统一连接入口（按 DB_BACKEND 分发）

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化反馈表() -> None:
    """幂等创建 feedback 表。"""
    if _后端() == "mysql":
        return  # 阶段 54-8：表结构由 mysql_repo.初始化数据库 统一管理（sqlite DDL 在 MySQL 下语义校验即报错）
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


def 按任务查询(task_id: str, user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """查询某任务的全部反馈（新→旧）。S5：按归属用户过滤，杜绝越权读取他人反馈。"""
    初始化反馈表()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, user_id, task_id, score, correction, sync_kb, created_at "
            "FROM feedback WHERE task_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
            (task_id, user_id, limit),
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