"""Tool 执行器注册：把已有能力包装为可被 LLM 调用的 Tool。

每个执行器函数签名：executor(arguments: dict, context: dict) -> dict
- arguments：LLM 通过 tool_call 传入的参数
- context：编排器注入的上下文（画像、df、trace 等）
- 返回值：结构化的摘要文本 + 数据，失败返回 None

设计决策
========
- 不重复造轮子，直接调用 上传报表生成器.py 中已有函数
- 执行器只返回文本摘要和结构化配置，不返回完整 DataFrame（防 trace 爆炸）
- 字段白名单校验在编排器中统一做，执行器假设入参已校验

═══════════════════════════════════════════════════════════════
【文件总览】项目层级与调用关系
═══════════════════════════════════════════════════════════════
- 所在目录：后端_核心/agent/
- 被谁调用：
  · 编排器.py 启动时 → 注册所有执行器()（把 4 个执行函数注入到全局 TOOL_EXECUTORS 字典）
  · 工具集.py execute_tool() → 通过 name 查表找到对应的执行函数并调用
- 调用了谁：
  · 工具集.py        → register_tool_executor()（注册函数）
  · 数据画像.py      → 生成数据画像()（数据画像执行器内部不调用，但画像在 context 里）
  · pandas           → 聚合计算（groupby/agg/pivot_table 等）
- 本文件负责：
  1. 实现 4 个 Tool 的后端执行逻辑（获取画像 / 聚合分析 / 推荐图表 / 生成结论）
  2. 每个执行器内部做字段白名单校验（防御 LLM 幻觉出不存在的字段名）
  3. 把执行结果压缩为文本摘要返回给 LLM，不返回原始 DataFrame（控制 token + 防数据泄漏）
- 面试要点：这是"LLM 决策 + 后端执行"架构里真正执行计算的地方；
  LLM 只能在这 4 个工具里选，参数再经过白名单校验才能运行，安全边界清晰。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from 后端_核心.agent.工具集 import register_tool_executor
from 后端_核心.数据画像 import 生成数据画像 as _生成数据画像


def _可读画像摘要(画像: Dict[str, Any], df=None) -> str:
    """把数据画像压缩成一段可读文本，供 LLM 查看。

    作用：ReAct 第 1 轮「获取数据画像」工具的输出——把画像 dict 翻译成人话。

    关键：除字段名/类型外，附上每字段前几个真实示例值——
    LLM 结合"字段名 + 示例值"才能准确理解字段语义（如"工作时间: 8,10,6"
    明确是时长度量），从而任意自然语言都能选对字段。

    入参：
      - 画像：数据画像 dict（字段列表/数值字段/日期字段/分类字段/数据质量）
      - df：可选，原始 DataFrame；提供时给每个字段附前 3 个真实示例值
    返回：
      - str：多行文本摘要，如"数据集共 100 行、5 列。字段列表：…"
    业务定位：LLM 的"眼睛"——没有这份摘要，LLM 面对陌生数据集将无从决策。
    """
    行数 = 画像.get("行数", 0)
    列数 = 画像.get("列数", 0)
    字段列表 = 画像.get("字段列表", [])
    数值字段 = 画像.get("数值字段", [])
    日期字段 = 画像.get("日期字段", [])
    分类字段 = 画像.get("分类字段", [])
    质量 = 画像.get("数据质量", {})
    lines = [
        f"数据集共 {行数} 行、{列数} 列。",
        f"字段列表：{', '.join(字段列表)}",
        f"数值字段：{', '.join(数值字段)}",
        f"日期字段：{', '.join(日期字段)}",
        f"分类字段：{', '.join(分类字段)}",
        f"数据质量评级：{质量.get('评级', '?')} - {质量.get('等级说明', '')}",
    ]
    # 每字段真实示例值（前 3 个非空），帮 LLM 理解字段语义
    if df is not None and not df.empty:
        sample_lines = []
        for field in 字段列表:
            if field not in df.columns:
                continue
            samples = [str(v) for v in df[field].dropna().head(3).tolist()]
            if samples:
                sample_lines.append(f"{field}: {', '.join(samples)}")
        if sample_lines:
            lines.append("字段示例值（帮助理解语义，非完整数据）：")
            lines.append(" | ".join(sample_lines))
    return "\n".join(lines)


def _获取数据画像_executor(arguments: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tool：获取数据画像摘要。"""
    画像 = context.get("画像")
    if not 画像:
        return None
    return {
        "摘要": _可读画像摘要(画像, df=context.get("df")),
        "字段列表": 画像.get("字段列表", []),
    }


