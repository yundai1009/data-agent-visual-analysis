"""服务端 LLM 配额限流（阶段 51）。

设计
====
- 只有"服务端共享 Key"（.env 全局 LLM_API_KEY / provider 级 env key）的请求
  计入共享配额；BYOK（请求头 / 账号绑定 / 自定义供应商自带 key）不消耗服务端额度，
  豁免判定在 api/routes/reports.py 的 _准备上下文 完成。
- 统计口径复用 llm_usage 表：当日（UTC）请求次数 + 总 token，
  与"成本可见性"同一张表，无需额外存储。
- 配置：EnvConfig.LLM_DAILY_TOKEN_QUOTA / LLM_DAILY_REQUEST_QUOTA，0 = 不限；
  默认 1000000 token / 200 次（一天一人，宽松安全网）。
"""

from __future__ import annotations

from typing import Dict

from config.settings import EnvConfig
from repositories import usage_repo


class QuotaExceeded(Exception):
    """当日配额已用尽（携带用户可读消息，路由层转 429）。"""


def _解析配额(raw) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def 检查LLM配额(user_id: str) -> Dict[str, int]:
    """校验当日用量。未超限返回当前用量；超限抛 QuotaExceeded。"""
    token_quota = _解析配额(EnvConfig.LLM_DAILY_TOKEN_QUOTA)
    request_quota = _解析配额(EnvConfig.LLM_DAILY_REQUEST_QUOTA)
    用量 = usage_repo.用户今日用量(user_id)
    used_tokens = 用量["总token"]
    used_requests = 用量["记录数"]
    if token_quota > 0 and used_tokens >= token_quota:
        raise QuotaExceeded(
            f"已达今日 LLM 用量上限（{used_tokens} / {token_quota} token），"
            "请明天再试，或使用自己的 API Key（BYOK）"
        )
    if request_quota > 0 and used_requests >= request_quota:
        raise QuotaExceeded(
            f"已达今日分析次数上限（{used_requests} / {request_quota} 次），"
            "请明天再试，或使用自己的 API Key（BYOK）"
        )
    return 用量