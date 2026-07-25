"""Agent 编排器：自然语言 → 报表意图。

阶段 1 的执行模型
=================
Function Calling **单轮**：

    用户需求 + 数据画像
        → LLM（DeepSeek / OpenAI 兼容）
        → tool_calls[0].function.arguments
        → 字段白名单校验
        → 标准化意图 dict
        → 喂给 ``上传报表生成器.生成报表数据``

失败回退（每一步都要兜底）
==========================
- 未配 LLM_API_KEY            → ``is_llm_configured()`` False，跳过 LLM
- LLM 网络异常 / 超时 / 非 200 → ``chat_completion`` 返回 None
- LLM 响应里没有 tool_calls   → ``extract_tool_call`` 返回 None
- tool arguments 不是合法 JSON → ``extract_tool_call`` 内部返回 None
- 字段白名单校验失败          → ``validate_intent_against_profile`` 返回 None
- 任一处返回 None → 上层调用方回退到 ``_意图驱动配置`` 关键词匹配

**LLM 不会被 exec/eval，也不会被允许调用任意 Python 函数。**
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from 后端_核心.agent.llm客户端 import (
    chat_completion,
    extract_tool_call,
    is_llm_configured,
)
from 后端_核心.agent.工具集 import (
    TOOL_SCHEMAS,
    validate_intent_against_profile,
)

logger = logging.getLogger(__name__)


# 一次请求里喂给 LLM 的画像摘要字段。少而精，控制 token。
def _build_profile_summary(画像: Dict[str, Any]) -> Dict[str, Any]:
    """把完整数据画像压缩成 LLM prompt 用的摘要。

    — 不传 describe 全量统计（token 浪费，且 LLM 抓不住重点）
    — 不传每行原始数据（隐私 + token）
    — 传：字段列表 + 字段类型 + 数值/日期/分类字段 + 数据质量等级 + 行数 + 列数
    """
    return {
        "行数": 画像.get("行数", 0),
        "列数": 画像.get("列数", 0),
        "字段列表": 画像.get("字段列表", []),
        "字段类型": 画像.get("字段类型", {}),
        "数值字段": 画像.get("数值字段", []),
        "日期字段": 画像.get("日期字段", []),
        "分类字段": 画像.get("分类字段", []),
        "数据质量等级": (画像.get("数据质量") or {}).get("等级", "未知"),
    }


_SYSTEM_PROMPT = """你是数据分析 Agent，负责把用户的自然语言分析需求转化为结构化报表意图。

【强约束】
1. 字段名必须严格从画像.字段列表中选取；不要编造字段名。
2. 图表类型必须从枚举中选取：自动推荐 / 柱状图 / 折线图 / 饼图 / 散点图 / 表格 / 直方图 / 热力图 / 堆积柱状图 / 面积图 / 雷达图。
3. 聚合方式必须从枚举中选取：求和 / 平均值 / 计数 / 最大值 / 最小值。
4. 占比/分布/构成/份额类语句 → 一律用饼图 + 计数。
5. 趋势/随时间变化类语句 → 折线图，X 轴优先选日期字段。
6. 对比/比较类语句 → 柱状图。
7. 关系/相关/散点 → 散点图（X/Y 都必须是数值字段）。
8. 表达不清时 → 图表类型填「自动推荐」，让后端兜底。

【输出形式】
必须调用 ``解析为报表意图`` 工具，不要输出解释性文字。
"""


def _build_user_message(分析需求: str, 画像: Dict[str, Any]) -> str:
    """组装用户消息：分析需求 + 数据画像摘要。"""
    摘要 = _build_profile_summary(画像)
    return (
        f"用户需求：{分析需求.strip() or '（用户未填写具体需求，请按数据画像自动推荐）'}\n\n"
        f"数据画像摘要（JSON）：\n{_safe_json_dumps(摘要)}"
    )


def _safe_json_dumps(obj: Dict[str, Any]) -> str:
    """安全序列化，兼容 numpy 类型与中文。"""
    import json
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(obj)


def 解析自然语言需求(
    分析需求: str,
    画像: Dict[str, Any],
    *,
    enable_llm: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    """对外唯一入口：解析自然语言，返回标准化报表意图。

    参数
    ----
    分析需求    用户输入的自然语言；空串时交给 LLM 自动推荐
    画像        ``数据画像.生成数据画像`` 返回的完整画像
    enable_llm  测试用：强制关闭 LLM 走兜底路径

    返回
    ----
    形如::

        {"图表类型": "...", "x轴": "...", "y轴": [...],
         "分组字段": "...", "聚合方式": "...", "推荐理由": "..."}

    失败任何一步都返回 ``None``，调用方必须自行回退到关键词兜底。
    """
    if not 画像 or not isinstance(画像, dict):
        return None
    if not isinstance(分析需求, str):
        分析需求 = ""

    if enable_llm is False:
        return None
    if not is_llm_configured():
        return None
    if not 分析需求.strip():
        # 空需求直接交给关键词匹配兜底；LLM 不该被空需求扰唤
        return None

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _build_user_message(分析需求, 画像)},
    ]

    response = chat_completion(
        messages=messages,
        tools=TOOL_SCHEMAS,
        tool_choice="auto",
    )
    if response is None:
        logger.warning("LLM 调用失败或未配置，降级到关键词匹配")
        return None
    tool_call = extract_tool_call(response)
    if not tool_call:
        logger.warning("LLM 未返回 tool_call，降级到关键词匹配")
        return None
    if tool_call["name"] != "解析为报表意图":
        logger.warning("LLM 返回了非预期 tool: %s，降级到关键词匹配", tool_call["name"])
        return None

    intent = tool_call["arguments"] or {}
    if not isinstance(intent, dict):
        logger.warning("LLM tool_call arguments 非 dict")
        return None

    validated = validate_intent_against_profile(intent, 画像)
    if validated is None:
        logger.warning("LLM 意图未通过字段白名单校验，降级到关键词匹配")
    return validated