def _聚合分析_executor(arguments: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tool：按 X/Y/分组/聚合方式执行数据聚合。

    作用：ReAct 第 2 轮的核心工具——根据 LLM 填的字段参数对 DataFrame 做分组聚合，
    把聚合结果压缩成文本摘要返回给 LLM 作为"观察"。

    入参：
      - arguments：LLM 传来的参数（X轴/Y轴/分组字段/聚合方式）
      - context：编排器注入的上下文（画像、df），这里真正读数据
    返回：
      - 成功：{"数据摘要": 聚合结果文本, "聚合方式", "行数", "字段"}
      - 失败/参数非法：None（触发上层降级）
    业务定位：唯一真正操作 df 的执行器——LLM 的"计算请求"在这里落地为 pandas 聚合。
    """
    df: Optional[pd.DataFrame] = context.get("df")
    画像: Optional[Dict[str, Any]] = context.get("画像")
    if df is None or 画像 is None:
        return None

    x轴 = arguments.get("X轴") or arguments.get("x轴")
    y轴列表 = arguments.get("Y轴") or arguments.get("y轴") or []
    分组字段 = arguments.get("分组字段")
    聚合方式 = arguments.get("聚合方式") or "求和"
    筛选条件 = arguments.get("筛选条件") or []

    # 阶段 34 修复（Bug2）：GLM-4-Flash 等模型把单值参数返回为数组（如
    # X轴=["地区"]），list 直接参与 set 成员判断会抛 unhashable type。
    # 对 x轴/分组字段 做 list→str 归一化（y轴列表 本来就是列表语义）。
    if isinstance(x轴, list):
        x轴 = x轴[0] if x轴 else None
    if isinstance(分组字段, list):
        分组字段 = 分组字段[0] if 分组字段 else None

    if isinstance(y轴列表, str):
        y轴列表 = [y轴列表]

    # 字段白名单校验
    可用字段 = set(画像.get("字段列表", []))
    if x轴 and x轴 not in 可用字段:
        return None
    y轴列表 = [f for f in y轴列表 if f in 可用字段]
    if 分组字段 and 分组字段 not in 可用字段:
        分组字段 = None

    # 阶段 29：工具层也应用筛选——LLM 观察到的聚合摘要必须反映筛选后的数据，
    # 否则"只看华东区"的 LLM 会基于全量摘要做错误推断。
    筛选条件 = [f for f in 筛选条件 if isinstance(f, dict) and f.get("字段") in 可用字段]
    if 筛选条件:
        from 后端_核心.数据筛选 import 应用筛选
        df, _ = 应用筛选(df, 筛选条件)
        if df.empty:
            return {"数据摘要": "筛选后没有数据（请检查筛选条件）", "行数": 0, "字段": []}

    if not x轴 or x轴 not in df.columns:
        return {"数据摘要": f"数据集前 5 行：\n{df.head().to_string()}", "行数": len(df)}

    group_fields = [x轴]
    if 分组字段 and 分组字段 in df.columns and 分组字段 != x轴:
        group_fields.append(分组字段)

    if 聚合方式 in ("计数", "count"):
        grouped = df.groupby(group_fields, dropna=False).size().reset_index(name="记录数")
        grouped = grouped.sort_values(group_fields).head(20)
    else:
        聚合映射 = {"求和": "sum", "平均值": "mean", "计数": "count", "最大值": "max", "最小值": "min"}
        agg = 聚合映射.get(聚合方式, "sum")
        valid_y = [f for f in y轴列表 if f in df.columns]
        if not valid_y:
            return {"数据摘要": "无有效的 Y 轴字段", "行数": 0}
        grouped = df.groupby(group_fields, dropna=False)[valid_y].agg(agg).reset_index()
        grouped = grouped.sort_values(group_fields).head(20)

    数据摘要 = f"聚合方式：{聚合方式}，返回 {len(grouped)} 行\n"
    for _, row in grouped.iterrows():
        items = [f"{col}: {_可读值(row[col])}" for col in grouped.columns]
        数据摘要 += "  " + ", ".join(items) + "\n"

    return {
        "数据摘要": 数据摘要,
        "聚合方式": 聚合方式,
        "行数": len(grouped),
        "字段": list(grouped.columns),
    }


def _推荐图表_executor(arguments: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tool：根据聚合结果和画像推荐图表类型。"""
    画像: Optional[Dict[str, Any]] = context.get("画像")
    if not 画像:
        return None
    图表类型 = arguments.get("图表类型", "自动推荐")
    理由 = arguments.get("理由", "")
    return {
        "推荐图表": 图表类型,
        "理由": 理由,
    }


def _生成结论_executor(arguments: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tool：生成 Markdown 分析结论。"""
    结论 = arguments.get("结论", "")
    if not 结论:
        return None
    return {"结论": 结论[:800]}


def _可读值(value: Any) -> str:
    if value is None:
        return "无"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


# ── 批量注册 ──

def 注册所有执行器() -> None:
    """编排器启动时调用一次，把所有 Tool executor 注册到全局 TOOL_EXECUTORS。"""
    register_tool_executor("获取数据画像", _获取数据画像_executor)
    register_tool_executor("聚合分析", _聚合分析_executor)
    register_tool_executor("推荐图表", _推荐图表_executor)
    register_tool_executor("生成结论", _生成结论_executor)
