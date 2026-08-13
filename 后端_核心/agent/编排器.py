"""Agent 编排器：多轮 ReAct 编排 + 真实 Trace。

阶段 3 核心逻辑
==============
1. 第 1 轮：LLM 调用「获取数据画像」→ 感知数据
2. 第 2 轮：LLM 调用「聚合分析」→ 按需计算
3. 第 3 轮：LLM 调用「推荐图表」+「生成结论」→ 出结果
4. 任何一轮失败 → 整体降级到关键词匹配兜底
5. 所有调用记录在 TraceRecorder 中

═══════════════════════════════════════════════════════════════
【文件总览】项目层级与调用关系
═══════════════════════════════════════════════════════════════
- 所在目录：后端_核心/agent/
- 被谁调用：
  · 上传报表生成器.py → _解析自然语言意图() → 编排Agent()（报表生成主链路）
  · 前端 API 路由也可以直接调用编排Agent() 获取意图结果
- 调用了谁：
  · llm客户端.py   → chat_completion / extract_tool_call / is_llm_configured
  · 工具集.py      → TOOL_SCHEMAS_FULL / execute_tool / validate_intent_against_profile
  · trace.py       → TraceRecorder / 计时 / 提取token
  · 执行器注册.py  → 注册所有执行器()
  · 记忆.py        → 检索相似记忆 / 保存记忆 / 生成_few_shot_prompt / 清理记忆
  · 上传报表生成器.py → _意图驱动配置 / 自动选字段（LLM 失败时的降级路径）
- 本文件负责（业务定位）：
  1. 接收「用户自然语言需求 + 数据画像」两个输入
  2. 通过 3 轮 ReAct 循环让 LLM 逐步推理：感知数据 → 聚合计算 → 推荐图表+结论
  3. 每一轮的工具执行结果都追加回 messages，让 LLM 基于真实结果继续推理
  4. 任何一轮失败都降级到关键词匹配兜底，保证用户永远能看到可用的报表配置
  5. 分析完成后把结果存入长期记忆，下次相似需求可作为 few-shot 参考
- 面试要点：这是典型的 ReAct（Reasoning + Acting）模式，区别于单次提示；
  核心价值是「LLM 决策 + 后端受控执行」的分离，保证安全与可审计。
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
# 【关键行】这行在模块加载时就把 4 个工具的执行函数注册到全局 TOOL_EXECUTORS 字典中。
# 为什么：LLM 通过 Function Calling 选出工具名后，编排器需要立刻找到对应的后端执行函数来真正运行；
# 如果不提前注册，execute_tool() 找不到执行器会返回 None，整个 Agent 链路直接断掉。
# 删除后果：所有 LLM 工具调用都会失败（execute_tool 返回 None），Agent 只能降级到关键词匹配。
# 替代方案：可以改为首次调用时懒加载注册（lazy init），但会增加一次 if 判断开销；
# 当前启动时一次性注册是最简洁、最不容易出错的方案。
注册所有执行器()

_SYSTEM_PROMPT = """你是数据分析 Agent。根据用户的分析需求和数据画像，逐步完成分析任务。

你有以下工具可用：
1. 获取数据画像 — 读取数据集的字段信息和统计摘要
2. 聚合分析 — 按指定字段和聚合方式计算数据
3. 推荐图表 — 推荐合适的图表类型
4. 生成结论 — 生成分析结论

请按顺序调用工具，每次调用一个。完成所有分析后输出最终结论。

筛选与排名（重要）：
- 如果需求包含条件过滤（如"只看华东区"、"排除华南"、"销量大于500"），
  请在「聚合分析」的"筛选条件"参数中明确给出（字段/操作/值），AND 语义；
