from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import html
import json
import logging

import pandas as pd

from 后端_核心.数据画像 import 生成数据画像
from 后端_核心.agent.编排器 import 编排Agent
from 后端_核心.agent.结论润色 import 润色结论
from config.settings import LLMRequestConfig

logger = logging.getLogger(__name__)


图表类型映射 = {
    "自动推荐": "auto",
    "柱状图": "bar",
    "折线图": "line",
    "饼图": "pie",
    "散点图": "scatter",
    "表格": "table",
    "直方图": "histogram",
    "热力图": "heatmap",
    "堆积柱状图": "stacked_bar",
    "面积图": "area",
    "雷达图": "radar",
    "词云图": "wordcloud",
    "漏斗图": "funnel",
    "桑基图": "sankey",
    "箱线图": "boxplot",
    "环形图": "donut",
    "瀑布图": "waterfall",
    "旭日图": "sunburst",
    "K线图": "candlestick",
}

聚合映射 = {
    "求和": "sum",
    "平均值": "mean",
    "计数": "count",
    "最大值": "max",
    "最小值": "min",
}


def _可_json值(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, tuple, set)):
        return list(value)  # 嵌套 list 直接返回（箱线五数概括 / K 线 OHLC）
    if hasattr(value, "item"):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except (ValueError, TypeError):
        pass
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _可_json行(df: pd.DataFrame) -> List[Dict[str, Any]]:
    return [
        {str(key): _可_json值(value) for key, value in row.items()}
        for row in df.to_dict(orient="records")
    ]


def _可选字段(value: Optional[str]) -> Optional[str]:
    if value is None or value == "无" or value == "":
        return None
    return value


