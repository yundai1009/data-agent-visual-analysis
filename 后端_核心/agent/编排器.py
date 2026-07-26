"""Agent 编排器：多轮 ReAct 编排 + 真实 Trace。

阶段 2 核心逻辑
==============
1. 第 1 轮 LLM → 意图识别（调用「解析为报表意图」tool）
2. 如果 LLM 失败或未配置 → 降级回 `_意图驱动配置` 关键词匹配
3. 上游 `上传报表生成器.py` 仍然接管聚合、画图、结论生成
4. 所有调用都记录在 `TraceRecorder` 中，返回真实 `Agent_Trace`
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from 后端_核心.agent.llm客户端 import (
    chat_completion,
    extract_tool_call,
    is_llm_configured,
)
from 后端_核心.agent.工具集 import (
    TOOL_SCHEMAS_FULL,
    validate_intent_against_profile,
)
from 后端_核心.agent.trace import TraceRecorder, 计时, 提取token

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """你是数据分析 Agent。你必须调用 `解析为报表意图` 工具，不要输出解释性文本。"""


# ═══════════════════════════════════════════════
# 阶段 1 兼容出口：保留旧名字 `解析自然语言需求`
# ═══════════════════════════════════════════════

def 解析自然语言需求(
    分析需求: str,
    画像: Dict[str, Any],
    *,
    enable_llm: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """阶段 1 接口：返回标准化意图 dict，失败返回 None。
    阶段 2 改为内部调 `编排Agent` 并从中提取意图。
    """
    agent_result = 编排Agent(画像, 分析需求, enable_llm=enable_llm)
    if agent_result is None:
        return None
    return {
        "图表类型": agent_result["图表类型"],
        "x轴": agent_result["x轴"],
        "y轴": agent_result["y轴"],
        "分组字段": agent_result["分组字段"],
        "聚合方式": agent_result["聚合方式"],
        "推荐理由": agent_result.get("推荐理由", ""),
    }


# ═══════════════════════════════════════════════
# 阶段 2 多轮编排
# ═══════════════════════════════════════════════

def 编排Agent(
    画像: Dict[str, Any],
    分析需求: str,
    enable_llm: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """返回标准化意图 +真实 Trace，供 `生成报表数据` 消费。失败返回 None。"""
    trace = TraceRecorder()
    if enable_llm is False:
        enable_llm = False
    else:
        enable_llm = is_llm_configured()

    intent_override = None
    intent_source = "无"

    # ---------- 第 1 轮：LLM 意图识别 ----------
    if enable_llm and (分析需求 or "").strip():
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": 分析需求},
        ]
        with 计时() as timer:
            resp = chat_completion(
                messages=messages,
                tools=TOOL_SCHEMAS_FULL[:1],  # 仅意图识别
                tool_choice="auto",
            )
        token_usage = 提取token(resp)
        tc = extract_tool_call(resp)
        if tc and tc["name"] == "解析为报表意图":
            validated = validate_intent_against_profile(tc.get("arguments", {}), 画像)
            if validated:
                intent_override = validated
                intent_source = "LLM"
                trace.记录LLM调用(
                    轮次=1, prompt_summary=分析需求[:200],
                    耗时_ms=timer.elapsed_ms, token=token_usage, 状态="成功",
                    理由=f"图表={validated.get('图表类型', '?')},聚合方式={validated.get('聚合方式', '?')}",
                )
            else:
                logger.warning("意图校验失败，降级")
                trace.记录LLM调用(轮次=1, prompt_summary=分析需求[:200],
                                  耗时_ms=timer.elapsed_ms, token=token_usage,
                                  状态="失败", 理由="字段白名单校验失败")
        else:
            trace.记录LLM调用(轮次=1, prompt_summary=分析需求[:200],
                              耗时_ms=timer.elapsed_ms, token=token_usage,
                              状态="失败", 理由="未返回合法工具调用")

    # ---------- 降级：关键词匹配 ----------
    if intent_override is None:
        from 后端_核心.上传报表生成器 import _意图驱动配置  # noqa: E402 延迟引入防循环
        rule_over = _意图驱动配置(画像, 分析需求)
        if rule_over:
            intent_override = rule_over
            intent_source = "规则"
            trace.记录观察(轮次=1, 说明="LLM 不可用，降级为关键词匹配", 状态="成功")
        else:
            # 默认：表格
            intent_override = {"图表类型": "自动推荐", "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和"}
            intent_source = "规则"
            trace.记录观察(轮次=1, 说明="未命中任何规则，自动推荐图表", 状态="成功")

    # ---------- 返回标准化意图 ----------
    return {
        "图表类型": intent_override.get("图表类型", "自动推荐"),
        "x轴": intent_override.get("x轴"),
        "y轴": intent_override.get("y轴", []),
        "分组字段": intent_override.get("分组字段"),
        "聚合方式": intent_override.get("聚合方式", "求和"),
        "意图来源": intent_source,
        "推荐理由": intent_override.get("推荐理由", ""),
        "Agent_Trace": trace.to_list(),
    }