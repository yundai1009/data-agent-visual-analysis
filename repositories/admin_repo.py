"""管理后台仓储：用户用量统计（管理员专用）。

所有查询只读。用户列表返回时剥离敏感字段（password_hash / llm_api_key /
llm_custom_providers），由路由层再次过滤保证。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from 后端_核心.存储.sqlite_repo import _get_conn

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _确保表存在() -> None:
    """幂等确保统计涉及的表已创建（各仓储的初始化）。"""
    from 后端_核心.存储.sqlite_repo import 初始化数据库  # noqa: E402
    from repositories.dashboard_repo import 初始化看板表
    from repositories.report_repo import 初始化报表表
    初始化数据库()
    初始化看板表()
    初始化报表表()


def 总览统计() -> Dict[str, Any]:
    """平台总览：各类资源总数。"""
    _确保表存在()
    with _get_conn() as conn:
        def _count(table: str) -> int:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            return int(row["n"])

        return {
            "用户数": _count("users"),
            "数据集数": _count("datasets"),
            "报表数": _count("reports"),
            "看板数": _count("dashboards"),
        }


def 用户用量列表() -> List[Dict[str, Any]]:
    """每个用户：注册信息 + 数据集数 / 报表数 / 最近报表时间。"""
    _确保表存在()
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT u.user_id, u.username, u.email, u.role, u.created_at,
                   (SELECT COUNT(*) FROM datasets d WHERE d.user_id = u.user_id) AS dataset_count,
                   (SELECT COUNT(*) FROM reports r  WHERE r.user_id = u.user_id) AS report_count,
                   (SELECT MAX(r.created_at) FROM reports r WHERE r.user_id = u.user_id) AS last_report_at
            FROM users u
            ORDER BY u.created_at ASC
            """
        ).fetchall()
    return [
        {
            "用户ID": row["user_id"],
            "用户名": row["username"],
            "邮箱": row["email"] or "",
            "角色": row["role"],
            "注册时间": row["created_at"],
            "数据集数": int(row["dataset_count"]),
            "报表数": int(row["report_count"]),
            "最近报表时间": row["last_report_at"] or "",
        }
        for row in rows
    ]


def 报表趋势(days: int = 7) -> List[Dict[str, Any]]:
    """最近 N 天每日报表生成数（缺的天补 0，按天升序）。"""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    cutoff = datetime(start.year, start.month, start.day, tzinfo=timezone.utc).isoformat()

    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n
            FROM reports
            WHERE created_at >= ?
            GROUP BY day
            """,
            (cutoff,),
        ).fetchall()
    by_day = {row["day"]: int(row["n"]) for row in rows}

    result = []
    for i in range(days):
        d = start + timedelta(days=i)
        key = d.isoformat()
        result.append({"日期": key, "数量": by_day.get(key, 0)})
    return result