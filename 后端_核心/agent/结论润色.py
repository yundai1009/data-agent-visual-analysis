"""LLM 结论文本润色 + 模板兜底。

输入：分析需求 + 数据画像 + 聚合后的 report_df + 推荐说明 + 风险提示
输出：Markdown 中文分析结论

设计纪律
--------
- LLM 只看到：列名 + top3 行 + 推荐理由 + 风险提示，**不看完整数据集**
- LLM 只输出 ``{"结论": "..."}`` 形态 JSON 或直接 Markdown 文本，不 exec 不 eval
- 任何失败（无 key / 超时 / JSON 不合法）→ 回退到现有 ``_生成结论`` 模板拼接
- 输出限长 800 字，避免长篇大论但不切题
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import pandas as pd

from 后端_核心.agent.llm客户端 import chat_completion, is_llm_configured, parse_llm_json
from config.settings import LLMRequestConfig

logger = logging.getLogger(__name__)

# 输出结论软上限
_MAX_结论_LEN = 800

_SYSTEM_PROMPT = """你是数据分析 Agent，任务是根据给定的画像、聚合结果、推荐依据，写一段中文 Markdown 分析结论。

【硬性规则】
1. 仅基于提供的事实，不要编造数字；
2. 结构为：先一句话总结，再 2-4 点「关键发现」（用 `-` 列表），再 1-2 点「需关注」（如果有风险提示）；
3. 不要使用代码块，不要输出解释性开场白；
4. 控制在 200-400 字之间；
5. 必须调用 ``生成结论`` 工具，把结论作为参数传入；不要直接输出文本。"""

_TOOL_SCHEMA = [{
    "type": "function",
    "function": {
        "name": "生成结论",
        "description": "把生成的分析结论作为工具参数返回",
        "parameters": {
            "type": "object",
            "properties": {
                "结论": {"type": "string", "description": "Markdown 中文分析结论"},
            },
            "required": ["结论"],
        },
    },
}]


def _build_report_summary(report_df: pd.DataFrame) -> str:
    """把聚合结果压缩成 LLM prompt 用的摘要：列名 + top3 行。"""
    if report_df is None or report_df.empty:
        return "（聚合结果为空）"
    columns = list(report_df.columns)
    top3 = report_df.head(3)
    # 用 dict-records 而非 to_markdown，避免 pandas额外依赖
    rows_text = []
    for _, row in top3.iterrows():
        items = [f"{col}: {_safe_value(row[col])}" for col in columns]
        rows_text.append("  - " + ", ".join(items))
    return f"列名: {columns}\n前3行:\n" + "\n".join(rows_text)


def _safe_value(value: Any) -> str:
    if value is None:
        return "无"
    try:
        if pd.isna(value):
            return "无"
    except (TypeError, ValueError):
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def 润色结论(
    分析需求: str,
    画像: Dict[str, Any],
    report_df: pd.DataFrame,
    推荐说明: Dict[str, Any],
    风险提示: List[str],
    llm_config: Optional["LLMRequestConfig"] = None,
) -> Optional[str]:
    """LLM 润色结论；失败返回 None，调用方回退到模板拼接。"""
    if not is_llm_configured():
        return None

    推荐 = 推荐说明 or {}
    report_summary = _build_report_summary(report_df)
    recommend_lines = "\n".join(f"- {r}" for r in 推荐.get("理由", [])) or "- （无）"
    risk_lines = "\n".join(f"- {r}" for r in 风险提示) or "- 无"

    user_content = (
        f"分析需求: {分析需求.strip() or '（未填写）'}\n"
        f"数据画像: 行数 {画像.get('行数', 0)}，列数 {画像.get('列数', 0)}，"
        f"数据质量等级 {(画像.get('数据质量') or {}).get('等级', '未知')}\n"
        f"推荐的图表类型: {推荐.get('图表类型', '未知')}\n"
        f"推荐依据:\n{recommend_lines}\n"
        f"聚合结果预览:\n{report_summary}\n"
        f"风险提示:\n{risk_lines}\n"
    )

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]

    response = chat_completion(messages=messages, tools=_TOOL_SCHEMA, tool_choice="auto", llm_config=llm_config)
    if response is None:
        logger.warning("结论润色 LLM 调用失败/未配置，回退模板")
        return None

    # 优先从 tool_calls 提取
    try:
        message = (response.get("choices") or [{}])[0].get("message") or {}
    except (IndexError, AttributeError):
        message = {}
    tool_calls = message.get("tool_calls") or []
    if tool_calls and isinstance(tool_calls, list):
        call = tool_calls[0] or {}
        args = (call.get("function") or {}).get("arguments")
        if isinstance(args, dict):
            text = args.get("结论") or ""
        elif isinstance(args, str):
            parsed = parse_llm_json(args)
            text = (parsed or {}).get("结论", "") if parsed else ""
        else:
            text = ""
        if text and isinstance(text, str):
            return text[:_MAX_结论_LEN]

    # 兜底：尝试从 content 直接提取 JSON
    content = message.get("content") or ""
    if isinstance(content, str) and content.strip():
        parsed = parse_llm_json(content)
        if parsed and "结论" in parsed:
            text = parsed["结论"]
            if isinstance(text, str):
                return text[:_MAX_结论_LEN]

    logger.warning("结论润色 LLM 输出无可解析结构，回退模板")
    return None
