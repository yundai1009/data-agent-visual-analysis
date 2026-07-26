"""Agent 编排器：多轮 ReAct 编排 + 真实 Trace。

阶段 3 核心逻辑
==============
1. 第 1 轮：LLM 调用「获取数据画像」→ 感知数据
2. 第 2 轮：LLM 调用「聚合分析」→ 按需计算
3. 第 3 轮：LLM 调用「推荐图表」+「生成结论」→ 出结果
4. 任何一轮失败 → 整体降级到关键词匹配兜底
5. 所有调用记录在 TraceRecorder 中
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
    execute_tool,
    validate_intent_against_profile,
)
from 后端_核心.agent.trace import TraceRecorder, 计时, 提取token
from 后端_核心.agent.执行器注册 import 注册所有执行器

logger = logging.getLogger(__name__)

# 启动时注册所有 Tool executor（幂等，多次调用无害）
注册所有执行器()

_SYSTEM_PROMPT = """你是数据分析 Agent。根据用户的分析需求和数据画像，逐步完成分析任务。

你有以下工具可用：
1. 获取数据画像 — 读取数据集的字段信息和统计摘要
2. 聚合分析 — 按指定字段和聚合方式计算数据
3. 推荐图表 — 推荐合适的图表类型
4. 生成结论 — 生成分析结论