- 如果需求包含排名（如"销量Top 10的商品"、"前5名"），请给出"TopN"参数。
"""


def 解析自然语言需求(
    分析需求: str,
    画像: Dict[str, Any],
    *,
    enable_llm: Optional[bool] = None,
    llm_config: Optional[LLMRequestConfig] = None,
) -> Optional[Dict[str, Any]]:
    """兼容接口：从编排结果中提取标准化意图。

    作用：供不关心 Agent Trace 的调用方快速获取意图结果的简化入口，内部委托编排Agent 完成全部推理。

    入参：
      - 分析需求：用户输入的自然语言分析需求（如"按工作时间统计占比"）
      - 画像：数据画像 dict（含字段列表、字段类型等，由 数据画像.py 生成）
      - enable_llm：是否启用 LLM（None 表示自动判断）
      - llm_config：请求级 LLM 配置（provider/base_url/model），并发安全
    返回：
      - 成功：标准化意图 dict，结构为 {"图表类型", "x轴", "y轴", "分组字段", "聚合方式", "推荐理由"}
      - 失败：None（LLM 不可用 + 关键词匹配也未命中）
    业务定位：报表生成器的"快速通道"，跳过 Trace 等诊断信息，只返回核心意图。"""
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

    这是整个 Agent 系统的核心入口，实现了完整的 ReAct（Reasoning + Acting）循环：
      第 1 轮 → LLM 调用「获取数据画像」了解数据长什么样（字段名、类型、行数等）
      第 2 轮 → LLM 调用「聚合分析」选择字段并做实际计算
      第 3 轮 → LLM 调用「推荐图表」+「生成结论」出最终结果

    每一轮的机制：LLM 决策（选哪个工具 + 填什么参数）→ 后端执行工具 → 结果追加回
    messages → LLM 基于真实结果继续推理（而非凭空想象），这是 ReAct 模式的核心价值。

    Args:
        画像: 数据画像 dict（由 数据画像.py 生成，含字段列表/类型/质量等信息）
        分析需求: 用户自然语言需求（如"按学历统计薪资分布"）
        df: 原始 DataFrame（仅用于聚合分析 tool 的实际执行，编排器自身不直接操作数据）
        enable_llm: 是否启用 LLM（None=自动检测 API Key 是否配置）
        llm_config: 请求级 LLM 配置（provider/base_url/model），每个请求独立，并发安全
        on_event: 可选回调，trace 每记录一步就实时推送一条记录（供前端 SSE 直播用）
        user_id: 用户 ID（贯穿到 Agent 记忆的检索和保存，实现用户级隔离）

    Returns:
        标准化意图 dict，完整结构：
        {
          "图表类型": str, "x轴": str|None, "y轴": list[str],
          "分组字段": str|None, "聚合方式": str,
          "意图来源": "LLM"|"规则", "推荐理由": str,
          "Agent_Trace": list[dict],  # 每轮推理的证据链
          "LLM失败原因": str,         # LLM 不可用时的原因（供前端明示）
        }
        失败返回 None（理论上不会到这里，因为有规则兜底）
    """
    trace = TraceRecorder(on_event=on_event)
    if enable_llm is False:
        enable_llm = False
    else:
        # BYOK：按本次请求的 llm_config.api_key 判断（用户自带 Key 有效即启用 LLM）
        # 【关键行】这行判断当前请求是否有可用的 LLM API Key，决定走智能路径还是降级路径。
        # 为什么：系统支持 BYOK（Bring Your Own Key），用户可在前端填写自己的 Key；
        # Key 有效则走 LLM 智能路径，否则自动降级到关键词匹配兜底。
        # 删除后果：始终走降级路径，LLM 智能分析完全失效，用户永远只能看到规则匹配结果。
        # 替代方案：可在前端强制要求填写 Key（阻断式），但用户体验差；当前静默降级更友好。
        enable_llm = is_llm_configured(llm_config.api_key if llm_config else None)

    intent_override = None
    intent_source = "无"

    # ═══ LLM 多轮 ReAct ═══
    if enable_llm and (分析需求 or "").strip():
        # ── 检索相似历史记忆（few-shot） ──
        # 【关键行】从向量记忆库中检索与当前需求最相似的 top-3 条历史分析记录。
        # 为什么：LLM 在没有参考案例时容易"凭空想象"图表类型和字段组合；
        # few-shot 示例让 LLM 参考"类似需求上次怎么分析"，显著提升推荐准确率。
        # 删除后果：LLM 失去历史参考，首次分析可能选错图表/字段，但不会崩溃（准确率下降）。
        # 替代方案：RAG 检索增强 + 更复杂的 prompt 工程效果更好但成本高；
        # 当前方案（向量检索 top-3 + 格式化为 few-shot 文本）简单实用、性价比高。
        相似记忆 = 检索相似记忆(user_id, 分析需求, llm_config=llm_config)
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
        # 【关键行】ReAct 第 1 轮：让 LLM 调用「获取数据画像」工具，先感知数据长什么样。
        # 为什么：LLM 必须基于真实字段信息（字段名/类型/行数）才能做出正确决策；
        # 直接把画像文本塞给 LLM 会占用大量上下文 token，通过工具调用按需读取更省。
        # 删除后果：LLM 不知道数据有哪些字段，后续聚合/推荐全凭猜测，结果不可用。
        # 替代方案：把完整画像直接放进 system prompt（token 成本高、画像大时超限）；
        # 当前"工具按需读取"方案符合 Function Calling 主流实践。
        round1_ok = _执行一轮(messages, tools, context, 轮次=1, trace=trace, llm_config=llm_config)
        if not round1_ok:
            logger.warning("第 1 轮（数据画像）失败，降级")
            trace.记录观察(轮次=1, 说明="数据画像获取失败，降级到关键词匹配", 状态="失败")
        else:
            # ── 第 2 轮：聚合分析 ──
            # 【关键行】ReAct 第 2 轮：LLM 已看到画像，现在决定用哪些字段做聚合计算。
            # 为什么：聚合是"行动（Action）"环节，LLM 只负责填写字段参数，实际计算由后端执行；
            # 前一轮的画像结果已追加回 messages，LLM 能基于真实字段名选择，不瞎猜。
            # 删除后果：拿不到聚合结果，第 3 轮推荐图表和生成结论都无从谈起。
            # 替代方案：第 1、3 轮合并（一次调用同时感知+输出），但 LLM 一次推理的准确性
            # 低于多轮逐步推理；ReAct 多轮正是为了"每步基于真实观察再决策"。
            round2_ok = _执行一轮(messages, tools, context, 轮次=2, trace=trace, llm_config=llm_config)
            if not round2_ok:
                logger.warning("第 2 轮（聚合分析）失败，降级")
                trace.记录观察(轮次=2, 说明="聚合分析失败，降级到关键词匹配", 状态="失败")
            else:
                # ── 第 3 轮：推荐图表 + 生成结论 ──
                # 【关键行】ReAct 第 3 轮：LLM 基于前两轮的真实结果，推荐图表并生成结论。
                # 为什么：图表/结论必须建立在真实聚合数据之上，这也是"观察→再推理"的最后一环；
                # 前两轮失败时不会执行到这里，保证不会基于错误数据出结论。
                # 删除后果：拿不到 LLM 推荐的图表类型和结论，只能整链路降级到关键词匹配。
                # 替代方案：图表推荐可以完全交给规则函数（_推荐图表类型），但规则覆盖不了
                # 用户千变万化的自然语言描述；LLM 泛化能力强，规则做兜底是合理分工。
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
                        # 【关键行】把本次成功分析（需求+意图+画像摘要）写入向量记忆库。
                        # 为什么：这是"记忆增强"的关键一步——下次遇到相似需求，检索模块能找回
                        # 这次分析作为 few-shot 参考，Agent 越用越准。
                        # 删除后果：Agent 失去经验积累能力，每次分析从零开始，准确率下降。
                        # 替代方案：不保存（省存储但无记忆）；或用关系库存结构化历史；
                        # 向量库 + 语义检索最适合"找相似需求"这个场景。
                        try:
                            from 后端_核心.数据画像 import 生成数据画像
                            画像摘要 = f"{画像.get('行数',0)}行/{画像.get('列数',0)}列"
                            保存记忆(user_id, 分析需求, intent_override, 画像摘要, llm_config=llm_config)
                            from 后端_核心.agent.记忆 import 清理记忆  # 批次4：容量上限
                            清理记忆(5000)
                        except Exception as exc:
                            logger.warning("保存长期记忆失败: %s", exc)

    # ═══ 降级：关键词匹配 ═══
    # 【关键行】LLM 不可用/失败时走规则降级：用关键词匹配从需求文本中推断意图。
    # 为什么：不能让用户因 LLM 故障看到空白页面；关键词匹配虽不如 LLM 智能，
    # 但能保证"总有结果"，这是系统的最后一层兜底。
    # 删除后果：LLM 一挂，整条分析链路直接返回 None，前端报错，体验严重受损。
    # 替代方案：多次重试 LLM 后再报错（用户等待时间长）；当前优雅降级体验最好。
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
    # 【关键行】构造最终返回的标准化意图 dict：图表配置 + 诊断信息一起返回。
    # 为什么：上游（上传报表生成器）只认这个固定结构；Agent_Trace 是给前端展示
    # 推理过程用的证据链，LLM失败原因用于前端明确告知用户"为什么降级了"。
    # 删除后果：上游拿不到图表配置无法生成报表；删掉 Trace 用户看不到推理过程。
    # 替代方案：返回 pydantic 模型（类型安全但序列化多一步）；dict 最轻量直接。
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
        "LLM失败原因": (llm_config.llm_fail_reason if llm_config else "") or 最近LLM失败().get("reason", ""),
    }


