# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】报表主链路的筛选/排名规则层：把"只看华东""Top 10"这类自然语言，变成能落到 DataFrame 上的过滤条件。
# ============================================================
# 【做了什么】
#   1. 应用筛选(df, 条件列表)：逐条 AND 语义过滤并产出人读描述列表；字段不存在 / 操作不在 筛选操作 枚举（9 种，与契约层、LLM schema 共用） / 值转型失败一律跳过不阻断。
#   2. _转换比较值：按目标列 dtype 转型（数值列→float，布尔列认 是/否/true/1/yes），转不了就按原样字符串比较，所以"销量大于 500"能命中。
#   3. 提取TopN：匹配 (?:[Tt]op|前|排名前)\s*(\d{1,3}) 并 clamp 到 1..200（与契约 topN 的 ge/le 一致）；刻意不匹配"最高/最多"——那是查询不是截断。
#   4. 匹配筛选条件：三条规则——显式"字段=值"（以真实列名为锚点，值尾部的"统计/分析/走势"等动词截掉）、"只看/仅看/只要/筛选出 X"、"排除/不含/剔除/去掉 X"；后两类靠 _值属于哪个字段 在分类字段前 500 个取值样本里双向子串命中。
# 【为什么这么做】
#   - 独立成模块而不是塞进 上传报表生成器.py：筛选被主链路、agent/executors.py（工具层摘要）与 field_selector 三处共用，放进生成器会让执行器与生成器互相 import 成环。
#   - 筛选放在生成链路的画像/聚合之前：先过滤再算画像，结论与图表口径才一致；放到前端过滤则大文件内存爆，且画像/结论仍按全量算，图表与结论会打架。
#   - 规则识别宁可漏也不错：值必须真的出现在分类字段取值样本里、且长度 ≥ 2 才参与双向包含；无 LLM key 时这是唯一可用路径，误伤会直接产出错误数据。
# 【关键约定与坑】
#   - 本模块只作用于内存 df，不碰连接与事务；调用方必须传入"未筛选的原始帧"——重算场景（refine_report 的"加筛选"）同理，作用于原始 df。
#   - 筛选操作 枚举三方共用，改动要同步契约层与 LLM schema，否则面板能选的值规则层不认（会被静默跳过，用户看不到报错）。
#   - 匹配筛选条件 返回的键固定为 字段/操作/值，与 应用筛选 的入参是同一契约，中途改名会让筛选静默失效。
#   - 常量 TOPN_排除图表（表格/直方/词云/热力/箱线/K线/瀑布/桑基/旭日/散点）指出这些图的 report_df 不是排名表，套 TopN 会得到无意义结果。
# ============================================================
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