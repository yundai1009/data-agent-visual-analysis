"""数据清洗：去重、填充缺失、删除空行。

设计决策
========
- 不修改原始数据集，清洗后生成新版本（浅拷贝）
- 默认分析时自动忽略缺失行（不删除），仅在明确请求时才做清洗
- 清洗操作可组合：去重 + 填充 + 删空行，按顺序执行

可选方向
========
1. 原地修改（mutate）→ 选否。风险高，用户误操作无法恢复
2. **浅拷贝 + 只读清洗** → 选了。清洗后返回新 DataFrame 和修改摘要
3. SQL 级清洗 → 不选。增加复杂度，且 pandas 已覆盖全部场景
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd


def 清洗数据集(
    df: pd.DataFrame,
    *,
    deduplicate: bool = False,
    fill_missing: bool = False,
    fill_strategy: str = "auto",
    drop_empty_rows: bool = False,
    drop_empty_columns: bool = False,
) -> Dict[str, Any]:
    """对 DataFrame 执行清洗操作，返回清洗结果与操作摘要。

    Args:
        df: 原始 DataFrame（不会被修改）
        deduplicate: 是否去重
        fill_missing: 是否填充缺失值
        fill_strategy: 填充策略（auto/mean/median/mode/zero）
        drop_empty_rows: 是否删除全空行
        drop_empty_columns: 是否删除全空列

    Returns:
        {
            "清洗后数据": pd.DataFrame,
            "操作摘要": {
                "去重": {"执行": True, "删除行数": 5},
                "填充缺失": {"执行": True, "策略": "auto", "填充列数": 2},
                "删除空行": {"执行": True, "删除行数": 1},
            }
        }
    """
    result = df.copy()
    摘要: Dict[str, Any] = {}

    # 1. 去重
    if deduplicate:
        before = len(result)
        result = result.drop_duplicates()
        摘要["去重"] = {"执行": True, "删除行数": before - len(result)}

    # 2. 填充缺失
    if fill_missing:
        # 策略白名单校验：非法策略直接拒绝，避免"静默不填充却记录执行成功"
        if fill_strategy not in ("auto", "mean", "median", "mode", "zero"):
            raise ValueError(f"不支持的填充策略：{fill_strategy}（可选 auto/mean/median/mode/zero）")
        filled_columns = []
        for column in result.columns:
            if result[column].isna().sum() > 0:
                if fill_strategy == "auto":
                    if pd.api.types.is_numeric_dtype(result[column]):
                        result[column] = result[column].fillna(result[column].median())
                    else:
                        mode_val = result[column].mode()
                        result[column] = result[column].fillna(mode_val.iloc[0] if not mode_val.empty else "未知")
                elif fill_strategy == "mean" and pd.api.types.is_numeric_dtype(result[column]):
                    result[column] = result[column].fillna(result[column].mean())
                elif fill_strategy == "median" and pd.api.types.is_numeric_dtype(result[column]):
                    result[column] = result[column].fillna(result[column].median())
                elif fill_strategy == "mode":
                    mode_val = result[column].mode()
                    result[column] = result[column].fillna(mode_val.iloc[0] if not mode_val.empty else "未知")
                elif fill_strategy == "zero":
                    result[column] = result[column].fillna(0 if pd.api.types.is_numeric_dtype(result[column]) else "")
                filled_columns.append(column)
        摘要["填充缺失"] = {"执行": True, "策略": fill_strategy, "填充列数": len(filled_columns)}

    # 3. 删除全空行
    if drop_empty_rows:
        before = len(result)
        result = result.dropna(how="all")
        摘要["删除空行"] = {"执行": True, "删除行数": before - len(result)}

    # 4. 删除全空列
    if drop_empty_columns:
        before = len(result.columns)
        result = result.dropna(axis=1, how="all")
        摘要["删除空列"] = {"执行": True, "删除列数": before - len(result.columns)}

    return {
        "清洗后数据": result,
        "操作摘要": 摘要,
    }