def _执行一轮(
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    context: Dict[str, Any],
    轮次: int,
    trace: TraceRecorder,
    llm_config: Optional[LLMRequestConfig] = None,
) -> bool:
    """执行一轮 LLM 推理 + 工具调用——ReAct 循环的最小单元。

    作用：这一轮里完成「LLM 决策 → 后端执行工具 → 结果回填上下文」三个动作。

    入参：
      - messages：多轮对话历史（会不断追加 assistant 的 tool_call 和 tool 结果）
      - tools：本轮可用的工具 schema 列表（用于 Function Calling 声明）
      - context：工具执行上下文 {"画像": 画像, "df": df}
      - 轮次：当前是第几轮（1/2/3），用于 Trace 标记和 tool_call id 唯一化
      - trace：TraceRecorder 实例，用于记录每一步的证据
      - llm_config：请求级 LLM 配置（并发安全）
    返回：
      - True：本轮成功（LLM 返回了合法工具调用且工具执行成功）
      - False：失败（LLM 没返回工具调用 / 工具执行失败），上层决定是否继续或降级

    业务定位：ReAct 循环"一回合"的实现；编排器通过连调 3 个回合完成感知→计算→结论。

    1. 调 LLM → 拿到 tool_call
    2. 执行工具 → 得到结果
    3. 将 tool_call + 结果追加到 messages
    4. 返回 True/False
    """
    with 计时() as timer:
        # 【关键行】这行调用 LLM 聊天接口，把当前对话上下文 + 工具声明发给模型，让它决策调用哪个工具。
        # 为什么：LLM 负责"决定做什么"（选工具、填参数），实际执行必须回到后端受控函数，防止幻觉输出被直接执行。
        # 删除后果：本轮推理直接断掉，所有轮次全部失败，整条 Agent 链路瘫痪、报表无法智能生成。
        # 替代方案：让 LLM 直接返回计算结果，但结果不可校验、token 成本极高；
        # 现方案（LLM 决策 + 后端执行）是 Function Calling 行业主流。
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
    # 【关键行】把 LLM 的"决策"（选了哪个工具 + 什么参数）以标准 tool_calls 格式写回消息列表。
    # 为什么：OpenAI 协议要求 assistant 消息里带 tool_calls，下一轮 LLM 才能看到自己之前的决策；
    # 不写回的话对话历史不完整，LLM 会"失忆"。
    # 删除后果：多轮推理上下文断裂，LLM 无法继续基于自己的决策推理，第 2、3 轮效果大减。
    # 替代方案：把决策拼成普通文本塞回 content（不标准，部分模型不认）；标准 tool_calls 最稳。
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
    # 【关键行】这行调用工具执行器，把 LLM 选定的工具参数真正拿到后端受控函数里去执行。
    # 为什么：执行权必须留在后端——LLM 输出可能越界/幻觉，但最终字段白名单校验、聚合计算
    # 全部发生在受控代码里，LLM 无法把任意代码注入系统（安全边界）。
    # 删除后果：工具不执行，分析在中途断掉，所有报表都无法生成。
    # 替代方案：让 LLM 直接返回计算结果（不可校验、不可审计、token 成本高）；
    # 当前「LLM 决策 + 后端执行」是 Function Calling 行业主流，安全与可控性最好。
    result = execute_tool(tool_name, tool_args, context)
    if result is None:
        trace.记录LLM调用(轮次=轮次, prompt_summary=f"工具={tool_name}",
                          耗时_ms=timer.elapsed_ms, token=token_usage,
                          状态="失败", 理由=f"工具 {tool_name} 执行失败")
        # 追加失败消息
        # 失败信息也回填给 LLM，让它下一轮知道"这个工具不行，换个试试"。
        messages.append({
            "role": "tool",
            "tool_call_id": f"call_{轮次}",
            "content": f"工具 {tool_name} 执行失败，请重试或使用其他工具",
        })
        return False

    # 把工具结果转成文本塞回 messages
    # 【关键行】把工具执行结果（dict）转成纯文本，作为"观察（Observation）"回填给 LLM。
    # 为什么：LLM 下一轮推理必须看到这一轮的真实结果，这正是 ReAct 的核心——基于观察再推理；
    # 用文本而非原始 dict，是因为消息协议只认字符串。
    # 删除后果：LLM 拿不到观察结果，之后所有推理与真实数据脱节，输出不可信。
    # 替代方案：直接 json.dumps 整个结果（token 暴涨）；当前只抽取摘要字段，省 token 又够用。
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
    """把工具执行结果 dict 转成文本，供 LLM 继续推理。

    作用：工具执行器返回的 dict 结构各不相同（摘要/数据摘要/推荐图表/结论），
    这里统一抽取关键字段拼成一段人话文本，塞回 messages 作为观察结果。

    入参：
      - result：工具执行器返回的 dict（可能含 摘要/数据摘要/推荐图表/理由/结论 等键）
    返回：
      - str：拼接后的文本；若无可拼接字段则返回结果 dict 的 JSON 截断串（兜底不丢信息）
    业务定位：ReAct 循环"观察（Observation）"环节的序列化管道——把结构化结果
    翻译成 LLM 能读懂的自然语言，同时只挑摘要字段、控制 token 消耗。
    """
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
    """从多轮 ReAct 的 messages 中提取结构化意图。

    作用：三轮工具调用结束后，从对话历史里"复盘"——把 LLM 各轮填写的
    图表类型、X/Y 轴、分组字段、聚合方式汇总成一个干净的标准意图 dict。

    入参：
      - messages：完整的多轮对话历史（含 assistant tool_calls 和 tool 结果）
      - 画像：数据画像（用于过滤 LLM 幻觉出来的、字段列表里不存在的字段名）
    返回：
      - 成功：意图 dict {"图表类型","x轴","y轴","分组字段","聚合方式","推荐理由"}
      - 失败：None（没有合法的图表类型，或字段全部越界）
    业务定位：把"LLM 自由发挥的对话"翻译回"后端严格校验过的结构化配置"，
    是 LLM 输出落到系统边界前的最后一道安全闸门。
    """
    chart_type = None
    x_axis = None
    y_axis_list: List[str] = []
    group_field = None
    agg_method = None
    reason = ""
    filter_list: List[Dict[str, Any]] = []  # 阶段 29：筛选条件（聚合分析参数）
    top_n = None

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
                    filter_args = args.get("筛选条件") or []
                    if isinstance(filter_args, list):
                        filter_args = [f for f in filter_args if isinstance(f, dict) and f.get("字段")]
                        if filter_args:
                            filter_list = filter_list or []
                            for f in filter_args:
                                if f not in filter_list:
                                    filter_list.append(f)
                    top_n = args.get("TopN") or args.get("topN") or top_n

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
    # 阶段 29：筛选条件字段必须来自画像字段列表（白名单校验）
    valid_filters = [
        {"字段": f["字段"], "操作": f.get("操作", "等于"), "值": f.get("值")}
        for f in filter_list if f.get("字段") in 可用字段
    ]
    if top_n is not None:
        try:
            top_n = max(1, min(int(top_n), 200))
        except (TypeError, ValueError):
            top_n = None

    return {
        "图表类型": chart_type,
        "x轴": x_axis,
        "y轴": y_axis_list,
        "分组字段": group_field,
        "聚合方式": agg_method or "求和",
        "推荐理由": reason[:200],
        "筛选条件": valid_filters,
        "TopN": top_n,
    }
