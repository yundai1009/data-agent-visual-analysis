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

═══════════════════════════════════════════════════════════════
【文件总览】项目层级与调用关系
═══════════════════════════════════════════════════════════════
- 所在目录：后端_核心/agent/
- 被谁调用：
  · 编排器.py → TOOL_SCHEMAS_FULL（声明给 LLM 的工具清单）/ execute_tool（执行入口）
  · 执行器注册.py → register_tool_executor（把执行函数注入 TOOL_EXECUTORS 字典）
  · 上传报表生成器.py → validate_intent_against_profile（下钻到生成前的最后白名单）
- 调用了谁：无业务依赖（仅 logging + typing），执行器函数由其他模块注入
- 本文件负责：
  1. 定义 5 个 Function Calling 工具的 JSON Schema（意图识别/获取数据画像/聚合分析/推荐图表/生成结论）
  2. TOOL_EXECUTORS 注册表 + execute_tool 统一执行入口（异常转 None）
  3. validate_intent_against_profile：LLM 意图 dict 进入生成链路前的字段白名单校验
  4. 私有的 图表类型/字段/Y轴/聚合方式 四个校验小函数
- 面试要点：这是"受控 Agent"的安全核心——LLM 只能在这 5 个工具里选，
  参数必须通过白名单校验才能执行，从根本上杜绝 LLM 生成代码 + exec 的高危路线。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import logging

logger = logging.getLogger(__name__)

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
                             "表格", "直方图", "热力图", "堆积柱状图", "面积图", "雷达图",
                             "词云图", "漏斗图", "桑基图", "箱线图", "环形图",
                             "瀑布图", "旭日图", "K线图"],
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


# 暴露给 LLM 的工具列表（阶段 1 仅 1 个；阶段 2 扩到 5 个）
TOOL_SCHEMAS: List[Dict[str, Any]] = [意图识别_tool_schema]


# ===========================================================================
# 阶段 2 新增：4 个 ReAct 工具的 schema 与执行器
# ===========================================================================

数据画像_tool_schema: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "获取数据画像",
        "description": "读取当前数据集的字段画像：行数 / 列数 / 字段列表 / 字段类型 / 数值·日期·分类字段 / 数据质量等级。无入参。",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

聚合分析_tool_schema: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "聚合分析",
        "description": "按 X 轴 / 分组字段 / 聚合方式对数据集做 pandas 聚合，返回前 N 行结果。字段名必须来自画像.字段列表。",
        "parameters": {
            "type": "object",
            "properties": {
                "X轴": {"type": ["string", "null"], "description": "X 轴字段名，必须来自画像字段列表；无则 null"},
                "Y轴": {"type": "array", "items": {"type": "string"},
                         "description": "Y 轴字段列表，元素必须来自画像字段列表；空数组表示只做计数"},
                "分组字段": {"type": ["string", "null"], "description": "分组字段名；无则 null"},
                "聚合方式": {"type": "string", "enum": ["求和", "平均值", "计数", "最大值", "最小值"],
                             "description": "聚合方式；占比/分布场景一律用计数"},
                "前N行": {"type": "integer", "description": "返回前 N 行；默认 5，最大 50", "default": 5},
            },
            "required": ["X轴", "Y轴", "聚合方式"],
        },
    },
}

推荐图表_tool_schema: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "推荐图表",
        "description": "根据数据画像 + 已经做过的聚合结果，推荐一个合适的图表类型。会返回图表类型与一句话理由。",
        "parameters": {
            "type": "object",
            "properties": {
                "图表类型": {
                    "type": "string",
                    "enum": ["柱状图", "折线图", "饼图", "散点图", "表格",
                             "直方图", "热力图", "堆积柱状图", "面积图", "雷达图",
                             "词云图", "漏斗图", "桑基图", "箱线图", "环形图",
                             "瀑布图", "旭日图", "K线图"],
                    "description": "推荐的图表类型",
                },
                "理由": {"type": "string", "description": "为什么推荐这个图表（一句话）"},
            },
            "required": ["图表类型"],
        },
    },
}

生成结论_tool_schema: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "生成结论",
        "description": "看完整画像 + 聚合结果 + 推荐依据，写一段 200-400 字的中文 Markdown 分析结论：含关键发现、Top/Bottom、异常提示、跟需求呼应。",
        "parameters": {
            "type": "object",
            "properties": {
                "结论": {"type": "string", "description": "Markdown 格式的中文分析结论"},
            },
            "required": ["结论"],
        },
    },
}


