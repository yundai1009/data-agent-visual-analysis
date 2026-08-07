"""LLM 用量统计仓储（P1 加固：成本可见性）。

每次报表生成成功后，从 Agent Trace 汇总 token 数写入 llm_usage 表；
管理员可查看近 N 天用量（总量 + 按天 + 按 provider）。不存 Prompt/响应内容，仅计费数字。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def 初始化用量表() -> None:
    """幂等创建 llm_usage 表。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_usage (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id           TEXT NOT NULL,
                provider          TEXT NOT NULL DEFAULT '',
                model             TEXT NOT NULL DEFAULT '',
                prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens      INTEGER NOT NULL DEFAULT 0,
                created_at        TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_llm_usage_created
            ON llm_usage (created_at)
            """
        )


def 记录用量(
    user_id: str,
    provider: str = "",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """记录一次分析（已按 trace 汇总）的 token 用量。"""
    if not user_id or (not prompt_tokens and not completion_tokens):
        return
    初始化用量表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            """
            INSERT INTO llm_usage (user_id, provider, model, prompt_tokens, completion_tokens, total_tokens, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, provider, model, prompt_tokens, completion_tokens,
             prompt_tokens + completion_tokens, _now_iso()),
        )


def 统计用量(days: int = 7) -> Dict[str, Any]:
    """管理员视角：近 N 天总量 + 按天 + 按 provider 分组。"""
    初始化用量表()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(prompt_tokens),0) AS p, "
            "COALESCE(SUM(completion_tokens),0) AS c, COALESCE(SUM(total_tokens),0) AS t "
            "FROM llm_usage WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
        by_day = conn.execute(
            "SELECT substr(created_at,1,10) AS day, COUNT(*) AS n, COALESCE(SUM(total_tokens),0) AS t "
            "FROM llm_usage WHERE created_at >= ? GROUP BY day ORDER BY day",
            (cutoff,),
        ).fetchall()
        by_provider = conn.execute(
            "SELECT provider, COUNT(*) AS n, COALESCE(SUM(total_tokens),0) AS t "
            "FROM llm_usage WHERE created_at >= ? GROUP BY provider ORDER BY t DESC",
            (cutoff,),
        ).fetchall()
    return {
        "天数": days,
        "记录数": int(total["n"]),
        "prompt_tokens": int(total["p"]),
        "completion_tokens": int(total["c"]),
        "total_tokens": int(total["t"]),
        "按天": [{"日期": r["day"], "记录数": int(r["n"]), "tokens": int(r["t"])} for r in by_day],
        "按provider": [{"provider": r["provider"] or "未知", "记录数": int(r["n"]), "tokens": int(r["t"])} for r in by_provider],
    }