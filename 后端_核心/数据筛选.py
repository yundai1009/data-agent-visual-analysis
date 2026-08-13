# -*- coding: utf-8 -*-
"""数据筛选模块（阶段 29 · 条件筛选 + TopN）

这个文件管什么：
    给"生成报表数据"主链路提供三类能力：
      1. 应用筛选条件（AND 语义）——把 DataFrame 过滤到用户想要的子集，
         再走画像/聚合/结论全链路（画像反映筛选后数据，结论才有意义）；
      2. 提取 TopN —— 从需求文本里识别"Top 10 / 前10 / 排名前5"这类排名意图；
      3. 规则层自然语言筛选识别 —— 无 LLM key 也能听懂"只看华东区"、
         "排除华南区"、"地区=华东"这类话。

为什么单独放一个文件：
    筛选逻辑同时被三条链路使用——上传报表生成器（主链路）、
    Agent 执行器注册（工具层摘要）、未来可能有其他调用方；
    放独立模块避免"执行器注册 ↔ 上传报表生成器"互相 import 成环。

删除它会怎样：
    筛选/排名能力全部失效，用户只能看全量数据聚合，
    "只看华东区"这类需求只能靠 LLM 且必须带 key。

替代方案：
    筛选只在前端做（前端过滤后上传子集）——数据量大时前端内存爆、
    且画像/结论仍按全量算，结论与图表不一致；当前方案最一致。
"""
import re
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

# 合法操作清单（契约层/LLM schema/规则层共用同一套枚举）
筛选操作 = ("等于", "不等于", "包含", "大于", "大于等于", "小于", "小于等于", "为空", "不为空")

# TopN 不适用的图表（它们的 report_df 不是"按 X 聚合的排名表"）
TOPN_排除图表 = {"表格", "直方图", "词云图", "热力图", "箱线图", "K线图",
               "瀑布图", "桑基图", "旭日图", "散点图"}


def 应用筛选(
    df: pd.DataFrame,
    筛选条件列表: Optional[List[Dict[str, Any]]],
) -> Tuple[pd.DataFrame, List[str]]:
    """逐条应用筛选条件（AND 语义），返回 (过滤后 df, 人读描述列表)。

    容错策略：
      - 字段不在 df 中 / 操作不合法 → 跳过该条（不阻断整体）；
      - 值按目标列 dtype 自动转型（数值列转 float、布尔列转 True/False），
        转不了就按字符串比较——保证"销量大于 500"这类需求可用。
    描述列表用于界面展示与报告说明（如 ["地区 等于 华东区"]）。
    """
    if not 筛选条件列表:
        return df, []
    result_df = df
    descriptions: List[str] = []
    for cond in 筛选条件列表:
        if not isinstance(cond, dict):
            continue
        字段 = str(cond.get("字段") or "").strip()
        操作 = str(cond.get("操作") or "").strip()
        值 = cond.get("值")
        if not 字段 or 字段 not in result_df.columns or 操作 not in 筛选操作:
            continue
        列 = result_df[字段]
        try:
            if 操作 == "为空":
                mask = 列.isna()
            elif 操作 == "不为空":
                mask = 列.notna()
            else:
                v = _转换比较值(列, 值)
                if 操作 == "等于":
                    mask = 列 == v
                elif 操作 == "不等于":
                    mask = 列 != v
                elif 操作 == "包含":
                    mask = 列.astype(str).str.contains(str(v), na=False, regex=False)
                elif 操作 == "大于":
                    mask = 列 > v
                elif 操作 == "大于等于":
                    mask = 列 >= v
                elif 操作 == "小于":
                    mask = 列 < v
                elif 操作 == "小于等于":
                    mask = 列 <= v
                else:
                    continue
            result_df = result_df[mask]
            descriptions.append(f"{字段} {操作} {值}" if 操作 not in ("为空", "不为空") else f"{字段} {操作}")
        except (TypeError, ValueError):
            continue
    return result_df, descriptions


