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

import json
import logging
from typing import Any, Dict, List, Optional

from 后端_核心.agent.llm客户端 import (
    chat_completion,
    extract_tool_call,
    is_llm_configured,
    最近LLM失败,
)
from config.settings import LLMRequestConfig
from 后端_核心.agent.工具集 import (
    TOOL_SCHEMAS_FULL,
    execute_tool,
    validate_intent_against_profile,
)
from 后端_核心.agent.trace import TraceRecorder, 计时, 提取token
from 后端_核心.agent.执行器注册 import 注册所有执行器
from 后端_核心.agent.记忆 import 检索相似记忆, 保存记忆, 生成_few_shot_prompt, 记忆条数

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
    llm_config: Optional[LLMRequestConfig] = None,
) -> Optional[Dict[str, Any]]:
    """兼容接口：从编排结果中提取标准化意图。"""
    agent_result = 编排Agent(画像, 分析需求, df=None, enable_llm=enable_llm, llm_config=llm_config)
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
    llm_config: Optional[LLMRequestConfig] = None,
    on_event: Optional[Any] = None,
    user_id: str = "",
) -> Optional[Dict[str, Any]]:
    """多轮 ReAct 编排：感知 → 推理 → 行动 → 观察 → 再推理。

    Args:
        画像: 数据画像 dict
        分析需求: 用户自然语言需求
        df: 原始 DataFrame（用于聚合分析 tool 的实际执行）
        enable_llm: 是否启用 LLM
        llm_config: 请求级 LLM 配置（provider/base_url/model），并发安全
        on_event: 可选回调，trace 每记录一步即实时推送（SSE 直播）

    Returns:
        标准化意图 dict（含 Agent_Trace），失败返回 None
    """
    trace = TraceRecorder(on_event=on_event)
    if enable_llm is False:
        enable_llm = False
    else:
        # BYOK：按本次请求的 llm_config.api_key 判断（用户自带 Key 有效即启用 LLM）
        enable_llm = is_llm_configured(llm_config.api_key if llm_config else None)

    intent_override = None
    intent_source = "无"

    # ═══ LLM 多轮 ReAct ═══
    if enable_llm and (分析需求 or "").strip():
        # ── 检索相似历史记忆（few-shot） ──
        相似记忆 = 检索相似记忆(user_id, 分析需求)
        memory_hint = 生成_few_shot_prompt(相似记忆)

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM_PROMPT + memory_hint},
            {"role": "user", "content": 分析需求},
        ]
        # 上下文：供 tool executor 使用的数据
        context = {"画像": 画像, "df": df}

        # 可用的 tool schema（排除「解析为报表意图」旧 tool）
        tools = [s for s in TOOL_SCHEMAS_FULL if s["function"]["name"] != "解析为报表意图"]

        # ── 第 1 轮：获取数据画像 ──
        round1_ok = _执行一轮(messages, tools, context, 轮次=1, trace=trace, llm_config=llm_config)
        if not round1_ok:
            logger.warning("第 1 轮（数据画像）失败，降级")
            trace.记录观察(轮次=1, 说明="数据画像获取失败，降级到关键词匹配", 状态="失败")
        else:
            # ── 第 2 轮：聚合分析 ──
            round2_ok = _执行一轮(messages, tools, context, 轮次=2, trace=trace, llm_config=llm_config)
            if not round2_ok:
                logger.warning("第 2 轮（聚合分析）失败，降级")
                trace.记录观察(轮次=2, 说明="聚合分析失败，降级到关键词匹配", 状态="失败")
            else:
                # ── 第 3 轮：推荐图表 + 生成结论 ──
                round3_ok = _执行一轮(messages, tools, context, 轮次=3, trace=trace, llm_config=llm_config)
                if round3_ok:
                    # 从多轮消息中提取最终意图
                    intent_override = _从消息提取意图(messages, 画像)
                    if intent_override:
                        # LLM 字段兜底：不满足图表语义时用规则选择器修正（如词云必须用文本字段）
                        from 后端_核心.上传报表生成器 import 自动选字段  # 延迟导入避免循环
                        chart_type = intent_override.get("图表类型")
                        if chart_type == "词云图":
                            文本字段 = 画像.get("文本字段") or []
                            if intent_override.get("x轴") not in 文本字段:
                                intent_override["x轴"] = 自动选字段(画像, "词云图").get("x轴")
                        intent_source = "LLM"
                        trace.记录观察(轮次=3, 说明="多轮 ReAct 完成", 状态="成功")
                        # 保存到长期记忆
                        try:
                            from 后端_核心.数据画像 import 生成数据画像
                            画像摘要 = f"{画像.get('行数',0)}行/{画像.get('列数',0)}列"
                            保存记忆(user_id, 分析需求, intent_override, 画像摘要)
                        except Exception as exc:
                            logger.warning("保存长期记忆失败: %s", exc)

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
        # LLM 失败原因：降级时透传给用户（避免静默回退规则让用户困惑）
        "LLM失败原因": 最近LLM失败().get("reason", ""),
    }


