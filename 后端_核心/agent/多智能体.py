"""轻量级多智能体架构：Supervisor + 3 个 Worker Agent。

架构
====
用户需求 → Supervisor Agent
  ├── 数据分析师 Agent（画像 → 聚合计算）
  ├── 图表设计师 Agent（选图表 → 出结论）
  └── 质量审查员 Agent（校验 → 通过/打回）

设计原则
========
- 每个 Agent 有独立的 system prompt，专注自己的角色
- Agent 间通过消息传递结果，不共享内存
- 质量审查员可以打回重做，形成反馈闭环
- 任何 Agent 失败 → Supervisor 接管降级
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from 后端_核心.agent.llm客户端 import chat_completion, extract_tool_call, is_llm_configured, embed_text
from 后端_核心.agent.工具集 import TOOL_SCHEMAS_FULL, execute_tool
from 后端_核心.agent.执行器注册 import 注册所有执行器
from 后端_核心.agent.trace import TraceRecorder
from config.settings import LLMRequestConfig

logger = logging.getLogger(__name__)
注册所有执行器()


# ── 各 Agent 的系统提示词 ──

_SYSTEM_PROMPTS = {
    "supervisor": """你是数据分析团队的 Supervisor。你需要：
1. 理解用户的分析需求
2. 依次调用团队成员：数据分析师 → 图表设计师 → 质量审查员
3. 如果某个环节失败，给出降级方案
4. 最终输出统一的分析结果

可用团队成员：
- 数据分析师：负责查看数据画像和执行聚合计算
- 图表设计师：负责推荐图表类型和生成分析结论
- 质量审查员：负责检查分析结果的合理性和准确性

请先调用「数据分析师」查看数据，再调用「图表设计师」出图，最后调用「质量审查员」复核。""",

    "数据分析师": """你是数据分析师。分析数据的步骤：
1. 先调用「获取数据画像」了解数据全貌
2. 再调用「聚合分析」按用户需求计算数据
3. 返回数据的统计分析结果

注意：所有字段名必须从数据画像的字段列表中选取。""",

    "图表设计师": """你是图表设计师。根据数据分析师提供的聚合结果：
1. 选择合适的图表类型
2. 调用「推荐图表」给出图表建议
3. 调用「生成结论」输出分析结论

图表选择规则：
- 占比/分布 → 饼图
- 时间趋势 → 折线图/面积图
- 分组对比 → 柱状图/堆积柱状图
- 数值关系 → 散点图""",

    "质量审查员": """你是质量审查员，负责检查分析结果的合理性和准确性。

检查要点：
1. 图表类型是否适合当前数据特征
2. 字段选择是否合理（分类字段做 X 轴，数值字段做 Y 轴）
3. 结论是否有数据支撑
4. 如果发现任何问题，返回「不通过+具体原因」
5. 如果一切正常，返回「通过」

