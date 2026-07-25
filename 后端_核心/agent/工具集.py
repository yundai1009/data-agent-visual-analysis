"""Agent 工具集：4 个受控 Tool 的 schema 与执行器。

为什么不直接 exec LLM 生成的 pandas 代码
----------------------------------------
- LLM 生成代码 + ``exec`` 是“强大但危险”的路线，需要 AST 白名单、子进程隔离、
  资源限制才能勉强安全；本项目明确不走这条路线。
- 这里把 4 个**后端已有能力**包装成 Function Calling Tool，LLM 只能选这 4 个
  之一并填参数；参数再经过字段白名单校验才会真正执行，执行路径完全受后端控制。

4 个 Tool 一一对应"出报表"链路中的 4 个动作
------------------------------------------
1. ``生成数据画像_tool``     : 只读，输出数据画像摘要（喂给 LLM 自己看）
2. ``推荐图表_tool``         : 输入数据特征 → 输出图表类型建议
3. ``聚合分析_tool``         : 输入 X/Y/分组/聚合方式 → 输出聚合后数据
4. ``生成结论_tool``         : 只读，根据画像 + 聚合结果生成结论文本

阶段 1 实际使用
--------------
阶段 1 只用 ``意图识别`` 这一种 Tool（让 LLM 把自然语言直接结构化为意图 dict）。
其余 3 个 Tool 的 schema 已就位但本轮不暴露给 LLM，留给阶段 2 的 ReAct 多轮编排。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# OpenAI Function Calling tools schema（DeepSeek 兼容）
意图识别_tool_schema: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "解析为报表意图",
        "description": (
            "把用户自然语言分析需求，结结已给出的数据画像，转化为一个结构化的报表意图。"
            "字段名必须严格从画像.字段列表中选取，图表类型必须从图表类型枚举中选取。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "图表类型": {
                    "type": "string",
                    "enum": ["自动推荐", "柱状图", "折线图", "饼图", "散点图",
                             "表格", "直方图", "热力图", "堆积柱状图", "面积图", "雷达图"],
                    "description": "图表类型；当没有明确指向时用「自动推荐」",
                },
                "X轴": {
                    "type": ["string", "null"],
                    "description": "X 轴字段名，必须是画像.字段列表中的字段；无则填 null",
                },
                "Y轴": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Y 轴字段名列表，元素必须来自画像.字段列表；无则空数组",
                },
                "分组字段": {
                    "type": ["string", "null"],
                    "description": "分组字段名，必须来自画像.字段列表；无则填 null",
                },
                "聚合方式": {
                    "type": "string",
                    "enum": ["求和", "平均值", "计数", "最大值", "最小值"],
                    "description": "聚合方式；占比/分布场景一律用「计数」",
                },
                "推荐理由": {
                    "type": "string",
                    "description": "一句话说明为什么选这个图表和这几个字段，便于前端展示推荐依据",
                },
            },
            "required": ["图表类型", "Y轴", "聚合方式"],
        },
    },
}


# 暴露给 LLM 的工具列表（阶段 1 仅 1 个）
TOOL_SCHEMAS: List[Dict[str, Any]] = [意图识别_tool_schema]

# 工具名 → 执行器 映射。阶段 1 的“执行”其实是“校验 + 透传”，不做 pandas 计算。
TOOL_EXECUTORS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Optional[Dict[str, Any]]]] = {}


def validate_intent_against_profile(
    intent: Dict[str, Any],
    画像: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """把 LLM 输出的意图 dict 校验为安全的报表意图。

    进入 ``上传报表生成器.生成报表数据`` 前的最后一道白名单：
    - 字段名必须在 ``画像["字段列表"]`` 中；
    - 图表类型必须在 ``图表类型映射.keys()`` 中（与现有项目同步）；
    - 聚合方式必须在 ``聚合映射.keys()`` 中；
    - Y 轴必须是 list[str]。

    任一字段非法 → 返回 ``None``，由上层回退到关键词匹配兜底。
    合法 → 返回标准化的意图 dict（与 ``_受控语句配置`` 返回结构一致）。
    """
    if not isinstance(intent, dict) or not 画像:
        return None

    可用字段 = set(画像.get("字段列表") or [])
    if not 可用字段:
        return None

    图表类型 = intent.get("图表类型")
    校验后图表类型 = _validate_chart_type(图表类型)
    if 校验后图表类型 is None:
        return None

    x轴 = _validate_field(intent.get("X轴"), 可用字段)
    y轴_raw = intent.get("Y轴")
    y轴 = _validate_y_axis(y轴_raw, 可用字段)
    分组字段 = _validate_field(intent.get("分组字段"), 可用字段)
    聚合方式 = _validate_aggregation(intent.get("聚合方式"))
    推荐理由 = intent.get("推荐理由") or ""

    # 必须至少给出 X 轴或 Y 轴其中之一（否则什么也画不出来）
    if not x轴 and not y轴:
        return None

    return {
        "图表类型": 校验后图表类型,
        "x轴": x轴,
        "y轴": y轴,
        "分组字段": 分组字段,
        "聚合方式": 聚合方式,
        "推荐理由": str(推荐理由)[:200],
    }


# ---- 私有校验小函数 ----------------------------------------------------------

# 与 ``上传报表生成器.图表类型映射`` 同步增长时也要更新这里。
_VALID_CHART_TYPES = {"自动推荐", "柱状图", "折线图", "饼图", "散点图",
                      "表格", "直方图", "热力图", "堆积柱状图", "面积图", "雷达图"}
_VALID_AGGREGATIONS = {"求和", "平均值", "计数", "最大值", "最小值"}


def _validate_chart_type(value: Any) -> Optional[str]:
    if isinstance(value, str) and value in _VALID_CHART_TYPES:
        return value
    return None


def _validate_field(value: Any, 可用字段: set) -> Optional[str]:
    if isinstance(value, str) and value in 可用字段:
        return value
    return None


def _validate_y_axis(value: Any, 可用字段: set) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v in 可用字段]


def _validate_aggregation(value: Any) -> str:
    if isinstance(value, str) and value in _VALID_AGGREGATIONS:
        return value
    # 默认值与现有项目保持一致
    return "求和"