def _执行一轮(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    context: Dict[str, Any],
    轮次: int,
    trace: TraceRecorder,
    llm_config: Optional[LLMRequestConfig] = None,
) -> bool:
    """执行一轮 LLM 推理 + 工具调用。

    1. 调 LLM → 拿到 tool_call
    2. 执行工具 → 得到结果
    3. 将 tool_call + 结果追加到 messages
    4. 返回 True/False
    """
    with 计时() as timer:
        resp = chat_completion(messages=messages, tools=tools, tool_choice="auto", llm_config=llm_config)
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
            "function": {"name": tool_name, "arguments": json.dumps(tool_args, ensure_ascii=False)},
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


def _从消息提取意图(messages: List[Dict[str, Any]], 画像: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """从多轮 ReAct 的 messages 中提取结构化意图。"""
    chart_type = None
    x_axis = None
    y_axis_list: List[str] = []
    group_field = None
    agg_method = None
    reason = ""

    for msg in reversed(messages):
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content", "")

        if role == "tool" and isinstance(content, str):
            if "推荐图表：" in content:
                for line in content.split("\n"):
                    if line.startswith("推荐图表："):
                        chart_type = line.replace("推荐图表：", "").strip()
                    if line.startswith("理由："):
                        reason = line.replace("理由：", "").strip()

        if role == "assistant" and msg.get("tool_calls"):
            for tc in (msg.get("tool_calls") or []):
                func = tc.get("function", {})
                name = func.get("name", "")
                try:
                    args = json.loads(func.get("arguments", "{}")) if isinstance(func.get("arguments"), str) else func.get("arguments", {})
                except (json.JSONDecodeError, TypeError):
                    args = {}
                if name == "推荐图表":
                    chart_type = args.get("图表类型") or chart_type
                    reason = args.get("理由") or reason
                elif name == "聚合分析":
                    x_axis = args.get("X轴") or args.get("x轴") or x_axis
                    y_axis_list = args.get("Y轴") or args.get("y轴") or y_axis_list
                    group_field = args.get("分组字段") or group_field
                    agg_method = args.get("聚合方式") or agg_method

    if not chart_type:
        return None

    可用字段 = set(画像.get("字段列表", []))
    if x_axis and x_axis not in 可用字段:
        x_axis = None
    if isinstance(y_axis_list, str):
        y_axis_list = [y_axis_list]
    y_axis_list = [f for f in y_axis_list if f in 可用字段]
    if group_field and group_field not in 可用字段:
        group_field = None

    return {
        "图表类型": chart_type,
        "x轴": x_axis,
        "y轴": y_axis_list,
        "分组字段": group_field,
        "聚合方式": agg_method or "求和",
        "推荐理由": reason[:200],
    }