def _转换比较值(列: pd.Series, 值: Any) -> Any:
    """把用户给的字符串值转成与列可比对的类型（数值/布尔），转不了原样返回。"""
    if 值 is None:
        return None
    if pd.api.types.is_numeric_dtype(列):
        try:
            return float(值)
        except (ValueError, TypeError):
            return 值
    if pd.api.types.is_bool_dtype(列):
        if str(值).strip().lower() in ("是", "true", "1", "yes"):
            return True
        if str(值).strip().lower() in ("否", "false", "0", "no"):
            return False
        return 值
    return 值


def 提取TopN(文本: str) -> Optional[int]:
    """从需求文本提取排名数量："Top 10"/"前10"/"排名前 5"，无则 None。

    刻意不匹配"最高/最多"——"销量最高的是哪个"是查询不是排名截断。
    上限 200 与契约 topN 的 ge/le 一致（防超大值 head 全表无意义）。
    """
    m = re.search(r"(?:[Tt]op|前|排名前)\s*(\d{1,3})", 文本 or "")
    if not m:
        return None
    return max(1, min(int(m.group(1)), 200))


def 匹配筛选条件(文本: str, df: pd.DataFrame, 画像: Dict[str, Any]) -> List[Dict[str, Any]]:
    """规则层自然语言筛选识别（LLM 不可用时的兜底，保守策略避免误伤）。

    支持三种说法：
      1. 显式"字段=值"：  "地区=华东" → 等于（字段名必须是真实列名，防"按"等字误吞）
      2. "只看X/仅X/只要X"：X 命中某分类字段的取值样本（样本是 X 的一部分，
         或 X 是样本的一部分）→ 等于
      3. "排除X/不含X/去掉X"：同上命中 → 不等于
    命中判定要求值真的出现在数据里，防止"只看趋势"这种非值的短语误触发。
    """
    if not 文本:
        return []
    条件列表: List[Dict[str, Any]] = []

    # 1) 显式 字段=值：以真实列名为锚点（避免"按地区=华东"把"按"吞进字段名），
    #    值末尾的常见动词（统计/分析等）截掉，只留真正的筛选值
    for 字段 in df.columns:
        m = re.search(re.escape(字段) + r"\s*[=＝]\s*([^\s,，。；;]+)", 文本)
        if not m:
            continue
        值 = re.sub(r"(统计|分析|对比|查看|排序|筛选|比较|情况|走势|趋势)$", "", m.group(1).strip())
        if 值:
            条件列表.append({"字段": 字段, "操作": "等于", "值": 值})

    # 2) 只看 / 排除 短语 → 值命中分类字段样本
    for pattern, 操作 in ((r"(?:只看|仅看|只要|筛选出)\s*([^\s,，。；;]+)", "等于"),
                          (r"(?:排除|不含|剔除|去掉)\s*([^\s,，。；;]+)", "不等于")):
        m = re.search(pattern, 文本)
        if not m:
            continue
        目标 = m.group(1).strip()
        if not 目标:
            continue
        命中 = _值属于哪个字段(目标, df, 画像)
        if 命中:
            字段, 值 = 命中
            条件列表.append({"字段": 字段, "操作": 操作, "值": 值})
    return 条件列表


def _值属于哪个字段(目标: str, df: pd.DataFrame, 画像: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """在分类字段的取值样本里找 target（双向包含：样本==目标 / 目标含样本 / 样本含目标）。

    双向包含的动机：数据里存的是"华东"（省），用户口语说"只看华东区"（省+区），
    需要"样本是输入的一部分"也能命中；反向（目标在样本里）兜底别名场景。
    保守性：目标长度 >= 2 才参与包含匹配，避免"只看A"这种单字误触发。
    """
    分类字段 = 画像.get("分类字段") or [
        f for f in df.columns if pd.api.types.is_object_dtype(df[f])
    ]
    for 字段 in 分类字段:
        if 字段 not in df.columns:
            continue
        try:
            样本 = df[字段].dropna().astype(str).unique()[:500]
        except (TypeError, ValueError):
            continue
        for s in 样本:
            if s == 目标 or (len(目标) >= 2 and 目标 in s) or (len(s) >= 2 and s in 目标):
                return 字段, s
    return None