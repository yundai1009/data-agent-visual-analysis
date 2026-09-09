from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
import html
import json
import logging

import numpy as np
import pandas as pd

from 后端_核心.数据画像 import 生成数据画像
from 后端_核心.数据筛选 import 应用筛选, 提取TopN, 匹配筛选条件, TOPN_排除图表
from 后端_核心.agent.编排器 import 编排Agent
from 后端_核心.agent.结论润色 import 润色结论
from config.settings import LLMRequestConfig

from 后端_核心.规则意图 import (
    _匹配意图字段, _提取模板字段, _合法字段,
    自动选字段, _合并显式字段, _受控语句配置,
    _意图驱动配置, _推荐图表类型,
    占比关键词, 字段意图关键词,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 【文件总览】项目层级与调用关系
# ═══════════════════════════════════════════════════════════════
# - 所在目录：后端_核心/（报表生成的"总装车间"，1000+ 行核心业务文件）
# - 被谁调用：
#   · API 路由层（上传报表相关接口）→ 生成报表数据()
#   · 多智能体.py → 生成报表数据()（多智能体流程最终也走这里出报表）
#   · 编排器.py → _意图驱动配置() / 自动选字段()（Agent 降级路径的规则兜底）
# - 调用了谁：
#   · 数据画像.py    → 生成数据画像(df)（先摸清数据底细，后续选字段全靠它）
#   · agent/编排器.py → 编排Agent()（LLM 多轮 ReAct 解析自然语言意图）
#   · agent/结论润色.py → 润色结论()（LLM 把模板结论润色成更自然的分析报告）
#   · config/settings.py → LLMRequestConfig（请求级 LLM 配置）
# - 本文件负责：
#   1. 生成报表数据()：主流程——画像 → 意图解析(LLM优先/规则兜底) → 推荐图表
#      → 按图表类型分发到各专用数据生成函数 → 组装前端可渲染的图表配置
#   2. 意图解析链路：_解析自然语言意图 → 编排Agent(LLM) / _意图驱动配置(规则)
#   3. 图表类型分发：直方图/热力图/词云图/漏斗图/桑基图/箱线图/瀑布图/旭日图/K线图
#      各有专用 _生成xxx数据() 函数，其余走通用 _聚合数据()
#   4. 结论与报告：_生成结论(模板) / _生成结论_含来源(LLM优先) / _生成HTML报告(导出)
# - 面试要点：双引擎设计——LLM 智能解析失败时规则引擎无缝接管，用户无感知；
#   所有 LLM/规则输出最终都收敛成同一个"标准意图 dict"，再走同一套生成管线。
# ═══════════════════════════════════════════════════════════════


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
        value = value.item()
    try:
        if pd.isna(value):
            return None
    except (ValueError, TypeError):
        pass
    # M24：非有限浮点（±inf/NaN，来自"环比/同比"等除零计算）→ None，
    # 否则 json.dumps 产出非法 JSON（Infinity/NaN）导致前端解析崩溃
    if isinstance(value, float) and not np.isfinite(value):
        return None
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


def _解析自然语言意图(
    画像: Dict[str, Any],
    分析需求: str,
    df=None,
    llm_config: Optional[LLMRequestConfig] = None,
    on_event: Optional[Any] = None,
    user_id: str = "",
) -> Tuple[Dict[str, Any], str, List[Dict[str, Any]], str]:
    """优先用 LLM 解析; 失败降级回规则匹配. 返回 (override, source, trace, llm_fail_reason)。

    作用：报表生成器的"意图解析总入口"——把用户自然语言需求变成结构化报表配置。

    入参：
      - 画像：数据画像 dict（字段列表等）
      - 分析需求：用户输入的自然语言需求文本
      - df：原始 DataFrame（透传给编排Agent，供聚合工具实际执行）
      - llm_config：请求级 LLM 配置（并发安全）
      - on_event：可选回调，trace 每记录一步即实时推送（SSE 直播）
      - user_id：用户 ID（透传给记忆检索/保存）

    返回：
      - override：标准意图 dict（图表类型/x轴/y轴/分组字段/聚合方式/推荐理由）
      - source：意图来源，"LLM" / "规则" / "无"
      - trace：多轮 ReAct 决策记录，或空列表
      - llm_fail_reason：LLM 失败原因（降级时供前端明示；成功或规则路径为空）
    业务定位：
      - 【关键行】双引擎切换开关：LLM 智能解析优先，任何异常/None 都降级到规则。
      - 为什么：LLM 可能未配置 Key、网络波动、返回非法 JSON；规则兜底保证
        用户永远拿到一份可用配置，这是"体验优先 + 优雅降级"的工程实践。
      - 删除后果：LLM 一失败整个报表生成直接抛错，用户操作全部中断。
      - 替代方案：前端先校验 Key 再允许点生成（阻断式，误伤自带 Key 用户）；
        当前"静默降级 + 原因透传"体验最好。
    """
    if 分析需求 and 分析需求.strip():
        try:
            # LLM 智能解析：调编排Agent 走 3 轮 ReAct；内部失败会自己降级并返回降级结果
            agent_result = 编排Agent(画像, 分析需求, df=df, llm_config=llm_config, on_event=on_event, user_id=user_id)
            if agent_result:
                override = {
                    "图表类型": agent_result["图表类型"],
                    "x轴": agent_result["x轴"],
                    "y轴": agent_result["y轴"],
                    "分组字段": agent_result["分组字段"],
                    "聚合方式": agent_result["聚合方式"],
                    "推荐理由": agent_result.get("推荐理由", ""),
                    "筛选条件": agent_result.get("筛选条件") or [],
                    "TopN": agent_result.get("TopN"),
                    "对比": agent_result.get("对比"),
                }
                # 阶段 29 兜底：编排器内部降级结果（无 key 时）不含筛选/TopN——
                # 用规则层识别补齐，保证"只看华东区"/"Top 10"在 LLM 路径同样生效
                if df is not None and not override["筛选条件"]:
                    override["筛选条件"] = 匹配筛选条件(分析需求, df, 画像)
                if df is not None and not override["TopN"]:
                    override["TopN"] = 提取TopN(分析需求)
                # 阶段 30 兜底：规则层识别"环比/同比"（LLM 未给出时补齐）
                if not override["对比"] and ("环比" in 分析需求 or "同比" in 分析需求):
                    override["对比"] = "环比" if "环比" in 分析需求 else "同比"
                fail_reason = agent_result.get("LLM失败原因", "")
                return override, agent_result["意图来源"], agent_result["Agent_Trace"], fail_reason
            logger.warning("LLM 意图解析返回 None, 降级到关键词匹配")
        except Exception as exc:
            # 阶段 34 修复：异常时把原因透传给调用方（此前硬编码空串，
            # 前端/评测看不到"为什么降级"，排查全靠猜）
            logger.warning("LLM 意图解析异常, 降级到关键词匹配: %s", exc)
            _降级原因 = f"LLM 意图解析异常: {str(exc)[:200]}"
            rule_override = _意图驱动配置(画像, 分析需求, df)
            return rule_override, ("规则" if rule_override else "无"), [], _降级原因
    # 规则降级路径：关键词匹配 + 模板语法解析（不依赖 LLM，永远可用）
    rule_override = _意图驱动配置(画像, 分析需求, df)
    return rule_override, ("规则" if rule_override else "无"), [], ""


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
    if not field or field not in df.columns:
        return pd.DataFrame(columns=["记录数"])
    if not pd.api.types.is_numeric_dtype(df[field]):
        # 阶段 34 修复：文本字段直方图 → 按分类计数（原实现返回 df.head(200)
        # 原始明细，前端取值字段回退文本列 → 全 0，与饼图同源问题）。
        return (
            df[field].dropna().astype(str).value_counts()
            .reset_index()
            .rename(columns={"index": field, 0: "记录数"})
        )
    series = df[field].dropna()
    # S14 修复：剔除 ±inf/NaN——pd.cut 遇到无穷值会抛 ValueError 导致 500
    series = series[np.isfinite(series)]
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


def _限基数列(df: pd.DataFrame, col: Optional[str], top: int = 200) -> pd.DataFrame:
    """S13：高基数列截断——保留出现频次最高的 top 个值，其余行丢弃。

    用于 pivot/透视前的防护：高基数分类列（如几万种商品名）直接 pivot
    会产生巨矩阵导致 OOM；截断到频次 top-N 后行列数可控。
    """
    if not col or col not in df.columns:
        return df
    counts = df[col].value_counts()
    if len(counts) <= top:
        return df
    keep = set(counts.head(top).index)
    return df[df[col].isin(keep)]


def _生成热力图数据(df: pd.DataFrame, x轴: Optional[str], 分组字段: Optional[str], y轴列表: List[str], 聚合方式: str) -> pd.DataFrame:
    if not x轴 or not 分组字段 or x轴 not in df.columns or 分组字段 not in df.columns:
        return df.head(200).copy()
    # S13 修复：pivot 前两列各截断 top-200，防高基数列 pivot 出巨矩阵 OOM
    df = _限基数列(df, 分组字段)
    df = _限基数列(df, x轴)
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
        # 阶段 34 修复（全图表"明细泄漏"）：空值列（LLM 漏填 y轴/聚合方式）时
        # 原实现返回 df.head(200) 原始明细——前端取值字段回退到第一个非名称列
        # （往往是日期/文本）→ Number()=NaN → 柱状图/折线图等同样出现"全 0"。
        # 兜底为"按 x轴 分类计数"：分类出现次数是空值列下唯一合理语义。
        return (
            df.groupby([x轴], dropna=False)
            .size()
            .reset_index(name="记录数")
            .sort_values(x轴)
            .head(500)
        )

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
        # S15 修复：混合类型列（如"100"与"abc"混存）排序会 TypeError 500——
        # 仅数值列参与 Top/Bottom 排序，非数值列跳过该洞察。
        if first_y in report_df.columns and not report_df.empty and pd.api.types.is_numeric_dtype(report_df[first_y]):
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


def _生成对比数据(report_df: pd.DataFrame, 对比: str, x轴: Optional[str]) -> pd.DataFrame:
    """阶段 30：在按时间聚合的结果上追加环比/同比列。

    语义（按行索引对齐，假设时间粒度均匀）：
      - 环比：与上一周期比 → 差值列「环比」+ 百分比列「环比率」；
      - 同比：与 12 个周期前比（按月粒度）→ 差值列「同比」+「同比增长率」。
    首行/数据不足 12 期时对应值为空（图表自然断点，不误报）。
    """
    if 对比 not in ("环比", "同比") or len(report_df) < 2:
        return report_df
    out = report_df.copy()
    数值列 = [c for c in out.columns if c != x轴 and pd.api.types.is_numeric_dtype(out[c])]
    if not 数值列:
        return report_df
    if 对比 == "环比":
        for col in 数值列:
            prev = out[col].shift(1)
            out[f"{col}环比"] = (out[col] - prev).round(4)
            out[f"{col}环比率"] = ((out[col] - prev) / prev * 100).round(2)
    else:  # 同比：隔 12 期（按月粒度）
        for col in 数值列:
            prev = out[col].shift(12)
            out[f"{col}同比"] = (out[col] - prev).round(4)
            out[f"{col}同比增长率"] = ((out[col] - prev) / prev * 100).round(2)
    return out


def 生成报表数据(
    df: pd.DataFrame,
    分析需求: str = "",
    图表类型: str = "自动推荐",
    x轴: Optional[str] = None,
    y轴: Optional[List[str] | str] = None,
    分组字段: Optional[str] = None,
    聚合方式: str = "求和",
    筛选条件: Optional[List[Dict[str, Any]]] = None,
    topN: Optional[int] = None,
    对比: Optional[str] = None,
    llm_config: Optional[LLMRequestConfig] = None,
    on_event: Optional[Any] = None,
    user_id: str = "",
) -> Dict[str, Any]:
    """根据上传数据和页面选择生成可渲染的报表配置。

    llm_config: 请求级 LLM 配置（并发安全）；为 None 时回退 EnvConfig 全局值。
    on_event: 可选回调，trace 每记录一步即实时推送（SSE 直播）。
    user_id: 归属用户（贯穿到 Agent 记忆的隔离检索/保存）。
    筛选条件: 显式筛选（AND 语义），在画像/聚合/结论之前应用——
        保证图表、结论、画像三者一致地反映"筛选后的世界"。
    topN: 聚合结果保留数值最大的前 N 行（"销量 Top 10"）。
    """
    if df.empty:
        raise ValueError("没有可用于生成报表的数据")

    # 阶段 29：条件筛选先行——筛选后数据才是画像/聚合/结论的"事实来源"
    显式筛选 = [c for c in (筛选条件 or []) if isinstance(c, dict)]
    if 显式筛选:
        df, 筛选说明 = 应用筛选(df, 显式筛选)
        if df.empty:
            raise ValueError("筛选后没有数据，请调整筛选条件（当前条件过滤掉了全部行）")
    else:
        筛选说明 = []

    画像 = 生成数据画像(df)
    df = _转换日期列(df, 画像.get("日期字段", []))
    x轴 = _可选字段(x轴)
    分组字段 = _可选字段(分组字段)

    if isinstance(y轴, str):
        y轴列表 = [y轴] if y轴 else []
    else:
        y轴列表 = [field for field in (y轴 or []) if field]

    intent_override, intent_source, agent_trace, llm_fail_reason = _解析自然语言意图(画像, 分析需求, df, llm_config=llm_config, on_event=on_event, user_id=user_id)
    # M23：用户原始请求语义（推荐说明文案用）——用户选了"自动推荐"时，即使
    # LLM 意图覆盖出了具体图表，文案也应说"系统自动选择"而非"用户手动选择"。
    用户请求自动推荐 = 图表类型 == "自动推荐"
    if intent_override:
        # 优先级策略（阶段 B 改造）：
        # - 图表类型：仅当用户选"自动推荐"时采用 LLM 推荐；用户显式选择则尊重用户
        # - 字段：用户显式选择（非空）优先；用户未指定（空/自动推荐）才由 LLM 决策
        if 图表类型 == "自动推荐":
            图表类型 = intent_override.get("图表类型", "自动推荐")
        x轴 = x轴 or intent_override.get("x轴")
        y轴列表 = y轴列表 or intent_override.get("y轴")
        分组字段 = 分组字段 or intent_override.get("分组字段")
        聚合方式 = 聚合方式 or intent_override.get("聚合方式")
        # 阶段 29：筛选/TopN 合并（显式 UI 筛选优先，意图筛选追加，AND 语义去重）
        for f in (intent_override.get("筛选条件") or []):
            if isinstance(f, dict) and f not in 显式筛选:
                显式筛选.append(f)
        if 显式筛选:
            df, 筛选说明 = 应用筛选(df, 显式筛选)
            if df.empty:
                raise ValueError("筛选后没有数据，请调整筛选条件（当前条件过滤掉了全部行）")
            画像 = 生成数据画像(df)  # 画像跟随筛选后的数据（结论/推荐说明保持一致）
        if not topN and intent_override.get("TopN"):
            topN = intent_override.get("TopN")
        if not 对比 and intent_override.get("对比"):
            对比 = intent_override.get("对比")

    # 是否自动推荐（意图覆盖后语义）：决定 effective_chart 是否走规则推荐——
    # intent 未给出图表类型（覆盖后仍为"自动推荐"）才用 _推荐图表类型 兜底
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
        # 阶段 34 修复：直方图数据固定为 [桶标签, 记录数]，y轴 必须指向计数列，
        # 否则前端 resolveKey 会命中桶标签文本列（Number→NaN→全 0，与饼图同源）。
        y轴列表 = ["记录数"]
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
    elif effective_chart == "瀑布图":
        report_df = _生成瀑布图数据(df, x轴, y轴列表, 聚合方式)
    elif effective_chart == "旭日图":
        report_df = _生成旭日图数据(df, x轴, 分组字段, y轴列表, 聚合方式)
    elif effective_chart == "K线图":
        report_df = _生成K线数据(df, x轴, y轴列表)
    else:
        # 阶段 33 修复（饼图全 0.0% bug）：饼图/环形图是"占比"语义，若 LLM 意图
        # 未给出值字段（y轴 为空）且聚合方式非计数，_聚合数据 会命中"无有效值列"
        # 的明细兜底——把原始数据行当报表数据（图例大量重复 + 占比全 0.0%）。
        # 强制按分类计数并把 y轴 补为聚合计数列：占比图在空 y轴 时"各分类出现
        # 次数"是唯一合理语义，且前端能据此取到值字段正确渲染占比。
        if effective_chart in ("饼图", "环形图") and (not y轴列表 or y轴列表[0] not in df.columns):
            # M22：值列与数据列不一致（LLM 幻觉字段/意图覆盖给出不存在的列）时，
            # 前端取不到值 → 占比全 0。降级为"各分类出现次数"（计数），
            # 值列统一为「记录数」，保证前端能正确取到值字段。
            聚合方式 = "计数"
            y轴列表 = ["记录数"]
        report_df = _聚合数据(df, x轴, y轴列表, 分组字段, 聚合方式)

    # 阶段 30：TopN 截断——"销量 Top 10"：按聚合结果的数值列降序保留前 N。
    # 仅对"按 X 聚合的排名表"类图表生效（表格/直方图等结构不适用）。
    if topN and effective_chart not in TOPN_排除图表 and len(report_df) > 1:
        排名值列 = [
            c for c in report_df.columns[1:]
            if pd.api.types.is_numeric_dtype(report_df[c])
        ]
        if 排名值列:
            report_df = report_df.sort_values(排名值列[0], ascending=False).head(int(topN))

    # 阶段 30：同比环比——x 轴为日期字段的时间序列图（折线/柱状/面积）上追加对比列
    对比图表 = ("折线图", "柱状图", "面积图", "堆积柱状图")
    if 对比 in ("环比", "同比") and effective_chart in 对比图表 and x轴 in 画像.get("日期字段", []):
        report_df = _生成对比数据(report_df, 对比, x轴)

    plotly_type = 图表类型映射.get(effective_chart, "table")
    report_rows = _可_json行(report_df)
    chart_config: Dict[str, Any] = {
        "类型": plotly_type,
        "标题": 分析需求.strip() or f"上传数据{effective_chart}",
        "X轴": x轴 or (report_df.columns[0] if len(report_df.columns) else None),
        "Y轴": y轴列表,
        "颜色": 分组字段,
        "数据": report_rows,
        "筛选条件": 显式筛选,          # 供 replay 重放 / 前端回显（原始结构）
        "筛选说明": 筛选说明,          # 人读描述（界面展示/导出报告）
        "TopN": topN,
        "对比": 对比,
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

    推荐说明 = _生成推荐说明(画像, effective_chart, x轴, y轴列表, 分组字段, 聚合方式, 用户请求自动推荐, 分析需求)
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