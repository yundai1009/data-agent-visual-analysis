# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】favorites 表的唯一出入口：报表星标（user_id + report_id 复合主键），只为「常用报表快速找」服务。
# ============================================================
# 【做了什么】
#   1. 建 favorites 表，PRIMARY KEY (user_id, report_id) 由数据库兜底防重复收藏。
#   2. 切换收藏：同一把写锁内先 SELECT 判存在，存在则 DELETE、不存在则 INSERT，并返回切换后是否已收藏。
#   3. 是否已收藏（单条判定）与 已收藏集合（一次取回某用户全部 report_id，供列表接口批量打星标）。
# 【为什么这么做】
#   - 不单开「取消收藏」接口而是做切换：前端星标只有一个动作，接口数减半，返回切换后状态让前端不必再查一次；用复合主键而不是自增 id + 唯一索引，是因为表只有两列业务字段，去重与整行删除由主键天然完成。
# 【关键约定与坑】
#   - 本文件没有任何删除函数：清理由 report_repo.删除报表（级联）与 user_repo.删除用户及数据（注销级联）负责，动这张表前先看那两处。
#   - 切换收藏是「先查后写」而非单条 UPSERT，顺序靠 backend.写锁 串行化；连接走 存储/连接._get_conn，SQL 全 ? 参数化。
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timezone

from 后端_核心.存储.backend import 写锁 as _write_lock
from 后端_核心.存储.backend import 当前后端 as _后端
from 后端_核心.存储.连接 import _get_conn   # 阶段 54-8：统一连接入口（按 DB_BACKEND 分发）

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化收藏表() -> None:
    """幂等创建 favorites 表（唯一约束防重复收藏）。"""
    if _后端() == "mysql":
        return  # 阶段 54-8：表结构由 mysql_repo.初始化数据库 统一管理（sqlite DDL 在 MySQL 下语义校验即报错）
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