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
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from 后端_核心.agent.工具集 import register_tool_executor
from 后端_核心.数据画像 import 生成数据画像 as _生成数据画像


def _可读画像摘要(画像: Dict[str, Any]) -> str:
    """把数据画像压缩成一段可读文本，供 LLM 查看。"""
    行数 = 画像.get("行数", 0)
    列数 = 画像.get("列数", 0)
    字段列表 = 画像.get("字段列表", [])
    数值字段 = 画像.get("数值字段", [])
    日期字段 = 画像.get("日期字段", [])
    分类字段 = 画像.get("分类字段", [])
    质量 = 画像.get("数据质量", {})
    return (
        f"数据集共 {行数} 行、{列数} 列。\n"
        f"字段列表：{', '.join(字段列表)}\n"
        f"数值字段：{', '.join(数值字段)}\n"
        f"日期字段：{', '.join(日期字段)}\n"
        f"分类字段：{', '.join(分类字段)}\n"
        f"数据质量评级：{质量.get('评级', '?')} - {质量.get('等级说明', '')}"
    )


def _获取数据画像_executor(arguments: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tool：获取数据画像摘要。"""
    画像 = context.get("画像")
    if not 画像:
        return None
    return {
        "摘要": _可读画像摘要(画像),
        "字段列表": 画像.get("字段列表", []),
    }


def _聚合分析_executor(arguments: Dict[str, Any], context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Tool：按 X/Y/分组/聚合方式执行数据聚合。"""
    df: Optional[pd.DataFrame] = context.get("df")
    画像: Optional[Dict[str, Any]] = context.get("画像")
    if df is None or 画像 is None:
        return None

    x轴 = arguments.get("X轴") or arguments.get("x轴")
    y轴列表 = arguments.get("Y轴") or arguments.get("y轴") or []
    分组字段 = arguments.get("分组字段")
    聚合方式 = arguments.get("聚合方式") or "求和"

    if isinstance(y轴列表, str):
        y轴列表 = [y轴列表]

    # 字段白名单校验
    可用字段 = set(画像.get("字段列表", []))
    if x轴 and x轴 not in 可用字段:
        return None
    y轴列表 = [f for f in y轴列表 if f in 可用字段]
    if 分组字段 and 分组字段 not in 可用字段:
        分组字段 = None

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
