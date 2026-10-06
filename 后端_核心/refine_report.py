# -*- coding: utf-8 -*-
"""阶段 55 · 报表图表局部精细化编辑服务。

设计定位（见 docs/superpowers/specs/2026-10-06-图表局部精细化编辑-design.md）：
对已生成报表做图表层局部修改，**不重新执行 Agent ReAct、不调用外部工具/LLM**，
仅复用报表关联数据集的 parquet + 已有画像做本地 pandas 重算，另存新报表。
"""
import re
from typing import Dict, List, Optional


# ---- 标识符/编码字段识别（约束 2 基石） ------------------------------------
# 标识符/编码 ID 类字段严禁作 Y 轴/数值度量，仅可作分类 X 轴。
# 识别规则：
#   1. 字段名命中 id/ID/编号/编码/code/序号/单号/号码/uuid/标识/键 等模式；
#   2. 高基数数值字段（唯一值数 ≈ 行数，如 user_id/score 类用户级 ID）。
_ID名称模式 = re.compile(
    r"(id|编号|编码|code|序号|单号|号码|代码|uuid|标识|键)$|^id[_]?",
    re.IGNORECASE,
)


def 标识符字段(画像: Dict) -> List[str]:
    """识别标识符/编码字段。命中的字段禁作 Y 轴/数值度量，仅可作 X 轴。

    规则：
    1. 字段名命中 ``_ID名称模式``；
    2. 画像提供 ``唯一值数`` 时，高基数数值字段（唯一值数 übige 行数，如
       user_id 类 9000/9000）视为标识符。
    """
    行数 = int(画像.get("行数") or 0) or 1
    唯一值数 = 画像.get("唯一值数") or {}
    结果: List[str] = []
    已见 = set()

    def _加(field: str) -> None:
        if field not in 已见:
            已见.add(field)
            结果.append(field)

    for field in 画像.get("字段列表", []) or []:
        if _ID名称模式.search(str(field)):
            _加(field)
            continue
        # 高基数数值标识符：唯一值数 ≈ 行数（≥95% 且绝对数足够大）
        uniq = 唯一值数.get(field)
        if isinstance(uniq, (int, float)) and uniq >= max(10, int(行数 * 0.95)):
            _加(field)
    return 结果