请按顺序调用工具，每次调用一个。完成所有分析后输出最终结论。
"""


def 解析自然语言需求(
    分析需求: str,
    画像: Dict[str, Any],
    *,
    enable_llm: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """兼容接口：从编排结果中提取标准化意图。"""
    agent_result = 编排Agent(画像, 分析需求, df=None, enable_llm=enable_llm)
    if agent_result is None:
        return None
    return {
        "图表类型": agent_result.get("图表类型", "自动推荐"),
        "x轴": agent_result.get("x轴"),
        "y轴": agent_result.get("y轴", []),
        "分组字段": agent_result.get("分组字段"),
        "聚合方式": agent_result.get("聚合方式", "求和"),
        "推荐理由": agent_result.get("推荐理由", ""),
    }


def 编排Agent(
    画像: Dict[str, Any],
    分析需求: str,
    df: Any = None,
    enable_llm: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """多轮 ReAct 编排：感知 → 推理 → 行动 → 观察 → 再推理。

    Args:
        画像: 数据画像 dict
        分析需求: 用户自然语言需求
        df: 原始 DataFrame（用于聚合分析 tool 的实际执行）
        enable_llm: 是否启用 LLM

    Returns:
        标准化意图 dict（含 Agent_Trace），失败返回 None
    """
    trace = TraceRecorder()
    if enable_llm is False:
        enable_llm = False
    else:
        enable_llm = is_llm_configured()

    intent_override = None
    intent_source = "无"

    # ═══ LLM 多轮 ReAct ═══
    if enable_llm and (分析需求 or "").strip():
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": 分析需求},
        ]
        # 上下文：供 tool executor 使用的数据
        context = {"画像": 画像, "df": df}

        # 可用的 tool schema（排除「解析为报表意图」旧 tool）
        tools = [s for s in TOOL_SCHEMAS_FULL if s["function"]["name"] != "解析为报表意图"]

        # ── 第 1 轮：获取数据画像 ──
        round1_ok = _执行一轮(messages, tools, context, 轮次=1, trace=trace)
        if not round1_ok:
            logger.warning("第 1 轮（数据画像）失败，降级")
            trace.记录观察(轮次=1, 说明="数据画像获取失败，降级到关键词匹配", 状态="失败")
        else:
            # ── 第 2 轮：聚合分析 ──
            round2_ok = _执行一轮(messages, tools, context, 轮次=2, trace=trace)
            if not round2_ok:
                logger.warning("第 2 轮（聚合分析）失败，降级")
                trace.记录观察(轮次=2, 说明="聚合分析失败，降级到关键词匹配", 状态="失败")
            else:
                # ── 第 3 轮：推荐图表 + 生成结论 ──
                round3_ok = _执行一轮(messages, tools, context, 轮次=3, trace=trace)
                if not round3_ok:
                    logger.warning("第 3 轮（推荐图表）失败，降级")
                    trace.记录观察(轮次=3, 说明="图表推荐失败，降级到关键词匹配", 状态="失败")

    # ═══ 降级：关键词匹配 ═══
    if intent_override is None:
        from 后端_核心.上传报表生成器 import _意图驱动配置  # noqa: E402
        rule_over = _意图驱动配置(画像, 分析需求)
        if rule_over:
            intent_override = rule_over
            intent_source = "规则"
            trace.记录观察(轮次=1, 说明="LLM 不可用，降级为关键词匹配", 状态="成功")
        else:
            intent_override = {"图表类型": "自动推荐", "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和"}
            intent_source = "规则"
            trace.记录观察(轮次=1, 说明="未命中任何规则，自动推荐图表", 状态="成功")

    # ═══ 返回 ═══
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


def _执行一轮(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    context: Dict[str, Any],
    轮次: int,
    trace: TraceRecorder,
) -> bool:
    """执行一轮 LLM 推理 + 工具调用。

    1. 调 LLM → 拿到 tool_call
    2. 执行工具 → 得到结果
    3. 将 tool_call + 结果追加到 messages
    4. 返回 True/False
    """
    with 计时() as timer:
        resp = chat_completion(messages=messages, tools=tools, tool_choice="auto")
    token_usage = 提取token(resp)
    tc = extract_tool_call(resp)

    if not tc or not tc.get("name"):
        trace.记录LLM调用(轮次=轮次, prompt_summary=messages[-1].get("content", "")[:200],
                          耗时_ms=timer.elapsed_ms, token=token_usage,
                          状态="失败", 理由="未返回合法工具调用")
        return False

    tool_name = tc["name"]
    tool_args = tc.get("arguments", {})

    # 追加 assistant 的 tool_call 消息
    messages.append({
        "role": "assistant",
        "content": None,
        "tool_calls": [{
            "id": f"call_{轮次}",
            "type": "function",
            "function": {"name": tool_name, "arguments": str(tool_args)},
        }],
    })

    # 执行工具
    result = execute_tool(tool_name, tool_args, context)
    if result is None:
        trace.记录LLM调用(轮次=轮次, prompt_summary=f"工具={tool_name}",
                          耗时_ms=timer.elapsed_ms, token=token_usage,
                          状态="失败", 理由=f"工具 {tool_name} 执行失败")
        # 追加失败消息
        messages.append({
            "role": "tool",
            "tool_call_id": f"call_{轮次}",
            "content": f"工具 {tool_name} 执行失败，请重试或使用其他工具",
        })
        return False

    # 把工具结果转成文本塞回 messages
    result_text = _结果转文本(result)
    messages.append({
        "role": "tool",
        "tool_call_id": f"call_{轮次}",
        "content": result_text,
    })

    trace.记录LLM调用(轮次=轮次, prompt_summary=f"工具={tool_name}",
                      耗时_ms=timer.elapsed_ms, token=token_usage,
                      状态="成功", 理由=f"{tool_name} → {result_text[:80]}")
    trace.记录工具调用(轮次=轮次, 工具名=tool_name, 入参=tool_args,
                      输出摘要=result_text[:200], 耗时_ms=timer.elapsed_ms,
                      状态="成功")
    return True


def _结果转文本(result: Dict[str, Any]) -> str:
    """把工具执行结果 dict 转成文本，供 LLM 继续推理。"""
    parts = []
    if "摘要" in result:
        parts.append(result["摘要"])
    if "数据摘要" in result:
        parts.append(result["数据摘要"])
    if "推荐图表" in result:
        parts.append(f"推荐图表：{result['推荐图表']}")
        if result.get("理由"):
            parts.append(f"理由：{result['理由']}")
    if "结论" in result:
        parts.append(f"分析结论：{result['结论']}")
    if not parts:
        return str(result)[:500]
    return "\n".join(parts)