# 阶段 2 全量工具 schema 暴露给编排器
TOOL_SCHEMAS_FULL: List[Dict[str, Any]] = [
    意图识别_tool_schema,
    数据画像_tool_schema,
    聚合分析_tool_schema,
    推荐图表_tool_schema,
    生成结论_tool_schema,
]


# 工具名 → 执行器映射：在编排器初始化时注入。
# 阶段 1 的“执行”仅做校验 + 透传，故映射为空；阶段 2 的执行器待 编排器.py 注入。
TOOL_EXECUTORS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Optional[Dict[str, Any]]]] = {}


def register_tool_executor(name: str, func: Callable[[Dict[str, Any], Dict[str, Any]], Optional[Dict[str, Any]]]) -> None:
    """注册工具执行器。编排器在启动时调用，把真实 pandas 函数注入到这里。

    作用：把"工具名"和"后端执行函数"绑定起来，存进全局 TOOL_EXECUTORS 字典。

    入参：
      - name：工具名（必须与 schema 里的 function.name 完全一致，LLM 靠它点名）
      - func：执行函数，签名 executor(arguments: dict, context: dict) -> dict|None
    返回：None（注册动作）
    业务定位：安全架构的关键一环——LLM 选工具后 execute_tool 查这个字典，
    名字对不上就执行不了，天然形成白名单。
    """
    TOOL_EXECUTORS[name] = func


def execute_tool(name: str, arguments: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """安全执行工具：白名单 + 字段校验在执行器内部完成；失败统一返回 None。

    作用：ReAct 循环"行动（Action）"的统一入口——按名字查注册表并调用执行器。

    入参：
      - name：LLM 决策选中的工具名
      - arguments：LLM 填写的参数 dict（可能含幻觉字段，执行器内部有白名单）
      - context：编排器注入的上下文（画像、df 等）
    返回：
      - 成功：执行器返回的结果 dict（摘要/数据摘要/推荐/结论）
      - 失败：None（工具未注册/执行器内部抛异常——一律吞掉转 None，不炸链路）
    业务定位：
      - 【关键行】LLM 决策与后端执行的边界线：所有工具调用都从这行进入受控代码。
      - 为什么：LLM 输出不可信，执行必须落在有白名单校验的后端函数里；
        异常一律吞掉并记日志，保证任何工具出错都只影响本轮、不影响整条链路。
      - 删除后果：工具全部无法执行，ReAct 循环瘫痪，报表无法生成。
      - 替代方案：让 LLM 直接返回计算结果（不可校验、token 成本高）；
        "LLM 决策 + 注册表查表执行"是 Function Calling 行业标准做法。
    """
    executor = TOOL_EXECUTORS.get(name)
    if not callable(executor):
        return None
    try:
        return executor(arguments, context)
    except Exception as exc:  # noqa: BLE001 工具执行器异常一律交给上层降级处理，但记录原因便于排查
        logger.warning("工具 %s 执行失败: %s", name, exc)
        return None


# ---- 私有校验小函数 ----------------------------------------------------------


def validate_intent_against_profile(
    intent: Dict[str, Any],
    画像: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """把 LLM 输出的意图 dict 校验为安全的报表意图。

    作用：这是进入 ``上传报表生成器.生成报表数据`` 前的最后一道白名单，
    所有来自 LLM 的字段名/图表类型/聚合方式都必须在这里通过校验。

    入参：
      - intent：LLM 输出的意图 dict（可能含幻觉字段、越界枚举值）
      - 画像：数据画像（提供字段列表，作为字段名的唯一合法来源）
    返回：
      - 成功：标准化的意图 dict（与 ``_受控语句配置`` 返回结构一致），键为小写
        图表类型/x轴/y轴/分组字段/聚合方式/推荐理由
      - 失败：None（任一字段非法/缺 X 轴且缺 Y 轴），上层回退到关键词匹配兜底

    业务定位：
      - 【关键行】安全边界——LLM 输出想进入报表生成链路，必须过这道"安检门"。
      - 为什么：LLM 可能编造不存在的字段名（幻觉），直接拿去 groupby 会抛 KeyError；
        白名单校验让"能进到生成器的字段"一定是画像里真实存在的。
      - 删除后果：LLM 幻觉字段直接进入 pandas 聚合，报表生成频繁报错或产出空表。
      - 替代方案：try/except 包裹生成过程（被动兜底，问题字段会被悄悄丢弃）；
        主动白名单校验（当前方案）能在源头拦截，还能统一记录原因。

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
                      "表格", "直方图", "热力图", "堆积柱状图", "面积图", "雷达图",
                      "词云图", "漏斗图", "桑基图", "箱线图", "环形图",
                      "瀑布图", "旭日图", "K线图"}
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