def _转换日期列(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    result = df.copy()
    for column in columns:
        if column in result.columns and not pd.api.types.is_datetime64_any_dtype(result[column]):
            parsed = pd.to_datetime(result[column], errors="coerce")
            if parsed.notna().sum() > 0:
                result[column] = parsed
    return result


def _匹配意图字段(画像: Dict[str, Any], 关键词列表: List[str], 需求文本: str = "") -> Optional[str]:
    可用字段 = 画像.get("字段列表", [])
    分类字段 = 画像.get("分类字段", [])
    候选字段 = [*可用字段, *分类字段]
    # 第一优先：需求文本中真正出现的关键词所匹配的字段
    # （如"工作经验要求占比图"→ 需求含"工作经验"，优先匹配工作经验字段，
    #   而不是按固定顺序被"时间"等字段抢先）
    if 需求文本:
        for 关键词 in 关键词列表:
            if 关键词 and 关键词 in 需求文本:
                for field in 候选字段:
                    if 关键词 in field:
                        return field
    # 第二优先：固定顺序
    for 关键词 in 关键词列表:
        for field in 候选字段:
            if 关键词 and 关键词 in field:
                return field
    if 分类字段:
        return 分类字段[0]
    if 可用字段:
        return 可用字段[0]
    return None


占比关键词 = ["占比", "比例", "分布", "构成", "占比图", "占比分布", "占比分析"]
# 维度/字段意图关键词（按优先级排列；命中后按“关键词 in 字段名”子串匹配字段）
字段意图关键词 = [
    # 时间/时长类（用户常用“工作时间/工时/时长/小时”描述占比需求）
    "工作时间", "工作时长", "加班", "工时", "时长", "小时", "时间", "日期", "月份", "年份",
    # 个人/组织维度
    "工作经验", "经验", "年龄", "年限", "学历", "性别", "薪资", "工资", "收入",
    # 地理/岗位维度
    "地区", "国家", "城市", "地点", "岗位", "职位", "分类", "类型", "行业", "部门", "公司",
]


def _提取模板字段(文本: str) -> List[str]:
    fields: List[str] = []
    start = 0
    while True:
        left = 文本.find("【", start)
        right = 文本.find("】", left + 1)
        if left == -1 or right == -1:
            break
        value = 文本[left + 1:right].strip()
        if value:
            fields.append(value)
        start = right + 1
    return fields


def _合法字段(画像: Dict[str, Any], field: Optional[str]) -> Optional[str]:
    if field and field in 画像.get("字段列表", []):
        return field
    return None


def 自动选字段(画像: Dict[str, Any], 图表类型: str) -> Dict[str, Any]:
    """按图表类型返回语义正确的字段组合（自然语言自动选择，零手动）。

    优先级：文本字段(词云) > 分类 > 日期 > 数值；字段不足时自动降级。
    返回 {图表类型, x轴, y轴, 分组字段, 聚合方式}。
    """
    分类 = 画像.get("分类字段") or []
    数值 = 画像.get("数值字段") or []
    日期 = 画像.get("日期字段") or []
    文本 = 画像.get("文本字段") or []
    字段列表 = 画像.get("字段列表") or []

    def _x() -> Optional[str]:
        return 分类[0] if 分类 else (日期[0] if 日期 else (字段列表[0] if 字段列表 else None))

    def _x2() -> Optional[str]:
        return 分类[1] if len(分类) > 1 else None

    def _y() -> List[str]:
        return [数值[0]] if 数值 else ["记录数"]

    def _agg() -> str:
        return "求和" if 数值 else "计数"

    base = {"图表类型": 图表类型}

    if 图表类型 == "词云图":
        # 文本字段优先；无文本字段取分类里最长的（仍可能分词出词）；再没有则 None（由生成函数兜底提示）
        x = 文本[0] if 文本 else (max(分类, key=lambda f: len(str(f)), default=None) if 分类 else None)
        return {**base, "x轴": x, "y轴": [], "分组字段": None, "聚合方式": "计数"}
    if 图表类型 == "散点图":
        x = 数值[0] if 数值 else None
        y = [数值[1]] if len(数值) > 1 else ([数值[0]] if 数值 else [])
        return {**base, "x轴": x, "y轴": y, "分组字段": None, "聚合方式": "求和"}
    if 图表类型 in ("箱线图", "K线图"):
        # K线优先日期（行情看时间轴）；箱线优先分类
        if 图表类型 == "K线图" and 日期:
            x = 日期[0]
        else:
            x = _x()
        y = _y()
        if x == (y[0] if y else None):
            # X==Y（单列/纯数值）：换另一个日期/分类，避免重复列
            x = 日期[0] if 日期 else (分类[1] if len(分类) > 1 else None)
        return {**base, "x轴": x, "y轴": y, "分组字段": None, "聚合方式": "求和"}
    if 图表类型 in ("热力图", "堆积柱状图", "桑基图", "旭日图"):
        return {**base, "x轴": _x(), "y轴": _y(), "分组字段": _x2(), "聚合方式": _agg()}
    if 图表类型 == "雷达图":
        y = 数值[:3] if 数值 else []
        return {**base, "x轴": _x(), "y轴": y, "分组字段": None, "聚合方式": "平均值"}
    if 图表类型 == "直方图":
        target = 数值[0] if 数值 else None
        return {**base, "x轴": target, "y轴": [target] if target else [], "分组字段": None, "聚合方式": "计数"}
    if 图表类型 in ("折线图", "面积图"):
        # 趋势类图表：日期字段优先作 X 轴
        x = 日期[0] if 日期 else _x()
        return {**base, "x轴": x, "y轴": _y(), "分组字段": None, "聚合方式": _agg()}
    # 柱状/饼/环形/漏斗/瀑布/表格/自动推荐
    return {**base, "x轴": _x(), "y轴": _y(), "分组字段": None, "聚合方式": _agg()}


def _合并显式字段(selected: Dict[str, Any], first: Optional[str], second: Optional[str]) -> Dict[str, Any]:
    """用户显式指定字段时覆盖自动选择（【字段】模板优先）。

    - first → X 轴
    - second：需要分组的图表（热力/堆积/桑基/旭日）→ 分组字段；
      其它图表 → Y 轴指标（避免误设分组导致 pandas 列冲突）
    """
    result = dict(selected)
    if first:
        result["x轴"] = first
    if second:
        分组类图表 = ("热力图", "堆积柱状图", "桑基图", "旭日图")
        if result.get("图表类型") in 分组类图表:
            result["分组字段"] = second
        else:
            y_list = result.get("y轴") or []
            if second not in y_list:
                result["y轴"] = [second] + [f for f in y_list if f != second]
    return result


def _受控语句配置(画像: Dict[str, Any], 分析需求: str) -> Dict[str, Any]:
    文本 = 分析需求.strip()
    fields = _提取模板字段(文本)

    first = _合法字段(画像, fields[0] if fields else None)
    second = _合法字段(画像, fields[1] if len(fields) > 1 else None)

    if "交叉分布" in 文本 or "热力图" in 文本 or "矩阵" in 文本 or "交叉分析" in 文本:
        return _合并显式字段(自动选字段(画像, "热力图"), first, second)
    if "直方图" in 文本 or "分布情况" in 文本 or "数值分布" in 文本:
        return _合并显式字段(自动选字段(画像, "直方图"), first, second)
    if "堆积" in 文本:
        return _合并显式字段(自动选字段(画像, "堆积柱状图"), first, second)
    if "关系" in 文本 or "相关" in 文本 or "散点" in 文本:
        return _合并显式字段(自动选字段(画像, "散点图"), first, second)
    if "雷达" in 文本:
        return _合并显式字段(自动选字段(画像, "雷达图"), first, second)
    if "词云" in 文本:
        return _合并显式字段(自动选字段(画像, "词云图"), first, second)
    if "漏斗" in 文本 or "转化" in 文本:
        return _合并显式字段(自动选字段(画像, "漏斗图"), first, second)
    if "桑基" in 文本 or "流向" in 文本:
        return _合并显式字段(自动选字段(画像, "桑基图"), first, second)
    if "箱线" in 文本 or "异常" in 文本 or "分布对比" in 文本:
        return _合并显式字段(自动选字段(画像, "箱线图"), first, second)
    if "环形" in 文本 or "甜甜圈" in 文本:
        return _合并显式字段(自动选字段(画像, "环形图"), first, second)
    if "瀑布" in 文本:
        return _合并显式字段(自动选字段(画像, "瀑布图"), first, second)
    if "旭日" in 文本 or "多层" in 文本:
        return _合并显式字段(自动选字段(画像, "旭日图"), first, second)
    if "K线" in 文本 or "行情" in 文本 or "蜡烛" in 文本:
        return _合并显式字段(自动选字段(画像, "K线图"), first, second)
    # 通用意图词（放在具体图表词之后，避免"多层占比旭日图"等被"占比"抢先命中）
    if "占比" in 文本 or "比例" in 文本 or "构成" in 文本:
        # 占比语义：优先匹配需求中提到的维度字段（如"工作时间占比"→ 工作时间），
        # 值统一用记录数计数（避免 x=y 同字段冲突）
        intent_field = _匹配意图字段(画像, 字段意图关键词, 文本)
        if intent_field and _合法字段(画像, intent_field):
            override = {"图表类型": "饼图", "x轴": intent_field, "y轴": ["记录数"],
                        "分组字段": None, "聚合方式": "计数"}
        else:
            override = 自动选字段(画像, "饼图")
        return _合并显式字段(override, first, second)
    if "趋势" in 文本 or "变化" in 文本 or "面积图" in 文本:
        chart = "面积图" if "面积图" in 文本 else "折线图"
        return _合并显式字段(自动选字段(画像, chart), first, second)
    if "统计" in 文本 and "数量" in 文本:
        return _合并显式字段(自动选字段(画像, "柱状图"), first, second)
    if "比较" in 文本 or "对比" in 文本:
        return _合并显式字段(自动选字段(画像, "柱状图"), first, second)
    return {}


def _解析自然语言意图(
    画像: Dict[str, Any],
    分析需求: str,
    df=None,
    llm_config: Optional[LLMRequestConfig] = None,
    on_event: Optional[Any] = None,
    user_id: str = "",
) -> Tuple[Dict[str, Any], str, List[Dict[str, Any]], str]:
    """优先用 LLM 解析; 失败降级回规则匹配. 返回 (override, source, trace, llm_fail_reason)。
    source: LLM / 规则 / 无
    trace: 多轮 ReAct 决策记录，或空列表
    llm_fail_reason: LLM 失败原因（降级时供前端明示；成功或规则路径为空）
    on_event: 可选回调，trace 每记录一步即实时推送（SSE 直播）
    """
    if 分析需求 and 分析需求.strip():
        try:
            agent_result = 编排Agent(画像, 分析需求, df=df, llm_config=llm_config, on_event=on_event, user_id=user_id)
            if agent_result:
                override = {
                    "图表类型": agent_result["图表类型"],
                    "x轴": agent_result["x轴"],
                    "y轴": agent_result["y轴"],
                    "分组字段": agent_result["分组字段"],
                    "聚合方式": agent_result["聚合方式"],
                    "推荐理由": agent_result.get("推荐理由", ""),
                }
                fail_reason = agent_result.get("LLM失败原因", "")
                return override, agent_result["意图来源"], agent_result["Agent_Trace"], fail_reason
            logger.warning("LLM 意图解析返回 None, 降级到关键词匹配")
        except Exception as exc:
            logger.warning("LLM 意图解析异常, 降级到关键词匹配: %s", exc)
    rule_override = _意图驱动配置(画像, 分析需求)
    return rule_override, ("规则" if rule_override else "无"), [], ""


def _意图驱动配置(画像: Dict[str, Any], 分析需求: str) -> Dict[str, Any]:
    controlled = _受控语句配置(画像, 分析需求)
    if controlled:
        return {key: value for key, value in controlled.items() if value not in (None, [None])}

    需求文本 = 分析需求.strip()
    if not any(keyword in 需求文本 for keyword in 占比关键词):
        return {}

    目标字段 = _匹配意图字段(画像, 字段意图关键词, 需求文本)
    if not 目标字段:
        return {}

    return {
        "图表类型": "饼图",
        "x轴": 目标字段,
        "y轴": ["记录数"],
        "聚合方式": "计数",
    }


def _推荐图表类型(画像: Dict[str, Any], x轴: Optional[str], y轴列表: List[str], 分析需求: str = "") -> str:
    日期字段 = set(画像.get("日期字段", []))
    数值字段 = set(画像.get("数值字段", []))
    分类字段 = set(画像.get("分类字段", []))
    需求文本 = 分析需求.strip()

    if any(keyword in 需求文本 for keyword in 占比关键词):
        return "饼图"
    if x轴 in 日期字段 and y轴列表:
        return "折线图"
    if len(y轴列表) >= 2 and all(field in 数值字段 for field in y轴列表[:2]):
        return "散点图"
    if x轴 in 分类字段 and y轴列表:
        return "柱状图"
    if x轴 and y轴列表:
        return "柱状图"
    return "表格"


def _生成推荐说明(
    画像: Dict[str, Any],
    图表类型: str,
    x轴: Optional[str],
    y轴列表: List[str],
    分组字段: Optional[str],
    聚合方式: str,
    是否自动推荐: bool,
    分析需求: str = "",
) -> Dict[str, Any]:
    日期字段 = set(画像.get("日期字段", []))
    数值字段 = set(画像.get("数值字段", []))
    分类字段 = set(画像.get("分类字段", []))
    需求文本 = 分析需求.strip()
    reasons: List[str] = []

    if 是否自动推荐:
        reasons.append(f"系统根据字段类型自动选择 `{图表类型}`")
    else:
        reasons.append(f"使用用户手动选择的 `{图表类型}`")
    if any(keyword in 需求文本 for keyword in 占比关键词):
        reasons.append("需求包含占比/分布语义，优先使用饼图并按计数统计各分类占比")
    if x轴 in 日期字段:
        reasons.append(f"`{x轴}` 被识别为日期字段，适合观察趋势变化")
    elif x轴 in 分类字段:
        reasons.append(f"`{x轴}` 被识别为分类字段，适合做分组对比")
    elif x轴:
        reasons.append(f"`{x轴}` 作为当前分析维度")
    if y轴列表:
        numeric_y = [field for field in y轴列表 if field in 数值字段]
        if numeric_y:
            reasons.append(f"`{'、'.join(numeric_y)}` 是数值字段，适合用 `{聚合方式}` 生成指标")
        else:
            reasons.append("当前指标字段不是数值字段，系统按计数类聚合处理")
    if 分组字段:
        reasons.append(f"`{分组字段}` 用作颜色/分组字段，便于比较不同类别")

    return {
        "图表类型": 图表类型,
        "自动推荐": 是否自动推荐,
        "理由": reasons,
        "推荐字段": {
            "X轴": x轴,
            "Y轴": y轴列表,
            "分组字段": 分组字段,
            "聚合方式": 聚合方式,
        },
    }


def _字段问题提示(画像: Dict[str, Any], 图表类型: str, x轴: Optional[str], y轴列表: List[str], 分析需求: str = "") -> List[str]:
    warnings: List[str] = []
    数值字段 = set(画像.get("数值字段", []))
    需求文本 = 分析需求.strip()
    if 图表类型 != "表格" and not x轴:
        warnings.append("当前图表缺少 X 轴字段，已回退为数据预览/聚合结果")
    if 图表类型 not in {"表格", "饼图"} and not y轴列表:
        warnings.append("当前图表缺少 Y 轴数值字段，建议至少选择一个指标字段")
    if 图表类型 == "散点图" and len([field for field in y轴列表 if field in 数值字段]) < 2:
        warnings.append("散点图建议选择至少两个数值字段，否则相关性观察不充分")
    if 图表类型 == "饼图" and len(y轴列表) > 1:
        warnings.append("饼图只使用第一个 Y 轴字段作为占比值")
    if 图表类型 == "雷达图" and len(y轴列表) < 3:
        warnings.append("雷达图建议至少选择 3 个数值指标")
    if 图表类型 == "热力图" and not x轴:
        warnings.append("热力图需要至少一个分类字段作为 X 轴")
    if 图表类型 == "直方图" and (not x轴 or x轴 not in 数值字段):
        warnings.append("直方图建议选择一个数值字段")
    return warnings


def _生成_agent_trace(
    分析需求: str,
    画像: Dict[str, Any],
    图表类型: str,
    x轴: Optional[str],
    y轴列表: List[str],
    分组字段: Optional[str],
    聚合方式: str,
    推荐说明: Dict[str, Any],
    风险提示: List[str],
    意图来源: str = "无",
) -> List[Dict[str, Any]]:
    数据质量 = 画像.get("数据质量", {})
    if 分析需求.strip():
        理解说明 = f"意图来源：{意图来源}；需求：{分析需求.strip()}"
    else:
        理解说明 = "用户未填写自然语言需求，系统按字段结构生成基础报表。"
    return [
        {
            "步骤": "理解需求",
            "状态": "完成",
            "说明": 理解说明,
            "意图来源": 意图来源,
        },
        {
            "步骤": "识别数据",
            "状态": "完成",
            "说明": f"数据集包含 {画像.get('行数', 0)} 行、{画像.get('列数', 0)} 列；数值字段 {len(画像.get('数值字段', []))} 个，日期字段 {len(画像.get('日期字段', []))} 个，分类字段 {len(画像.get('分类字段', []))} 个。",
        },
        {
            "步骤": "推荐配置",
            "状态": "完成",
            "说明": "；".join(推荐说明.get("理由", [])) or f"使用 `{图表类型}` 生成报表。",
            "配置": {
                "图表类型": 图表类型,
                "X轴": x轴,
                "Y轴": y轴列表,
                "分组字段": 分组字段,
                "聚合方式": 聚合方式,
            },
        },
        {
            "步骤": "执行计算",
            "状态": "完成",
            "说明": f"按当前字段配置执行 `{聚合方式}` 聚合，并生成前端可渲染的图表数据。",
        },
        {
            "步骤": "质量检查",
            "状态": "需关注" if 风险提示 or 数据质量.get("提示") else "完成",
            "说明": "；".join([*数据质量.get("提示", []), *风险提示]) or "未发现明显的数据质量或字段适配风险。",
        },
        {
            "步骤": "生成结论",
            "状态": "完成",
            "说明": "结合报表数据、推荐依据和数据质量生成分析结论。",
        },
    ]


def _生成HTML报告(report: Dict[str, Any]) -> str:
    title = html.escape(report.get("标题") or "报表结果")
    recommendation = report.get("推荐说明", {})
    trace = report.get("Agent Trace", [])
    rows = report.get("报表数据", [])
    quality = report.get("数据画像", {}).get("数据质量", {})
    return f"""<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{title}</title>
  <style>
    body {{ font-family: Inter, 'PingFang SC', 'Microsoft YaHei', sans-serif; margin: 0; background: #f5f7fb; color: #0f172a; }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 24px; }}
    .card {{ background: #fff; border: 1px solid #dbe3f0; border-radius: 14px; padding: 16px; margin-bottom: 16px; box-shadow: 0 16px 32px rgba(15,23,42,.06); }}
    h1, h2, h3 {{ margin: 0 0 12px; }}
    .meta {{ display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
    .pill {{ display: inline-block; padding: 4px 10px; border-radius: 999px; background: #eff6ff; color: #2563eb; font-size: 12px; }}
    ul {{ margin: 8px 0 0 20px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ border-bottom: 1px solid #dbe3f0; padding: 8px 10px; text-align: left; vertical-align: top; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #f8fafc; border-radius: 12px; padding: 12px; }}
  </style>
</head>
<body>
<main>
  <div class=\"card\">
    <h1>{title}</h1>
    <div class=\"meta\">
      <div><strong>图表类型</strong>：{html.escape(report.get('图表类型') or '')}</div>
      <div><strong>数据质量</strong>：{html.escape(str(quality.get('等级', '未知')))}</div>
      <div><strong>数据集ID</strong>：{html.escape(report.get('数据集ID') or '')}</div>
      <div><strong>报表ID</strong>：{html.escape(report.get('报表ID') or '')}</div>
    </div>
  </div>

  <div class=\"card\">
    <h2>推荐依据</h2>
    {''.join(f'<div class="pill">{html.escape(str(reason))}</div>' for reason in recommendation.get('理由', [])) or '<div>暂无推荐依据</div>'}
  </div>

  <div class=\"card\">
    <h2>Agent Trace</h2>
    {''.join(f'<div><strong>{html.escape(str(step.get("步骤", "")))}</strong> · {html.escape(str(step.get("状态", "")))}<div>{html.escape(str(step.get("说明", "")))}</div></div><hr/>' for step in trace) or '<div>暂无 Trace</div>'}
  </div>

  <div class=\"card\">
    <h2>分析结论</h2>
    <pre>{html.escape(report.get('结论') or '')}</pre>
  </div>

  <div class=\"card\">
    <h2>报表数据</h2>
    <table>
      <thead>
        <tr>{''.join(f'<th>{html.escape(str(h))}</th>' for h in (rows[0].keys() if rows else []))}</tr>
      </thead>
      <tbody>
        {''.join('<tr>' + ''.join(f'<td>{html.escape(str(row.get(h, "")))}</td>' for h in (rows[0].keys() if rows else [])) + '</tr>' for row in rows) if rows else '<tr><td>暂无数据</td></tr>'}
      </tbody>
    </table>
  </div>
</main>
</body>
</html>"""


def _格式化数值(value: Any) -> str:
    if value is None:
        return "无"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _生成直方图数据(df: pd.DataFrame, field: Optional[str]) -> pd.DataFrame:
    if not field or field not in df.columns or not pd.api.types.is_numeric_dtype(df[field]):
        return df.head(200).copy()
    series = df[field].dropna()
    if series.empty or series.nunique() < 2:
        # 全常量列：分布无意义，直接返回空表（避免 cut 边界重合的晦涩异常）
        return pd.DataFrame(columns=[field, "记录数"])
    bins = min(10, max(3, int(series.nunique())))
    bucket = pd.cut(series, bins=bins, duplicates="drop")
    grouped = bucket.value_counts(sort=False).reset_index()
    grouped.columns = [field, "记录数"]
    grouped[field] = grouped[field].astype(str)
    return grouped


# 词云常用中文停用词（轻量集合，够用即可）
_中文停用词 = {
    "的", "了", "和", "与", "在", "是", "我", "你", "他", "她", "它", "有", "也", "就",
    "都", "而", "及", "或", "等", "对", "把", "被", "这", "那", "不", "一个", "我们",
    "你们", "他们", "这个", "那个", "一些", "一下", "因为", "所以", "但是", "如果",
    "并且", "或者", "还是", "已经", "可以", "进行", "没有", "不是", "通过", "对于",
    "以及", "其中", "然后", "什么", "怎么", "如何", "为什么",
}


def _生成词云数据(df: pd.DataFrame, text_field: Optional[str]) -> pd.DataFrame:
    """从文本字段分词统计词频，返回 [name, value] DataFrame（词云专用）。

    中文分词用 jieba；过滤停用词、单字词、纯数字。
    无文本字段或未提取到词时抛 ValueError，由接口转 400。
    """
    import jieba
    from collections import Counter

    field = _可选字段(text_field)
    if field is None or field not in df.columns:
        raise ValueError("词云图需要选择一个文本字段作为 X 轴")
    texts = df[field].dropna().astype(str)
    if texts.empty:
        raise ValueError("所选字段没有可分词的内容，请换一个文本字段")

    counter: Counter = Counter()
    for text in texts:
        for word in jieba.cut(text):
            word = word.strip()
            if not word or word in _中文停用词 or len(word) == 1 or word.isdigit():
                continue
            counter[word] += 1
    if not counter:
        raise ValueError("所选字段未提取到有效词（可能全是数字/停用词），请换一个文本字段")

    top = counter.most_common(60)
    return pd.DataFrame(top, columns=["name", "value"])


def _生成漏斗图数据(df: pd.DataFrame, x轴: Optional[str], y轴列表: List[str], 聚合方式: str) -> pd.DataFrame:
    """分类聚合后按值降序，作为漏斗的转化阶段。"""
    agg = _聚合数据(df, x轴, y轴列表, None, 聚合方式)
    if len(agg.columns) < 2 or agg.empty:
        return agg
    value_col = agg.columns[1]
    return agg.sort_values(value_col, ascending=False).reset_index(drop=True)


def _生成桑基图数据(df: pd.DataFrame, x轴: Optional[str], 分组字段: Optional[str], y轴列表: List[str], 聚合方式: str) -> pd.DataFrame:
    """两级流向：源=分组字段，目标=X 轴。缺分组字段时抛 ValueError（需两个分类字段）。"""
    if not x轴 or not 分组字段 or x轴 not in df.columns or 分组字段 not in df.columns:
        raise ValueError("桑基图需要两个分类字段（X 轴 + 分组字段）构成流向")
    value_field = y轴列表[0] if y轴列表 else "记录数"
    if 聚合方式 == "计数" or value_field == "记录数" or value_field not in df.columns:
        flow = df.groupby([分组字段, x轴], observed=True).size().reset_index(name="value")
    else:
        agg = 聚合映射.get(聚合方式, "sum")
        flow = df.groupby([分组字段, x轴], observed=True)[value_field].agg(agg).reset_index(name="value")
    flow.columns = ["源", "目标", "value"]
    return flow.head(500)  # 高基数字段限流，避免超大结果集


def _生成箱线图数据(df: pd.DataFrame, x轴: Optional[str], y轴列表: List[str]) -> pd.DataFrame:
    """每组五数概括 [min, Q1, median, Q3, max]，用于异常值/分布对比。"""
    if not x轴 or not y轴列表 or x轴 not in df.columns or y轴列表[0] not in df.columns:
        raise ValueError("箱线图需要 X 轴（分类）和 Y 轴（数值）字段")
    if x轴 == y轴列表[0]:
        raise ValueError("箱线图的 X 轴与 Y 轴需要选择不同字段")
    num = df[[x轴, y轴列表[0]]].copy()
    num[y轴列表[0]] = pd.to_numeric(num[y轴列表[0]], errors="coerce")
    num = num.dropna()
    if num.empty:
        raise ValueError("箱线图没有可统计的数据")
    rows = []
    for name, grp in num.groupby(x轴, observed=True):
        s = grp[y轴列表[0]]
        q1, med, q3 = s.quantile([0.25, 0.5, 0.75])
        rows.append({
            "name": str(name),
            "value": [round(float(s.min()), 4), round(float(q1), 4), round(float(med), 4),
                      round(float(q3), 4), round(float(s.max()), 4)],
        })
    return pd.DataFrame(rows).head(500)  # 高基数分组限流


def _生成瀑布图数据(df: pd.DataFrame, x轴: Optional[str], y轴列表: List[str], 聚合方式: str) -> pd.DataFrame:
    """分类聚合值（可正可负），前端按累计偏移渲染瀑布。"""
    agg = _聚合数据(df, x轴, y轴列表, None, 聚合方式)
    if len(agg.columns) < 2 or agg.empty:
        return agg
    agg = agg.reset_index(drop=True)
    agg.columns = ["name", "value"]
    return agg


def _生成旭日图数据(df: pd.DataFrame, x轴: Optional[str], 分组字段: Optional[str], y轴列表: List[str], 聚合方式: str) -> pd.DataFrame:
    """两级层级：外层=分组字段，内层=X 轴；无分组时单级。返回 层级,名称,value 或 名称,value。"""
    if not x轴 or x轴 not in df.columns:
        raise ValueError("旭日图需要选择 X 轴字段")
    value_field = y轴列表[0] if y轴列表 else "记录数"
    has_group = bool(分组字段) and 分组字段 in df.columns and 分组字段 != x轴
    if 聚合方式 == "计数" or value_field == "记录数" or value_field not in df.columns:
        if has_group:
            agg = df.groupby([分组字段, x轴], observed=True).size().reset_index(name="value")
            agg.columns = ["层级", "名称", "value"]
        else:
            agg = df.groupby(x轴, observed=True).size().reset_index(name="value")
            agg.columns = ["名称", "value"]
    else:
        agg = 聚合映射.get(聚合方式, "sum")
        if has_group:
            agg = df.groupby([分组字段, x轴], observed=True)[value_field].agg(agg).reset_index(name="value")
            agg.columns = ["层级", "名称", "value"]
        else:
            agg = df.groupby(x轴, observed=True)[value_field].agg(agg).reset_index(name="value")
            agg.columns = ["名称", "value"]
    return agg.head(500)  # 高基数层级限流


def _生成K线数据(df: pd.DataFrame, x轴: Optional[str], y轴列表: List[str]) -> pd.DataFrame:
    """按 X 轴分组派生 OHLC：[open=组内首个, close=组内最后, low=最小, high=最大]。"""
    if not x轴 or not y轴列表 or x轴 not in df.columns or y轴列表[0] not in df.columns:
        raise ValueError("K线图需要 X 轴（日期/分类）和 Y 轴（数值）字段")
    if x轴 == y轴列表[0]:
        raise ValueError("K线图的 X 轴与 Y 轴需要选择不同字段")
    num = df[[x轴, y轴列表[0]]].copy()
    num[y轴列表[0]] = pd.to_numeric(num[y轴列表[0]], errors="coerce")
    num = num.dropna()
    if num.empty:
        raise ValueError("K线图没有可统计的数据")
    rows = []
    for name, grp in num.groupby(x轴, observed=True):
        vals = grp[y轴列表[0]]
        rows.append({
            "name": str(name),
            "value": [round(float(vals.iloc[0]), 4), round(float(vals.iloc[-1]), 4),
                      round(float(vals.min()), 4), round(float(vals.max()), 4)],
        })
    return pd.DataFrame(rows).head(500)  # 高基数分组限流


def _生成热力图数据(df: pd.DataFrame, x轴: Optional[str], 分组字段: Optional[str], y轴列表: List[str], 聚合方式: str) -> pd.DataFrame:
    if not x轴 or not 分组字段 or x轴 not in df.columns or 分组字段 not in df.columns:
        return df.head(200).copy()
    value_field = y轴列表[0] if y轴列表 else "记录数"
    if 聚合方式 == "计数" or value_field == "记录数" or value_field not in df.columns:
        pivot = df.pivot_table(index=分组字段, columns=x轴, aggfunc="size", fill_value=0)
    else:
        agg = 聚合映射.get(聚合方式, "sum")
        pivot = df.pivot_table(index=分组字段, columns=x轴, values=value_field, aggfunc=agg, fill_value=0)
    return pivot.reset_index().melt(id_vars=[分组字段], var_name=x轴, value_name=value_field).head(500)


def _聚合数据(
    df: pd.DataFrame,
    x轴: Optional[str],
    y轴列表: List[str],
    分组字段: Optional[str],
    聚合方式: str,
) -> pd.DataFrame:
    if not x轴 or x轴 not in df.columns:
        return df.head(200).copy()

    valid_y = [field for field in y轴列表 if field in df.columns]
    # B10 修复：求和/均值等聚合要求数值列，日期/文本列过滤掉，否则 agg("sum") TypeError
    if 聚合方式 not in ("count", "计数"):
        valid_y = [field for field in valid_y if pd.api.types.is_numeric_dtype(df[field])]
    group_fields = [x轴]
    if 分组字段 and 分组字段 in df.columns and 分组字段 != x轴:
        group_fields.append(分组字段)

    if 聚合方式 == "count" or 聚合方式 == "计数":
        grouped = df.groupby(group_fields, dropna=False).size().reset_index(name="记录数")
        return grouped.sort_values(group_fields).head(500)

    agg = 聚合映射.get(聚合方式, "sum")
    if not valid_y:
        return df.head(200).copy()

    grouped = df.groupby(group_fields, dropna=False)[valid_y].agg(agg).reset_index()
    return grouped.sort_values(group_fields).head(500)


def _生成结论(
    分析需求: str,
    画像: Dict[str, Any],
    report_df: pd.DataFrame,
    图表类型: str,
    推荐说明: Dict[str, Any],
    风险提示: List[str],
) -> str:
    rows = 画像.get("行数", 0)
    cols = 画像.get("列数", 0)
    missing = 画像.get("总缺失值", 0)
    requirement = 分析需求.strip() or "未填写具体分析需求"
    数据质量 = 画像.get("数据质量", {})
    recommendation_lines = "\n".join(f"- {reason}" for reason in 推荐说明.get("理由", []))
    warning_lines = "\n".join(f"- {warning}" for warning in [*数据质量.get("提示", []), *风险提示]) or "- 未发现明显的数据质量或字段适配风险。"

    insight_lines: List[str] = []
    y_fields = 推荐说明.get("推荐字段", {}).get("Y轴", [])
    x_field = 推荐说明.get("推荐字段", {}).get("X轴")
    if x_field and y_fields and x_field in report_df.columns:
        first_y = y_fields[0]
        if first_y in report_df.columns and not report_df.empty:
            top_row = report_df.sort_values(first_y, ascending=False).iloc[0]
            insight_lines.append(
                f"- `{x_field}` 中 `{_格式化数值(top_row[x_field])}` 的 `{first_y}` 最高，值为 {_格式化数值(top_row[first_y])}。"
            )
            if len(report_df) >= 2:
                bottom_row = report_df.sort_values(first_y, ascending=True).iloc[0]
                insight_lines.append(
                    f"- `{x_field}` 中 `{_格式化数值(bottom_row[x_field])}` 的 `{first_y}` 最低，值为 {_格式化数值(bottom_row[first_y])}。"
                )
    if not insight_lines:
        insight_lines.append(f"- 当前报表结果包含 {len(report_df)} 行数据，可优先查看数据表确认明细。")

    insight_text = "\n".join(insight_lines)

    return (
        "### 报表结论\n\n"
        f"- 已基于上传数据生成 `{图表类型}`，原始数据共 {rows} 行、{cols} 列。\n"
        f"- 分析需求：{requirement}。\n"
        f"- 当前报表结果包含 {len(report_df)} 行聚合/预览数据。\n"
        f"- 数据中检测到 {missing} 个缺失值，数据质量等级：{数据质量.get('等级', '未知')}。\n\n"
        "### 推荐依据\n"
        f"{recommendation_lines}\n\n"
        "### 关键发现\n"
        f"{insight_text}\n\n"
        "### 注意事项\n"
        f"{warning_lines}"
    )


def 生成报表数据(
    df: pd.DataFrame,
    分析需求: str = "",
    图表类型: str = "自动推荐",
    x轴: Optional[str] = None,
    y轴: Optional[List[str] | str] = None,
    分组字段: Optional[str] = None,
    聚合方式: str = "求和",
    llm_config: Optional[LLMRequestConfig] = None,
    on_event: Optional[Any] = None,
    user_id: str = "",
) -> Dict[str, Any]:
    """根据上传数据和页面选择生成可渲染的报表配置。

    llm_config: 请求级 LLM 配置（并发安全）；为 None 时回退 EnvConfig 全局值。
    on_event: 可选回调，trace 每记录一步即实时推送（SSE 直播）。
    user_id: 归属用户（贯穿到 Agent 记忆的隔离检索/保存）。
    """
    if df.empty:
        raise ValueError("没有可用于生成报表的数据")

    画像 = 生成数据画像(df)
    df = _转换日期列(df, 画像.get("日期字段", []))
    x轴 = _可选字段(x轴)
    分组字段 = _可选字段(分组字段)

    if isinstance(y轴, str):
        y轴列表 = [y轴] if y轴 else []
    else:
        y轴列表 = [field for field in (y轴 or []) if field]

    intent_override, intent_source, agent_trace, llm_fail_reason = _解析自然语言意图(画像, 分析需求, df, llm_config=llm_config, on_event=on_event, user_id=user_id)
    if intent_override:
        # 优先级策略（阶段 B 改造）：
        # - 图表类型：仅当用户选"自动推荐"时采用 LLM 推荐；用户显式选择则尊重用户
        # - 字段：用户显式选择（非空）优先；用户未指定（空/自动推荐）才由 LLM 决策
        if 图表类型 == "自动推荐":
            图表类型 = intent_override["图表类型"]
        x轴 = x轴 or intent_override.get("x轴")
        y轴列表 = y轴列表 or intent_override.get("y轴")
        分组字段 = 分组字段 or intent_override.get("分组字段")
        聚合方式 = 聚合方式 or intent_override.get("聚合方式")

    是否自动推荐 = 图表类型 == "自动推荐"
    effective_chart = 图表类型
    if 是否自动推荐:
        effective_chart = _推荐图表类型(画像, x轴, y轴列表, 分析需求)

    if intent_override and 图表类型 == "饼图":
        effective_chart = "饼图"

    if effective_chart == "表格":
        report_df = df.head(200).copy()
    elif effective_chart == "直方图":
        report_df = _生成直方图数据(df, x轴)
    elif effective_chart == "热力图":
        report_df = _生成热力图数据(df, x轴, 分组字段, y轴列表, 聚合方式)
    elif effective_chart == "词云图":
        report_df = _生成词云数据(df, x轴)
    elif effective_chart == "漏斗图":
        report_df = _生成漏斗图数据(df, x轴, y轴列表, 聚合方式)
    elif effective_chart == "桑基图":
        report_df = _生成桑基图数据(df, x轴, 分组字段, y轴列表, 聚合方式)
    elif effective_chart == "箱线图":
        report_df = _生成箱线图数据(df, x轴, y轴列表)
    elif effective_chart == "环形图":
        report_df = _聚合数据(df, x轴, y轴列表, None, 聚合方式)  # 同饼图数据
    elif effective_chart == "瀑布图":
        report_df = _生成瀑布图数据(df, x轴, y轴列表, 聚合方式)
    elif effective_chart == "旭日图":
        report_df = _生成旭日图数据(df, x轴, 分组字段, y轴列表, 聚合方式)
    elif effective_chart == "K线图":
        report_df = _生成K线数据(df, x轴, y轴列表)
    else:
        report_df = _聚合数据(df, x轴, y轴列表, 分组字段, 聚合方式)

    plotly_type = 图表类型映射.get(effective_chart, "table")
    report_rows = _可_json行(report_df)
    chart_config: Dict[str, Any] = {
        "类型": plotly_type,
        "标题": 分析需求.strip() or f"上传数据{effective_chart}",
        "X轴": x轴 or (report_df.columns[0] if len(report_df.columns) else None),
        "Y轴": y轴列表,
        "颜色": 分组字段,
        "数据": report_rows,
    }

    if plotly_type in ("pie", "donut") and x轴 and y轴列表:
        chart_config["名称"] = x轴
        chart_config["值"] = y轴列表[0]
    if plotly_type == "wordcloud":
        chart_config["名称"] = "name"
        chart_config["值"] = "value"
    if plotly_type == "funnel" and len(report_df.columns) >= 2:
        chart_config["名称"] = report_df.columns[0]
        chart_config["值"] = report_df.columns[1]
    if plotly_type == "sankey":
        chart_config["名称"] = "源"
        chart_config["值"] = "value"
    if plotly_type == "boxplot":
        chart_config["名称"] = "name"
        chart_config["值"] = "value"
    if plotly_type == "waterfall":
        chart_config["名称"] = "name"
        chart_config["值"] = "value"
    if plotly_type == "sunburst":
        chart_config["名称"] = "名称"
        chart_config["值"] = "value"
    if plotly_type == "candlestick":
        chart_config["名称"] = "name"
        chart_config["值"] = "value"

    推荐说明 = _生成推荐说明(画像, effective_chart, x轴, y轴列表, 分组字段, 聚合方式, 是否自动推荐, 分析需求)
    风险提示 = _字段问题提示(画像, effective_chart, x轴, y轴列表, 分析需求)
    conclusion, conclusion_source = _生成结论_含来源(
        分析需求, 画像, report_df, effective_chart, 推荐说明, 风险提示,
        agent_trace, intent_source, llm_config=llm_config,
    )
    result = {
        "标题": chart_config["标题"],
        "分析需求": 分析需求,
        "图表类型": effective_chart,
        "图表配置": chart_config,
        "报表数据": report_rows,
        "数据画像": 画像,
        "推荐说明": 推荐说明,
        "风险提示": 风险提示,
        "Agent Trace": agent_trace or _生成_agent_trace(分析需求, 画像, effective_chart, x轴, y轴列表, 分组字段, 聚合方式, 推荐说明, 风险提示, intent_source),
        "意图来源": intent_source,
        "LLM失败原因": llm_fail_reason,
        "结论来源": conclusion_source,
        "导出数据": {
            "推荐文件名": "analysis-report.html",
            "格式": "html",
        },
        "结论": conclusion,
    }
    result["导出数据"]["HTML"] = _生成HTML报告(result)
    result["导出数据"]["JSON"] = json.dumps(result, ensure_ascii=False, default=str)
    return result
def _生成结论_含来源(
    分析需求: str,
    画像: Dict[str, Any],
    report_df: pd.DataFrame,
    图表类型: str,
    推荐说明: Dict[str, Any],
    风险提示: List[str],
    agent_trace: List[Dict[str, Any]],
    intent_source: str = "",
    llm_config: Optional[LLMRequestConfig] = None,
) -> Tuple[str, str]:
    """优先用 LLM 润色结论，失败回退模板拼接。返回（结论文本, 来源）。
    来源取值："LLM" | "模板"
    """
    if agent_trace:
        try:
            llm_结论 = 润色结论(分析需求, 画像, report_df, 推荐说明, 风险提示, llm_config=llm_config)
            if llm_结论:
                return llm_结论, "LLM"
        except Exception as exc:
            logger.warning("结论润色异常，回退模板：%s", exc)
    return _生成结论(分析需求, 画像, report_df, 图表类型, 推荐说明, 风险提示), "模板"