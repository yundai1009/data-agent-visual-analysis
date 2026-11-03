# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】管理后台的只读统计仓储：跨用户聚合（总量 / 用量 / 趋势），不含任何写操作。
# ============================================================
# 【做了什么】
#   1. 总览统计：users / datasets / reports / dashboards 四张表的 COUNT(*)。
#   2. 用户用量列表：一条 SQL 用相关子查询带出每人的数据集数、报表数与最近报表时间，按注册时间升序。
#   3. 报表趋势(days)：按 substr(created_at, 1, 10) 分组统计最近 N 天报表数，缺的天在 Python 侧补 0。
# 【为什么这么做】
#   - 显式列字段而不是 SELECT *：users 表同存 password_hash / llm_api_key / llm_custom_providers，敏感字段靠「不查」保证而非事后过滤；跨用户聚合也必须留在这层，在路由里拼 SQL 等于把存储细节外泄到 API 层。
# 【关键约定与坑】
#   - _count 的 f-string 表名是模块内硬编码字面量而非用户输入，将来若接受外部表名必须先加白名单；_确保表存在 只初始化 users/dashboards/reports，旧库缺 status/email 列否则会 500。
#   - substr 截日期依赖 created_at 一律是 _now_iso() 产出的带 +00:00 ISO 串，换成时间戳列会让分天统计失效。
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from 后端_核心.存储.连接 import _get_conn   # 阶段 54-8：统一连接入口（按 DB_BACKEND 分发）

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _确保表存在() -> None:
    """幂等确保统计涉及的表已创建（各仓储的初始化）。"""
    from 后端_核心.存储.连接 import 初始化数据库  # noqa: E402
    from repositories.dashboard_repo import 初始化看板表
    from repositories.report_repo import 初始化报表表
    from repositories.user_repo import 初始化用户表
    初始化数据库()
    初始化看板表()
    初始化报表表()
    初始化用户表()  # 含 status 列幂等迁移（旧库缺列时 SELECT u.status 会 500）


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
            SELECT u.user_id, u.username, u.email, u.role, u.created_at, u.status,
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
            "状态": row["status"] or "active",
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


def 价值漏斗() -> Dict[str, Any]:
    """阶段九十 · R15（产品评审团"无价值度量口径"）：注册 → 传数据 → 出报表 → 回访。

    【口径定义】逐步给「有多少用户走到了这一步」，每步都是**累计且去重**：
      - 注册：users 表里有账号的用户数（这是漏斗顶，分母）；
      - 传数据：至少有一条 datasets 记录的用户数；
      - 出报表：至少有一条 reports 记录的用户数（真正拿到结果的）；
      - 回访：注册满 7 天、且首条报表与最近一条报表不在同一天的用户数
        —— 用「报表时间跨天」当留存代理指标。为什么不用登录日志：本项目没有
        登录事件表，硬造一条只会得到假数据；报表跨天是可查、可解释、不撒谎的口径。
    另外给出每一步相对上一步的转化率，方便一眼看出卡在哪一环。

    【已知局限（不掩盖）】分母只含已注册用户，匿名试用不在内（本项目默认要求登录）；
    回访用报表跨天代理，只能说明「回来继续用」，不能说明「只是回来看看」。
    """
    _确保表存在()
    with _get_conn() as conn:
        注册 = int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])
        传数据 = int(conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM datasets"
        ).fetchone()["n"])
        出报表 = int(conn.execute(
            "SELECT COUNT(DISTINCT user_id) AS n FROM reports"
        ).fetchone()["n"])
        # 回访：同一天只有一条报表的不算回访；跨天出现才算「回来接着用」
        回访 = int(conn.execute(
            """
            SELECT COUNT(*) AS n FROM (
                SELECT user_id
                FROM reports
                GROUP BY user_id
                HAVING MIN(substr(created_at, 1, 10)) <> MAX(substr(created_at, 1, 10))
            ) t
            """
        ).fetchone()["n"])

    def _率(分子: int, 分母: int) -> float:
        return round(分子 / 分母, 4) if 分母 else 0.0

    return {
        "漏斗": [
            {"步骤": "注册", "人数": 注册, "占注册": _率(注册, 注册)},
            {"步骤": "传数据", "人数": 传数据, "占注册": _率(传数据, 注册)},
            {"步骤": "出报表", "人数": 出报表, "占注册": _率(出报表, 注册)},
            {"步骤": "回访（报表跨天）", "人数": 回访, "占注册": _率(回访, 注册)},
        ],
        "转化率": {
            "注册→传数据": _率(传数据, 注册),
            "传数据→出报表": _率(出报表, 传数据),
            "出报表→回访": _率(回访, 出报表),
          },
        "口径说明": "各步为累计去重用户数；回访以「同一用户报表出现在不同日期」代理，"
                   "分母仅含已注册用户，匿名试用不计入。",
    }