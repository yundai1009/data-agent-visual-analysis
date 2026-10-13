# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】audit_log 表的唯一出入口：关键安全操作的只追加台账（who / what / when）。
# ============================================================
# 【做了什么】
#   1. 建 audit_log 表（自增 id 主键）+ idx_audit_created(created_at) 索引。
#   2. 记录()：username / action / target_type / target_id / detail 分别截断到 50 / 50 / 30 / 64 / 300 字符。
#   3. 查询()：按 id 倒序分页，可选按 user_id 过滤，返回中文键给管理员页面。
# 【为什么这么做】
#   - 只追加、刻意不给 UPDATE / DELETE 接口：记录不可被业务代码改写才有价值，留了删改能力等于留篡改入口；记录() 整段吞异常只打 warning，因为审计是旁路，写不进台账不能让登录、删除等主流程失败。
# 【关键约定与坑】
#   - 查询() 的 user_id 是管理员的筛选而非隔离边界，本层不做越权防护，调用方审计接口须自行校验管理员身份；username 冗余存一份，因为注销时审计行会随 user 一起被删。
#   - 字段截断放在仓储层而不是十几个调用点；连接走 存储/连接._get_conn，写操作加 backend.写锁，SQL 全 ? 参数化。
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from 后端_核心.存储.backend import 写锁 as _write_lock
from 后端_核心.存储.backend import 创建索引SQL as _建索引SQL, 当前后端 as _后端
from 后端_核心.存储.连接 import _get_conn   # 阶段 54-8：统一连接入口（按 DB_BACKEND 分发）

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化审计表() -> None:
    """幂等创建 audit_log 表。"""
    if _后端() == "mysql":
        return  # 阶段 54-8：表结构由 mysql_repo.初始化数据库 统一管理（sqlite DDL 在 MySQL 下语义校验即报错）
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                username    TEXT NOT NULL DEFAULT '',
                action      TEXT NOT NULL,
                target_type TEXT NOT NULL DEFAULT '',
                target_id   TEXT NOT NULL DEFAULT '',
                detail      TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL
            )
            """
        )
        _sql = _建索引SQL(_后端(), "idx_audit_created", "audit_log", "(created_at)")
        if _sql:
            conn.execute(_sql)


def 记录(
    user_id: str,
    action: str,
    username: str = "",
    target_type: str = "",
    target_id: str = "",
    detail: str = "",
) -> None:
    """追加一条审计记录（失败不阻塞业务）。"""
    try:
        初始化审计表()
        with _write_lock, _get_conn() as conn:
            conn.execute(
                """
                INSERT INTO audit_log (user_id, username, action, target_type, target_id, detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, username[:50], action[:50], target_type[:30], target_id[:64],
                 str(detail)[:300], _now_iso()),
            )
    except Exception as exc:
        logger.warning("审计记录失败（不影响业务）: %s", exc)


def 查询(limit: int = 50, offset: int = 0, user_id: str = "") -> List[Dict[str, Any]]:
    """查询审计日志（管理员用，默认最近 50 条；可按 user_id 过滤）。"""
    初始化审计表()
    sql = "SELECT id, user_id, username, action, target_type, target_id, detail, created_at FROM audit_log"
    params: list = []
    if user_id:
        sql += " WHERE user_id = ?"
        params.append(user_id)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params += [limit, offset]
    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "id": row["id"],
            "用户ID": row["user_id"],
            "用户名": row["username"],
            "操作": row["action"],
            "对象类型": row["target_type"],
            "对象ID": row["target_id"],
            "详情": row["detail"],
            "时间": row["created_at"],
        }
        for row in rows
    ]