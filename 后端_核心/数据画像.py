from __future__ import annotations

from typing import Any, Dict, List
import warnings

import pandas as pd
from pandas.api.types import is_datetime64_any_dtype, is_numeric_dtype


def _尝试日期列(series: pd.Series) -> bool:
    if is_datetime64_any_dtype(series):
        return True
    if series.dtype != object:
        return False
    sample = series.dropna().astype(str).head(50)
    if sample.empty:
        return False
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        parsed = pd.to_datetime(sample, errors="coerce")
    return parsed.notna().mean() >= 0.8


def _字段分组(df: pd.DataFrame) -> Dict[str, List[str]]:
    数值字段: List[str] = []
    日期字段: List[str] = []
    分类字段: List[str] = []
    文本字段: List[str] = []

    row_count = max(len(df), 1)
    for column in df.columns:
        series = df[column]
        non_null = series.dropna()
        unique_count = int(non_null.nunique()) if not non_null.empty else 0
        # 平均字符长度：用于区分「短枚举」（地区/渠道）与「长文本」（评论/备注，适合分词）
        avg_len = float(non_null.astype(str).str.len().mean()) if not non_null.empty else 0.0
        if is_numeric_dtype(series):
            数值字段.append(column)
        elif _尝试日期列(series):
            日期字段.append(column)
        elif unique_count <= min(30, max(10, int(row_count * 0.5))) and avg_len <= 6:
            分类字段.append(column)
        else:
            文本字段.append(column)

    return {
        "数值字段": 数值字段,
        "日期字段": 日期字段,
        "分类字段": 分类字段,
        "文本字段": 文本字段,
    }


def _数值摘要(df: pd.DataFrame, 数值字段: List[str]) -> Dict[str, Dict[str, Any]]:
    if not 数值字段:
        return {}
    describe = df[数值字段].describe().round(4)
    return {
        column: {stat: _可_json值(describe.loc[stat, column]) for stat in describe.index}
        for column in describe.columns
    }


def _分类摘要(df: pd.DataFrame, fields: List[str]) -> Dict[str, Dict[str, int]]:
    summary: Dict[str, Dict[str, int]] = {}
    for column in fields:
        value_counts = df[column].astype(str).value_counts(dropna=True).head(10)
        summary[column] = {str(index): int(value) for index, value in value_counts.items()}
    return summary


def _可_json值(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _生成字段建议(df: pd.DataFrame, 字段: Dict[str, List[str]]) -> List[Dict[str, str]]:
    建议: List[Dict[str, str]] = []
    if 字段["日期字段"]:
        建议.append({"字段": 字段["日期字段"][0], "角色": "X轴", "理由": "日期字段适合观察趋势变化，优先用于折线图 X 轴"})
    if 字段["数值字段"]:
        建议.append({"字段": 字段["数值字段"][0], "角色": "Y轴", "理由": "数值字段适合求和、平均值等聚合，优先用于指标 Y 轴"})
    if 字段["分类字段"]:
        建议.append({"字段": 字段["分类字段"][0], "角色": "分组", "理由": "分类字段适合做分组对比或柱状图 X 轴"})
    return 建议


def _生成数据质量(df: pd.DataFrame, 缺失值: Dict[str, int]) -> Dict[str, Any]:
    warnings: List[str] = []
    row_count = max(len(df), 1)
    # 超大表统计采样：duplicated()/nunique() 全表计算在 50MB 级数据上很慢
    stat_df = df.sample(n=50_000, random_state=42) if len(df) > 100_000 else df

    # ── A/B/C 分级 ──
    total_missing = sum(缺失值.values())
    missing_rate = total_missing / (row_count * max(len(df.columns), 1))

    constant_fields = [column for column in stat_df.columns if stat_df[column].nunique(dropna=True) <= 1]
    duplicate_count = int(stat_df.duplicated().sum())

    if missing_rate < 0.05 and not constant_fields:
        level = "A"
        level_label = "优秀"
    elif missing_rate < 0.20 and duplicate_count < row_count * 0.1:
        level = "B"
        level_label = "良好"
    else:
        level = "C"
        level_label = "需关注"

    missing_fields = [f"{column}（{count / row_count:.0%}）" for column, count in 缺失值.items() if count]
    if missing_fields:
        warnings.append(f"存在缺失值：{ '、'.join(missing_fields[:5]) }")
    if duplicate_count:
        warnings.append(f"发现 {duplicate_count} 行完全重复记录")
    if constant_fields:
        warnings.append(f"字段无有效变化，可能不适合分析：{ '、'.join(constant_fields[:5]) }")

    # ── 等级说明 ──
    等级说明 = {
        "A": "数据质量优秀，缺失率 < 5%，无重复行，无异常字段",
        "B": "数据质量良好，缺失率 5%~20%，少量异常",
        "C": "数据质量较差，缺失率 > 20% 或存在结构异常，建议清洗后再分析",
    }

    return {
        "重复行数": duplicate_count,
        "缺失字段": missing_fields,
        "提示": warnings,
        "等级": level_label,
        "评级": level,
        "等级说明": 等级说明.get(level, ""),
        "缺失率": round(missing_rate * 100, 2),
    }


def 生成数据画像(df: pd.DataFrame) -> Dict[str, Any]:
    """生成上传数据的字段类型、缺失值、质量提示和基础统计摘要。"""
    字段 = _字段分组(df)
    缺失值 = {column: int(df[column].isna().sum()) for column in df.columns}
    字段类型 = {column: str(df[column].dtype) for column in df.columns}
    分类候选 = 字段["分类字段"] + 字段["日期字段"]

    return {
        "行数": int(len(df)),
        "列数": int(len(df.columns)),
        "字段列表": list(df.columns),
        "字段类型": 字段类型,
        "缺失值": 缺失值,
        "总缺失值": int(sum(缺失值.values())),
        **字段,
        "字段建议": _生成字段建议(df, 字段),
        "数据质量": _生成数据质量(df, 缺失值),
        "数值摘要": _数值摘要(df, 字段["数值字段"]),
        "分类摘要": _分类摘要(df, 分类候选[:12]),
    }