不通过时请说明具体原因，以便重新分析。""",
}


def 多智能体分析(
    画像: Dict[str, Any],
    分析需求: str,
    df: Any = None,
    max_retries: int = 1,
    llm_config: Optional[LLMRequestConfig] = None,
) -> Dict[str, Any]:
    """多智能体方式执行数据分析。

    Args:
        画像: 数据画像
        分析需求: 用户需求
        df: DataFrame（用于工具执行）
        max_retries: 质量审查打回后的最大重试次数
        llm_config: 请求级 LLM 配置（并发安全）

    Returns:
        标准化意图 dict（含 Agent_Trace）
    """
    trace = TraceRecorder()
    context = {"画像": 画像, "df": df}
    tools = [s for s in TOOL_SCHEMAS_FULL if s["function"]["name"] != "解析为报表意图"]

    intent = None
    intent_source = "无"

    if not is_llm_configured(llm_config.api_key if llm_config else None) or not (分析需求 or "").strip():
        trace.记录观察(轮次=0, 说明="LLM 未配置，使用关键词匹配降级", 状态="成功")
        return _降级(画像, 分析需求, trace)

    # ── 第 1 步：数据分析师（画像 + 聚合） ──
    data_agent_result = _运行_agent("数据分析师", 分析需求, tools, context, trace, 轮次起始=1, llm_config=llm_config)
    if not data_agent_result["成功"]:
        logger.warning("数据分析师失败，降级")
        trace.记录观察(轮次=1, 说明="数据分析师执行失败，降级到关键词匹配", 状态="失败")
        return _降级(画像, 分析需求, trace)

    # ── 第 2 步：图表设计师（推荐图表 + 结论），带质量审查重试闭环 ──
    data_summary = data_agent_result["摘要"]
    chart_result = None
    passed = False
    last_review_feedback = ""

    for attempt in range(max_retries + 1):
        轮次图表 = 3 + attempt * 2

        if attempt == 0:
            chart_prompt = f"基于以下数据画像和分析结果进行图表推荐：\n画像摘要：{_画像摘要(画像)}\n数据分析结果：{data_summary}\n\n用户需求：{分析需求}"
        else:
            chart_prompt = (
                f"基于以下数据画像和分析结果进行图表推荐：\n画像摘要：{_画像摘要(画像)}\n数据分析结果：{data_summary}\n\n"
                f"用户需求：{分析需求}\n\n"
                f"【上一版审查意见】\n{last_review_feedback}\n\n"
                f"请根据审查意见修正分析方案后重新推荐。"
            )

        chart_result = _运行_agent("图表设计师", chart_prompt, tools, context, trace, 轮次起始=轮次图表, llm_config=llm_config)
        if not chart_result["成功"]:
            logger.warning(f"图表设计师第 {attempt+1} 次尝试失败")
            trace.记录观察(轮次=轮次图表, 说明=f"图表设计师第 {attempt+1} 次尝试失败", 状态="失败")
            if attempt < max_retries:
                continue
            return _降级(画像, 分析需求, trace)

        # ── 质量审查员 ──
        quality_prompt = (
            f"请检查以下分析结果：\n数据画像：{_画像摘要(画像)}\n"
            f"用户需求：{分析需求}\n"
            f"图表设计师推荐：{chart_result.get('摘要', '')}\n\n"
            f"请判断结果是否合理。如果发现问题，请明确说明具体原因和改进方向。"
        )
        quality_result = _运行_agent("质量审查员", quality_prompt, tools, context, trace, 轮次起始=轮次图表 + 1, llm_config=llm_config)

        if not quality_result["成功"]:
            trace.记录观察(轮次=轮次图表 + 1, 说明="质量审查员执行失败，跳过审查", 状态="失败")
            passed = True
            break

        passed = "不通过" not in quality_result.get("摘要", "")
        if passed:
            trace.记录观察(轮次=轮次图表 + 1, 说明=f"质量审查通过（第 {attempt+1} 次）", 状态="成功")
            break
        else:
            last_review_feedback = quality_result.get("摘要", "")
            trace.记录观察(轮次=轮次图表 + 1, 说明=f"质量审查不通过，准备第 {attempt+2} 次重试：{last_review_feedback[:100]}", 状态="需关注")

    if not passed:
        trace.记录观察(轮次=轮次图表 + 1, 说明="重试次数用尽，接受当前结果", 状态="需关注")

    # ── 提取意图 ──
    intent = _从消息提取意图(chart_result["消息"], 画像)
    if intent:
        intent_source = "LLM"
        trace.记录观察(轮次=6, 说明="多智能体分析完成" + ("（质量审查通过）" if passed else "（质量审查有建议）"), 状态="成功")
    else:
        return _降级(画像, 分析需求, trace)

    return {
        "图表类型": intent.get("图表类型", "自动推荐"),
        "x轴": intent.get("x轴"),
        "y轴": intent.get("y轴", []),
        "分组字段": intent.get("分组字段"),
        "聚合方式": intent.get("聚合方式", "求和"),
        "意图来源": intent_source,
        "推荐理由": intent.get("推荐理由", ""),
        "Agent_Trace": trace.to_list(),
    }


def _运行_agent(
    role: str,
    prompt: str,
    tools: List[Dict[str, Any]],
    context: Dict[str, Any],
    trace: TraceRecorder,
    轮次起始: int = 1,
    llm_config: Optional[LLMRequestConfig] = None,
) -> Dict[str, Any]:
    """运行一个 Agent，返回执行结果。"""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPTS.get(role, _SYSTEM_PROMPTS["supervisor"])},
        {"role": "user", "content": prompt},
    ]

    max_rounds = 2  # 每个 Agent 最多 2 轮 tool 调用
    for i in range(max_rounds):
        轮次 = 轮次起始 + i
        from 后端_核心.agent.编排器 import _执行一轮 as _一轮
        ok = _一轮(messages, tools, context, 轮次, trace, llm_config=llm_config)
        if not ok:
            return {"成功": False, "消息": messages, "摘要": "执行失败"}

    # 提取摘要
    摘要 = _提取最后工具结果(messages)
    return {"成功": True, "消息": messages, "摘要": 摘要}


def _提取最后工具结果(messages: List[Dict[str, Any]]) -> str:
    """从消息中提取最后一个工具调用的结果。"""
    for msg in reversed(messages):
        if msg.get("role") == "tool" and isinstance(msg.get("content"), str):
            return msg["content"][:300]
    return ""


def _画像摘要(画像: Dict[str, Any]) -> str:
    字段 = 画像.get("字段列表", [])
    return f"{画像.get('行数',0)}行/{画像.get('列数',0)}列，字段：{', '.join(字段[:8])}"


def _降级(画像: Dict[str, Any], 分析需求: str, trace: TraceRecorder) -> Dict[str, Any]:
    """关键词匹配降级。"""
    from 后端_核心.上传报表生成器 import _意图驱动配置
    rule_over = _意图驱动配置(画像, 分析需求)
    if rule_over:
        trace.记录观察(轮次=0, 说明="降级为关键词匹配", 状态="成功")
        return {
            "图表类型": rule_over.get("图表类型", "自动推荐"),
            "x轴": rule_over.get("x轴"),
            "y轴": rule_over.get("y轴", []),
            "分组字段": rule_over.get("分组字段"),
            "聚合方式": rule_over.get("聚合方式", "求和"),
            "意图来源": "规则",
            "推荐理由": rule_over.get("推荐理由", ""),
            "Agent_Trace": trace.to_list(),
        }
    trace.记录观察(轮次=0, 说明="未命中规则，自动推荐", 状态="成功")
    return {
        "图表类型": "自动推荐", "x轴": None, "y轴": [], "分组字段": None,
        "聚合方式": "求和", "意图来源": "规则", "推荐理由": "",
        "Agent_Trace": trace.to_list(),
    }


def _从消息提取意图(messages: List[Dict[str, Any]], 画像: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """从多轮消息中提取结构化意图。"""
    from 后端_核心.agent.编排器 import _从消息提取意图 as _提取
    return _提取(messages, {"字段列表": 画像.get("字段列表", [])} if 画像 else {"字段列表": []})
