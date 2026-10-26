"""阶段七十一：多数据集对比分析（跨文件对比核心）。

一句话定位：把多份结构相似的数据集沿「来源轴」对齐，透视成可比宽表，
算出变化/差异并按轴类型给出结论——产出仍是一份普通报表（长表 + 图表配置），
前端报表页零改动即可渲染。

三轴模型（用户上传多份文件后要说清"谁跟谁比"）：

- **来源轴**（谁跟谁比）：1月/2月/3月、华东/华南/华北、线上/线下、改造前/改造后
- **主体轴**（比哪些对象）：地区、产品、渠道、门店（数据集之间的共同分类列）
- **指标**（比什么数值）：销售额、销量、订单数（数据集之间的共同数值列）

来源轴的推导优先级（`解析来源轴`）：
① 用户手动给的 `对比标签`（最可信，人工指定）
② 数据集内**恒定型列**（该列在每个数据集里只有一个取值，且各数据集取值不同）
   —— 支持"按地区分文件"这类需求（用户 2026-10-19 补充：「月份只是举的例子，
   还可能有地区之类的」）
③ 文件名推导（去扩展名 + 自然排序，`1月 < 2月 < 10月`）

对比轴类型决定表述口径（`判定对比轴类型`）：
- 时间型（1月/2024-01/一季度/2024年）→ 变化量 + 变化率，结论写"从 X 增至 Y，+27.0%"
- 类别型（华东/华南/线上）→ 差值 + 倍数 + 排名，不编造"变化率"（无周期概念）

本模块是纯函数：只吃已读好的 DataFrame，不碰数据库、不写文件；
唯一的外部调用是可选的大模型结论解读（`llm_config` 为 None 或未配置时走模板）。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from 后端_核心.data_filter import 应用筛选
# 复用 report_generator 的既有口径，避免两套聚合/JSON 序列化语义漂移
# （refine_report.py:236 已有引用同类私有函数的先例）
from 后端_核心.report_generator import 聚合映射, 图表类型映射, _可_json行, _生成HTML报告

# ── 对外契约常量（API/前端/测试都按这些字符串取值）──────────────────────────
列_来源 = "来源"
列_变化量 = "变化量"
列_变化率 = "变化率"
列_差值 = "差值"
列_倍数 = "倍数"
列_排名 = "排名"
列_主体 = "主体"

轴类型时间 = "时间型"
轴类型类别 = "类别型"

# 对比结果可用的图表类型白名单：
# 前端 EChartsChart.jsx:349-369 只有 stacked_bar/bar 消费 groupField（颜色）画多系列，
# pie/donut（:257-）与 line（:295-307）都只认单列，会把来源轴丢掉 → 一律不放进白名单。
对比图表白名单 = ("自动推荐", "堆积柱状图", "柱状图", "表格")
默认对比图表 = "堆积柱状图"

# 主体轴基数区间：1 是恒定列（多半是来源轴），>50 更像 ID/自由文本，做行维度无意义
主体轴基数下限 = 2
主体轴基数上限 = 50

# 一次对比允许的数据集数量上限（与 api/contracts.py 的 min/max_length 呼应）
最小数据集数 = 2
最大数据集数 = 10

# 数据集总行数上限（与 /datasets/merge 的 50 万行口径一致）
最大总行数 = 500_000


# ═══════════════════════════════════════════════════════════════
# 一、标签与轴类型：来源轴是时间还是类别
# ═══════════════════════════════════════════════════════════════

# 时间型标签的常见写法（余地留够：中文月/季度/年、ISO 年月、纯年份）
_时间标签模式 = re.compile(
    r"^\s*(?:"
    r"(?P<年>\d{4})\s*(?:年|[-/.])\s*(?P<月>\d{1,2})\s*(?:月|[-/.]\s*\d{1,2}\s*日?)?"
    r"|(?P<月单>\d{1,2})\s*月份?"
    r"|(?:第?\s*)?(?P<季>[1-4一二三四])\s*季度?"
    r"|(?P<年单>\d{4})\s*年?"
    r")\s*$"
)

_中文数字 = {"一": 1, "二": 2, "三": 3, "四": 4}

# 无主体轴时（整体合计对比）对外统一用的主体名（长表/明细/宽表都用它）
主体_全部 = "（全部）"


def _解析时间序(标签: str) -> Optional[Tuple[int, int]]:
    """把时间型标签解析成 (年, 月) 可排序序对；解析不出来返回 None。

    年缺失时用 0 占位（"1月" 与 "2月" 仍能相互比较），季度折算成月中
    （Q1→3月、Q2→6月……）以便和月份混排。
    """
    文本 = str(标签 or "").strip()
    if not 文本:
        return None
    匹配 = _时间标签模式.match(文本)
    if not 匹配:
        return None
    季度 = 匹配.group("季")
    if 季度:
        序 = _中文数字.get(季度) or int(季度)
        return (0, 序 * 3)
    if 匹配.group("年"):
        年, 月 = int(匹配.group("年")), int(匹配.group("月"))
        if not 1 <= 月 <= 12:
            return None
        return (年, 月)
    if 匹配.group("月单"):
        月 = int(匹配.group("月单"))
        return (0, 月) if 1 <= 月 <= 12 else None
    if 匹配.group("年单"):
        return (int(匹配.group("年单")), 0)
    return None


def 判定对比轴类型(标签列表: Sequence[str]) -> str:
    """来源轴是时间型还是类别型——决定用"变化率"还是"倍数+排名"表述。

    只要有一个标签解析不出时间序就判类别型（宁可保守：类别型不编造变化率）。
    """
    有效 = [str(x).strip() for x in (标签列表 or []) if str(x).strip()]
    if len(有效) < 2:
        return 轴类型类别
    if all(_解析时间序(标签) is not None for 标签 in 有效):
        return 轴类型时间
    return 轴类型类别


def 自然排序键(文本: str) -> Tuple:
    """自然排序键：数字段按数值比，其余按字符串比（`1月 < 2月 < 10月`）。

    每段统一成 (0|1, 值)：0=数字段、1=字符串段，保证不同位置不混型比较。
    """
    片段: List[Tuple[int, Any]] = []
    for 段 in re.split(r"(\d+)", str(文本 or "")):
        if 段 == "":
            continue
        片段.append((0, int(段)) if 段.isdigit() else (1, 段))
    return tuple(片段)


def 对比标签顺序(标签列表: Sequence[str]) -> List[int]:
    """把标签排成对比顺序所需的**原始下标**（阶段七十二补）。

    为什么要有它：「标签排序」从来不是终点——标签是挂在数据集上的，标签一换位置，
    对应的数据行必须跟着换。只排标签不排数据，就会出现「1月」显示 10月 的数字。
    这里返回下标而不是排好的标签，调用方才能用同一份顺序同时重排标签和数据集。
    """
    列表 = [str(x) for x in (标签列表 or [])]
    if 判定对比轴类型(列表) == 轴类型时间:
        return sorted(range(len(列表)),
                      key=lambda 序: (_解析时间序(列表[序]) or (0, 0), 自然排序键(列表[序])))
    return sorted(range(len(列表)), key=lambda 序: 自然排序键(列表[序]))


def 排序对比标签(标签列表: Sequence[str]) -> List[str]:
    """按来源轴类型给标签定序：时间型按时间序，类别型按自然序。"""
    列表 = [str(x) for x in (标签列表 or [])]
    return [列表[序] for 序 in 对比标签顺序(列表)]


def 推导来源标签(名称列表: Sequence[str]) -> List[str]:
    """文件名 → 来源标签：去扩展名、去空、保序去重（不做自然排序，调用方按需排）。"""
    结果: List[str] = []
    for 名称 in 名称列表 or []:
        文本 = re.split(r"[\\/]", str(名称 or ""))[-1]
        文本 = re.sub(r"\.(csv|xlsx|xls|json|tsv|txt)$", "", 文本, flags=re.IGNORECASE).strip()
        if not 文本:
            continue
        if 文本 in 结果:
            continue
        结果.append(文本)
    return 结果


# ═══════════════════════════════════════════════════════════════
# 二、结构解析：共同字段 / 来源轴 / 主体轴 / 指标
# ═══════════════════════════════════════════════════════════════

# 列名语义别名：业务上指同一件事但写法不同（避免「销售额」/「销售金额」这种对齐失败）
_列名别名组: List[List[str]] = [
    ["销售额", "销售金额", "销售总额", "成交额", "GMV"],
    ["销量", "销售量", "销量额", "销售数量"],
    ["订单数", "订单量", "订单个数"],
    ["利润", "净利润", "毛利"],
    ["地区", "区域", "城市", "省份", "大区"],
    ["日期", "时间", "月份", "年份", "下单日期"],
]


def _列名归一(列名: str) -> str:
    """把列名归一到它的别名组代表（首组长串），无别名则原样返回。

    用于「共同字段」判定：销售额 / 销售金额 应视为同一列。
    """
    原名 = str(列名).strip()
    for 组 in _列名别名组:
        if 原名 in 组:
            return 组[0]
    return 原名


def _共同字段(数据列表: Sequence[pd.DataFrame]) -> List[str]:
    """所有数据集都有的列名（保持第一个数据集的列顺序）。

    2026-10-26 增强：先按语义别名归一再求交集，使「销售额」/「销售金额」这类
    写法不同的同义列也能对齐（D2）。归一只影响「是否算共同字段」的判定，
    返回仍用第一个数据集里的原始列名，下游取数不丢真实列名。
    """
    if not 数据列表:
        return []
    原始列 = [str(c) for c in 数据列表[0].columns]
    归一集合0 = {_列名归一(c) for c in 原始列}
    共同归一 = set(归一集合0)
    for df in 数据列表[1:]:
        共同归一 &= {_列名归一(str(c)) for c in df.columns}
    return [c for c in 原始列 if _列名归一(c) in 共同归一]


def _全数值列(数据列表: Sequence[pd.DataFrame], 列: str) -> bool:
    for df in 数据列表:
        实际 = _解析实际列名(df, 列)
        if 实际 is None:
            return False
        系列 = df[实际]
        if not pd.api.types.is_numeric_dtype(系列):
            return False
        if pd.api.types.is_bool_dtype(系列):
            return False
    return True


def _像时间列(系列: pd.Series) -> bool:
    """该列取值整体像时间（日期"主体轴"= 时间，不能当"比哪些对象"）。"""
    样本 = [str(v).strip() for v in 系列.dropna().astype(str).unique()[:20]]
    if len(样本) < 2:
        return False
    return all(_解析时间序(样本值) is not None for 样本值 in 样本)


def _恒定型列识别(
    数据列表: Sequence[pd.DataFrame],
    列: str,
    允许数值: bool = False,
) -> Optional[List[str]]:
    """判断某列是否为"来源轴候选"：每个数据集内只有一个非空取值，且各集取值不全相同。

    返回按数据集顺序的取值列表；不满足返回 None。
    —— 这是"按地区分文件"场景的核心：华东.csv 里 地区 列全是"华东"。
    风险防护：
    - 像"公司名称"这种单一取值、各集又都一样的列，去重后只有 1 个值 → 不算来源轴；
    - **自动识别时数值列一律不算**：单行数据集会让"销售额"这种度量列也满足 nunique<=1，
      误判成来源轴（回归用例 `test_数值列不被误判为来源轴` 就是这么暴露的）。
      数值型来源列（如整数月份）只允许用户通过 `来源轴` 显式指定（允许数值=True）。
    """
    取值列表: List[str] = []
    for df in 数据列表:
        if 列 not in df.columns:
            return None
        系列 = df[列]
        if not 允许数值 and (
            pd.api.types.is_numeric_dtype(系列) or pd.api.types.is_bool_dtype(系列)
        ):
            return None
        唯一 = pd.unique(系列.dropna())
        if len(唯一) > 1:
            return None
        取值列表.append(str(唯一[0]).strip() if len(唯一) == 1 else "")
    if any(值 == "" for 值 in 取值列表):
        return None
    if len(set(取值列表)) < 2:
        return None
    return 取值列表


def _列基数(df: pd.DataFrame, 列: str) -> int:
    try:
        return int(df[列].nunique(dropna=True))
    except (KeyError, TypeError, ValueError):
        return 0


def _像ID列(列: str) -> bool:
    名称 = str(列).strip().lower().replace("_", "").replace("-", "")
    return 名称.endswith("id") or 名称 in ("编号", "序号", "主键")


def 解析来源轴(
    数据列表: Sequence[pd.DataFrame],
    名称列表: Sequence[str],
    手动标签: Optional[Sequence[str]] = None,
    指定列: Optional[str] = None,
) -> Dict[str, Any]:
    """决定"谁跟谁比"，返回 {"列": Optional[str], "标签": [...], "推导方式": str}。

    优先级：手动标签 > 用户指定的恒定列 > 自动识别的恒定列 > 文件名。
    手动标签与数据集一一对应时直接用（不要求恒定列），数量不匹配则忽略。
    """
    数量 = len(数据列表)
    标签 = [str(x).strip() for x in (手动标签 or []) if str(x).strip()]
    if len(标签) == 数量 and len(set(标签)) == 数量:
        return {"列": None, "标签": 标签, "推导方式": "手动标签"}

    if 指定列:
        取值 = _恒定型列识别(数据列表, 指定列, 允许数值=True)
        if 取值:
            return {"列": 指定列, "标签": 取值, "推导方式": "指定列"}
        # 指定的列不恒定（每份文件里都有多个取值）→ 退化为文件名，但要告诉用户原因
        return {
            "列": None,
            "标签": 推导来源标签(名称列表),
            "推导方式": "文件名",
            "警告": f"指定的来源轴列「{指定列}」在部分数据集中有多个取值，无法作为来源轴，已改用文件名",
        }

    候选: List[Tuple[str, List[str]]] = []
    for 列 in _共同字段(数据列表):
        取值 = _恒定型列识别(数据列表, 列)
        if 取值:
            候选.append((列, 取值))
    if 候选:
        # 多个恒定列都可能当来源轴时：优先时间型（最常见），再按列名稳定排序
        候选.sort(key=lambda 项: (0 if 判定对比轴类型(项[1]) == 轴类型时间 else 1, 项[0]))
        列名, 取值 = 候选[0]
        结果: Dict[str, Any] = {"列": 列名, "标签": 取值, "推导方式": "恒定列"}
        if len(候选) > 1:
            其它 = "、".join(f"「{名}」" for 名, _ in 候选[1:])
            结果["警告"] = f"另有恒定列 {其它} 也可作为来源轴，可在设置中指定"
        return 结果

    return {"列": None, "标签": 推导来源标签(名称列表), "推导方式": "文件名"}


def _命中文本(候选列表: Sequence[str], 文本: str) -> Optional[str]:
    """在需求文本里找候选字段名（长的优先，避免"销售金额"命中"销售"）。"""
    有效 = [c for c in 候选列表 if c]
    if not 文本:
        return None
    命中 = [c for c in 有效 if str(c) in 文本]
    if not 命中:
        return None
    return max(命中, key=len)


def _推定聚合方式(文本: str, 默认: str = "求和") -> str:
    """需求文本里的聚合词 → 聚合口径（"平均单价"→平均值，"有多少"→计数）。"""
    for 关键词, 口径 in (
        ("平均", "平均值"), ("均值", "平均值"), ("人均", "平均值"), ("单均", "平均值"),
        ("最大值", "最大值"), ("最高", "最大值"), ("最小值", "最小值"), ("最低", "最小值"),
        ("数量", "计数"), ("多少个", "计数"), ("多少条", "计数"), ("条数", "计数"),
        ("笔数", "计数"), ("次数", "计数"), ("频次", "计数"),
        ("总额", "求和"), ("合计", "求和"), ("总计", "求和"), ("总和", "求和"),
    ):
        if 关键词 in (文本 or ""):
            return 口径
    return 默认


def 生成对比预览(
    数据列表: Sequence[pd.DataFrame],
    名称列表: Sequence[str],
    手动标签: Optional[Sequence[str]] = None,
    来源轴: Optional[str] = None,
) -> Dict[str, Any]:
    """对比能力预检：共同字段、可选轴、推荐口径、警告——供前端"对比分析"页开箱选择。

    只读、不做任何计算，纯结构分析。
    """
    警告: List[str] = []
    if len(数据列表) < 最小数据集数:
        警告.append(f"至少需要 {最小数据集数} 个数据集才能对比，当前 {len(数据列表)} 个")
    总行数 = sum(len(df) for df in 数据列表)
    if 总行数 > 最大总行数:
        警告.append(f"合计 {总行数} 行超过上限 {最大总行数} 行，请先筛选或合并")

    共同字段 = _共同字段(数据列表)
    来源 = 解析来源轴(数据列表, 名称列表, 手动标签, 来源轴)
    if 来源.get("警告"):
        警告.append(来源["警告"])
    来源列 = 来源.get("列")

    指标候选 = [列 for 列 in 共同字段 if _全数值列(数据列表, 列)]
    # ID 类数值列排在最后（订单ID 求和没有意义，但仍允许用户主动选）
    指标候选.sort(key=lambda 列: (1 if _像ID列(列) else 0, 共同字段.index(列)))

    主体轴候选: List[Dict[str, Any]] = []
    for 列 in 共同字段:
        if 列 == 来源列 or 列 in 指标候选:
            continue
        基数 = max((_列基数(df, 列) for df in 数据列表), default=0)
        if not 主体轴基数下限 <= 基数 <= 主体轴基数上限:
            continue
        首集 = 数据列表[0]
        if _像时间列(首集[列]):
            continue  # 日期列不是"比哪些对象"
        主体轴候选.append({"列": 列, "基数": 基数})
    主体轴候选.sort(key=lambda 项: 项["基数"])

    来源轴候选 = [{"列": 来源列, "各数据集取值": 来源["标签"], "类型": 判定对比轴类型(来源["标签"])}]
    for 列 in 共同字段:
        if 列 == 来源列:
            continue
        取值 = _恒定型列识别(数据列表, 列)
        if 取值:
            来源轴候选.append({"列": 列, "各数据集取值": 取值, "类型": 判定对比轴类型(取值)})

    if not 指标候选:
        警告.append(f"各数据集没有共同的数值字段（共同字段：{'、'.join(共同字段) or '无'}），无法对比")
    if not 主体轴候选:
        警告.append("没有基数 2~50 的共同分类字段，将把每个数据集整体作为一行来对比")

    return {
        "共同字段": 共同字段,
        "指标候选": 指标候选,
        "主体轴候选": 主体轴候选,
        "来源轴候选": 来源轴候选,
        "推荐": {
            "来源轴": 来源列,
            "来源标签": 来源["标签"],
            "推导方式": 来源["推导方式"],
            "主体轴": 主体轴候选[0]["列"] if 主体轴候选 else None,
            "指标": 指标候选[0] if 指标候选 else None,
            "聚合方式": "求和",
            "轴类型": 判定对比轴类型(来源["标签"]),
        },
        "行数": 总行数,
        "警告": 警告,
    }


# ═══════════════════════════════════════════════════════════════
# 三、对比计算：透视成"来源 × 主体"的宽表
# ═══════════════════════════════════════════════════════════════

def _解析实际列名(df: pd.DataFrame, 列: Optional[str]) -> Optional[str]:
    """在 df 里找到与「列」语义相同的真实列名；找不到返回 None。

    先精确匹配（绝大多数情况），匹配不到再按别名组找——这样「指标=销售额」
    在只有「销售金额」的数据集上也能取到数，而不是静默产出一行空数据。
    """
    if not 列:
        return None
    if 列 in df.columns:
        return 列
    归一 = _列名归一(列)
    for c in df.columns:
        if _列名归一(str(c)) == 归一:
            return str(c)
    return None


def _聚合单数据集(
    df: pd.DataFrame,
    主体轴: Optional[str],
    指标: Optional[str],
    聚合方式: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """单个数据集按主体轴聚合指标 → [{"主体": 值, "值": 数值}] + 实际值列名。"""
    聚合 = 聚合映射.get(聚合方式, "sum")
    实际主体 = _解析实际列名(df, 主体轴)
    实际指标 = _解析实际列名(df, 指标)
    if 聚合方式 == "计数" or not 指标:
        if 实际主体:
            分组 = df.groupby(实际主体, dropna=False).size().reset_index(name="记录数")
        else:
            分组 = pd.DataFrame({列_主体: [主体_全部], "记录数": [int(len(df))]})
        return (
            [{列_主体: str(行[实际主体 or 列_主体]), "值": float(行["记录数"])} for _, 行 in 分组.iterrows()],
            "记录数",
        )
    if not 实际主体:
        # 没有主体轴：整个数据集聚合成一行（"只看总量变化"）
        if not 实际指标:
            return [], 指标
        数值 = pd.to_numeric(df[实际指标], errors="coerce").dropna()
        if 数值.empty:
            return [], 指标
        return [{列_主体: 主体_全部, "值": float(getattr(数值, 聚合)())}], 实际指标
    if not 实际指标:
        return [], 指标
    工作 = df[[实际主体, 实际指标]].copy()
    工作[实际指标] = pd.to_numeric(工作[实际指标], errors="coerce")
    工作 = 工作.dropna(subset=[实际指标])
    if 工作.empty:
        return [], 指标
    分组 = 工作.groupby(实际主体, dropna=False)[实际指标].agg(聚合).reset_index()
    return (
        [{列_主体: str(行[实际主体]), "值": float(行[实际指标])} for _, 行 in 分组.iterrows()],
        实际指标,
    )


def _安全除法(分子: float, 分母: float) -> Optional[float]:
    """除零/None/非有限 → None（对齐 M24：绝不产出 Infinity/NaN 进 JSON）。"""
    try:
        if 分母 is None or 分子 is None:
            return None
        分母 = float(分母)
        分子 = float(分子)
    except (TypeError, ValueError):
        return None
    if 分母 == 0 or not np.isfinite(分母) or not np.isfinite(分子):
        return None
    商 = 分子 / 分母
    return round(商, 4) if np.isfinite(商) else None


def _对比明细(
    宽表: pd.DataFrame,
    标签: List[str],
    轴类型: str,
    指标名称: str,
) -> List[Dict[str, Any]]:
    """宽表 → 每个主体一行的对比明细（含变化量/变化率 或 差值/倍数/排名）。

    宽表：index = 主体值，columns = 来源标签。
    """
    明细: List[Dict[str, Any]] = []
    if 宽表.empty:
        return 明细
    for 主体, 行 in 宽表.iterrows():
        记录: Dict[str, Any] = {列_主体: str(主体)}
        有效值: List[Tuple[str, float]] = []
        for 标签值 in 标签:
            原值 = 行.get(标签值)
            try:
                数值 = float(原值) if 原值 is not None and not pd.isna(原值) else None
            except (TypeError, ValueError):
                数值 = None
            记录[标签值] = 数值
            if 数值 is not None:
                有效值.append((标签值, 数值))
        if 轴类型 == 轴类型时间 and len(标签) >= 2:
            首 = 记录.get(标签[0])
            末 = 记录.get(标签[-1])
            记录[列_变化量] = None if 首 is None or 末 is None else round(末 - 首, 4)
            记录[列_变化率] = _安全除法(
                (末 - 首) if 首 is not None and 末 is not None else None, 首
            )
            if 记录[列_变化量] is not None:
                明细.append(记录)
            continue
        # 类别型：跨来源取最大/最小 → 差值 + 倍数 + 排名（不伪造变化率）
        if 有效值:
            最高 = max(有效值, key=lambda 项: 项[1])
            最低 = min(有效值, key=lambda 项: 项[1])
            记录["最高来源"] = 最高[0]
            记录["最低来源"] = 最低[0]
            记录[列_差值] = round(最高[1] - 最低[1], 4)
            记录[列_倍数] = _安全除法(最高[1], 最低[1])
        明细.append(记录)
    # 排名按"最新一期"（时间型）或"差值"（类别型）降序，便于阅读
    排序列 = (标签[-1] if 标签 else None) if 轴类型 == 轴类型时间 else 列_差值
    if 排序列 and any(项.get(排序列) is not None for 项 in 明细):
        明细.sort(key=lambda 项: (项.get(排序列) is None, -(项.get(排序列) or 0)))
    for 序号, 记录 in enumerate(明细, start=1):
        记录[列_排名] = 序号
    return 明细


def 执行对比(
    数据列表: Sequence[pd.DataFrame],
    名称列表: Sequence[str],
    对比标签: Optional[Sequence[str]] = None,
    来源轴: Optional[str] = None,
    主体轴: Optional[str] = None,
    指标: Optional[str] = None,
    聚合方式: str = "求和",
    图表类型: str = "自动推荐",
    分析需求: str = "",
    筛选条件: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """执行一次跨数据集对比，返回 {长表, 明细, 宽表, 标签, 轴类型, ...}（不含结论文本）。

    长表格式与平台既有图表契约一致：`{主体轴, 指标, 来源}` →
    前端 EChartsChart 用 颜色=来源 分组画多系列（EChartsChart.jsx:349-369）。
    """
    数值指标 = (指标 or "").strip() or None
    聚合口径 = 聚合方式 if 聚合方式 in 聚合映射 else "求和"
    警告: List[str] = []

    # 1. 逐集套用筛选（对比场景下筛选是"两边用同一批条件"，保证口径一致）
    过滤后: List[pd.DataFrame] = []
    for df in 数据列表:
        子集 = df
        if 筛选条件:
            try:
                子集, 说明 = 应用筛选(df, list(筛选条件))
                if 说明:
                    警告.append(f"已套用筛选：{'；'.join(说明)}")
            except (KeyError, TypeError, ValueError) as 异常:
                警告.append(f"筛选条件未生效（{异常}），已按全量数据对比")
                子集 = df
        过滤后.append(子集)

    # 2. 定来源轴与标签
    # 注意：轴结构一律从**未筛选**的全量数据推导。筛选只是缩小行范围，
    # 若拿筛选后的数据判定"共同分类字段"，地区被筛到只剩 1 个值就会掉出
    # 基数 2~50 的候选，用户明明筛了"华东"却会看到"（全部）"这种假象。
    来源 = 解析来源轴(数据列表, 名称列表, 对比标签, 来源轴)
    if 来源.get("警告"):
        警告.append(来源["警告"])
    标签 = 排序对比标签(来源["标签"])
    if len(标签) != len(过滤后):
        警告.append(
            f"来源标签数（{len(标签)}）与数据集数（{len(过滤后)}）不一致，已按位置对齐"
        )
    else:
        # 标签排了序，数据集必须按同一份顺序一起排。
        # 阶段七十二真机 E2E 抓到的缺陷：这里原先只排标签不排数据，
        # 乱序上传 10月/1月/2月 时「10月」的数字被挂到了「1月」名下，
        # 报表看着正常、数字全错。标签顺序与数据顺序必须同源。
        过滤后 = [过滤后[序] for 序 in 对比标签顺序(来源["标签"])]
    轴类型 = 判定对比轴类型(标签)

    # 3. 主体轴与指标：指定优先 → 需求文本命中 → 结构推荐
    预览 = 生成对比预览(数据列表, 名称列表, 对比标签, 来源轴)
    主体轴名 = (主体轴 or "").strip() or None
    if not 主体轴名:
        候选 = [项["列"] for 项 in 预览["主体轴候选"]]
        主体轴名 = _命中文本(候选, 分析需求) or (候选[0] if 候选 else None)
    if not 数值指标:
        候选 = 预览["指标候选"]
        数值指标 = _命中文本(候选, 分析需求) or (候选[0] if 候选 else None)
    elif 数值指标 not in 预览["指标候选"]:
        # 用户显式指定的指标不是各集共有的数值列 → 明确报错，
        # 而不是悄悄产出一张空数据的报表（M 系列教训：静默降级最难排查）
        raise ValueError(
            f"指标「{数值指标}」不是各数据集共有的数值字段"
            f"（可选：{'、'.join(预览['指标候选']) or '无'}）"
        )
    聚合口径 = _推定聚合方式(分析需求, 聚合口径) if 分析需求 else 聚合口径
    if not 数值指标 and 聚合口径 != "计数":
        raise ValueError(
            "各数据集没有共同的数值字段，无法对比"
            f"（共同字段：{'、'.join(预览['共同字段']) or '无'}）"
        )
    指标名称 = "记录数" if 聚合口径 == "计数" else (数值指标 or "记录数")

    # 4. 逐集聚合 → 长表
    长表: List[Dict[str, Any]] = []
    各集主体: List[set] = []
    for 序号, df in enumerate(过滤后):
        标签值 = 标签[序号] if 序号 < len(标签) else f"数据集{序号 + 1}"
        行列表, 实际指标名 = _聚合单数据集(df, 主体轴名, 数值指标, 聚合口径)
        if not 行列表:
            警告.append(f"数据集「{标签值}」没有可用数据（{实际指标名} 全为空或缺失）")
        各集主体.append({行[列_主体] for 行 in 行列表})
        for 行 in 行列表:
            长表.append({列_主体: 行[列_主体], 指标名称: 行["值"], 列_来源: 标签值})

    # 5. 主体取值：默认取交集（"同一个地区"才可比），交集不足 2 个退回并集
    if not 主体轴名:
        # 无主体轴 = 只比每个数据集的总量，不存在"主体对齐"问题
        保留 = set.union(*各集主体) if 各集主体 else set()
    else:
        交集 = set.intersection(*各集主体) if 各集主体 else set()
        并集 = set.union(*各集主体) if 各集主体 else set()
        if len(交集) >= 2:
            保留 = 交集
        else:
            保留 = 并集
            if 并集:
                警告.append(
                    f"数据集之间共同的主体只有 {len(交集)} 个，无法严格对齐，已改用并集对比"
                    "（部分主体在部分数据集中缺数据，图上会显示为 0）"
                )
    长表 = [行 for 行 in 长表 if 行[列_主体] in 保留]
    # 主体按"各来源合计"降序，图更直观；来源按轴类型顺序
    合计: Dict[str, float] = {}
    for 行 in 长表:
        合计[行[列_主体]] = 合计.get(行[列_主体], 0.0) + float(行[指标名称] or 0)
    主体序 = {主体: 序 for 序, 主体 in enumerate(
        sorted(合计, key=lambda 键: (-合计[键], 自然排序键(键)))
    )}
    来源序 = {标签值: 序 for 序, 标签值 in enumerate(标签)}
    长表.sort(key=lambda 行: (主体序.get(行[列_主体], 0), 来源序.get(行[列_来源], 0)))

    # 6. 宽表 + 明细（变化量/变化率 或 差值/倍数/排名）
    宽表 = pd.DataFrame(
        {标签值: {行[列_主体]: 行[指标名称] for 行 in 长表 if 行[列_来源] == 标签值} for 标签值 in 标签}
    )
    宽表.index.name = 列_主体
    明细 = _对比明细(宽表, 标签, 轴类型, 指标名称)

    # 7. 图表类型：只允许消费 groupField 的类型（饼图/折线图会把来源轴丢掉）
    期望图表 = (图表类型 or "自动推荐").strip()
    if 期望图表 not in 对比图表白名单:
        警告.append(
            f"图表类型「{期望图表}」不支持按来源分组显示，已改用{默认对比图表}"
        )
        期望图表 = 默认对比图表
    if 期望图表 == "自动推荐":
        期望图表 = 默认对比图表
    plotly类型 = 图表类型映射.get(期望图表, "stacked_bar")

    return {
        "长表": 长表,
        "宽表": 宽表,
        "明细": 明细,
        "标签": 标签,
        "轴类型": 轴类型,
        "主体轴": 主体轴名,
        "指标": 指标名称,
        "聚合方式": 聚合口径,
        "来源轴": 来源.get("列"),
        "推导方式": 来源.get("推导方式"),
        "图表类型": 期望图表,
        "plotly类型": plotly类型,
        "警告": 警告,
    }


# ═══════════════════════════════════════════════════════════════
# 四、结论：时间型讲"变化"，类别型讲"差距"
# ═══════════════════════════════════════════════════════════════

def _格式化数值(值: Any) -> str:
    """数值人读格式：千分位 + 最多保留 2 位小数（整数不补小数）。"""
    try:
        数值 = float(值)
    except (TypeError, ValueError):
        return "—"
    if not np.isfinite(数值):
        return "—"
    if abs(数值 - round(数值)) < 1e-9:
        return f"{int(round(数值)):,}"
    return f"{数值:,.2f}"


def _格式化率(值: Optional[float]) -> str:
    if 值 is None:
        return "—"
    return f"{值 * 100:+.1f}%"


def 生成对比结论(对比结果: Dict[str, Any]) -> str:
    """用确定性规则写结论（模板化，不依赖大模型；LLM 只做可选润色）。"""
    明细 = 对比结果.get("明细") or []
    标签 = 对比结果.get("标签") or []
    指标 = 对比结果.get("指标") or "记录数"
    轴类型 = 对比结果.get("轴类型")
    主体轴 = 对比结果.get("主体轴") or "对象"
    if not 明细 or not 标签:
        return "没有可比对的数据。"

    if 轴类型 == 轴类型时间 and len(标签) >= 2:
        首标签, 末标签 = 标签[0], 标签[-1]
        首合计 = sum((项.get(首标签) or 0) for 项 in 明细)
        末合计 = sum((项.get(末标签) or 0) for 项 in 明细)
        总变化 = _安全除法(末合计 - 首合计, 首合计)
        语句 = [
            f"{指标}整体从「{首标签}」的 {_格式化数值(首合计)} 变为「{末标签}」的 "
            f"{_格式化数值(末合计)}（{_格式化率(总变化)}）"
        ]
        有变化 = [项 for 项 in 明细 if 项.get(列_变化率) is not None]
        if 有变化:
            增长 = max(有变化, key=lambda 项: 项[列_变化率])
            下滑 = min(有变化, key=lambda 项: 项[列_变化率])
            语句.append(f"{主体轴}「{增长[列_主体]}」增幅最大（{_格式化率(增长[列_变化率])}）")
            if 下滑[列_变化率] < 0:
                语句.append(f"「{下滑[列_主体]}」降幅最大（{_格式化率(下滑[列_变化率])}）")
            else:
                语句.append(f"所有{主体轴}均为增长或持平，最低为「{下滑[列_主体]}」（{_格式化率(下滑[列_变化率])}）")
        return "；".join(语句) + "。"

    # 类别型：比差距、比倍数、比排名
    有值 = [项 for 项 in 明细 if 项.get(列_差值) is not None]
    if not 有值:
        return f"没有可比较的{指标}数据。"
    最高 = 有值[0]
    语句 = [f"{主体轴}「{最高[列_主体]}」的{指标}差距最大："
            f"{最高.get('最高来源')} 比 {最高.get('最低来源')} 多 {_格式化数值(最高[列_差值])}"]
    if 最高.get(列_倍数) is not None:
        语句.append(f"相差 {最高[列_倍数]:.2f} 倍")
    各来源合计 = {标签值: sum((项.get(标签值) or 0) for 项 in 明细) for 标签值 in 标签}
    if 各来源合计 and any(各来源合计.values()):
        最高来源 = max(各来源合计, key=lambda 键: 各来源合计[键])
        最低来源 = min(各来源合计, key=lambda 键: 各来源合计[键])
        语句.append(
            f"合计口径上「{最高来源}」最高（{_格式化数值(各来源合计[最高来源])}），"
            f"「{最低来源}」最低（{_格式化数值(各来源合计[最低来源])}）"
        )
    return "；".join(语句) + "。"


def _生成推荐理由(对比结果: Dict[str, Any]) -> List[str]:
    """把"怎么比的"拆成人读的理由列表（导出 HTML 的「推荐依据」直接展示）。"""
    来源说明 = (
        f"来源轴取自数据集内的恒定列 `{对比结果['来源轴']}`" if 对比结果.get("来源轴")
        else "来源轴由文件名推导"
    )
    理由 = [
        f"对比了 {len(对比结果.get('标签') or [])} 个数据集（{'、'.join(对比结果.get('标签') or [])}）",
        来源说明 + f"（推导方式：{对比结果.get('推导方式')}）",
    ]
    if 对比结果.get("主体轴"):
        理由.append(
            f"`{对比结果['主体轴']}` 是各数据集共有的分类字段，用作主体轴对齐同一批对象"
        )
    else:
        理由.append("没有可用的共同分类字段，改为对每个数据集整体合计做对比")
    if 对比结果.get("指标"):
        理由.append(
            f"`{对比结果['指标']}` 是各数据集共有的数值字段，用 `{对比结果.get('聚合方式')}` 口径对比"
        )
    if 对比结果.get("轴类型") == 轴类型时间:
        理由.append("对比轴可解析为时间，按变化量与变化率呈现")
    else:
        理由.append("对比轴是类别而非时间，按差值/倍数/排名呈现（不虚构变化率）")
    return 理由


def 生成推荐说明(对比结果: Dict[str, Any]) -> Dict[str, Any]:
    """与单表报表 `_生成推荐说明` 同构（前端读 `推荐说明.理由`，HTML 导出读同一处）。"""
    return {
        "图表类型": 对比结果.get("图表类型") or 默认对比图表,
        "自动推荐": True,
        "理由": _生成推荐理由(对比结果),
        "推荐字段": {
            "来源轴": 对比结果.get("来源轴") or 列_来源,
            "主体轴": 对比结果.get("主体轴"),
            "指标": 对比结果.get("指标"),
            "聚合方式": 对比结果.get("聚合方式"),
        },
    }


def _对比数据画像(对比结果: Dict[str, Any], 数据列表: Sequence[pd.DataFrame]) -> Dict[str, Any]:
    """对比报表的数据画像：讲清"比了几份数据、多少行"，而不是单表列统计。

    前端报表页读 `数据画像.行数/列数` 显示"数据集共 N 行 M 列"，
    对比场景把 N/M 换成来源文件的合计，语义更贴合。
    """
    行数 = sum(len(df) for df in 数据列表)
    列数 = max((df.shape[1] for df in 数据列表), default=0)
    若干 = 对比结果.get("警告") or []
    return {
        "行数": 行数,
        "列数": 列数,
        "数据集个数": len(数据列表),
        "字段列表": sorted({str(c) for df in 数据列表 for c in df.columns}),
        "对比轴类型": 对比结果.get("轴类型"),
        "主体轴": 对比结果.get("主体轴"),
        "指标": 对比结果.get("指标"),
        "数据质量": {
            "等级": "需关注" if 若干 else "良好",
            "提示": list(若干),
        },
    }


def _对比_agent_trace(对比结果: Dict[str, Any], 数据列表: Sequence[pd.DataFrame]) -> List[Dict[str, Any]]:
    """对比链路的决策轨迹（与单表报表的 Agent Trace 同构，报表页可直接渲染）。"""
    标签 = 对比结果.get("标签") or []
    来源说明 = (
        f"`{对比结果['来源轴']}`" if 对比结果.get("来源轴") else "文件名"
    )
    return [
        {
            "步骤": "选择数据",
            "状态": "完成",
            "说明": f"选定 {len(数据列表)} 个数据集，合计 {sum(len(df) for df in 数据列表)} 行。",
        },
        {
            "步骤": "确认对比轴",
            "状态": "完成",
            "说明": f"来源轴取 {来源说明}（{对比结果.get('推导方式')}），标签为 {'、'.join(标签)}；"
                    f"判定为{对比结果.get('轴类型')}。",
        },
        {
            "步骤": "对齐主体",
            "状态": "完成",
            "说明": (
                f"以 `{对比结果['主体轴']}` 为共同分类字段对齐同一批对象。"
                if 对比结果.get("主体轴")
                else "无共同分类字段，按每个数据集整体合计对齐。"
            ),
        },
        {
            "步骤": "聚合计算",
            "状态": "完成",
            "说明": f"按 `{对比结果.get('聚合方式')}` 聚合 `{对比结果.get('指标')}`，"
                    f"生成 {len(对比结果.get('长表') or [])} 行对比长表。",
        },
        {
            "步骤": "生成结论",
            "状态": "完成",
            "说明": "根据对比轴类型生成变化量/变化率或差值/倍数/排名结论。",
        },
    ]


# ═══════════════════════════════════════════════════════════════
# 五、LLM 解读（可选）：只喂摘要，不喂全表
# ═══════════════════════════════════════════════════════════════

_解读提示 = """你是数据分析师。下面是同一批对象在多个来源（{轴类型}）下的对比结果摘要，
请用 2~3 句中文写一段结论性解读，指出最值得关注的变化或差距，不要复述所有数字，
不要编造摘要里没有的数据，不要使用 Markdown。

指标：{指标}（{聚合方式}口径）
对象维度：{主体轴}
来源：{标签}
对比明细（前 10 行 JSON）：
{明细}
"""


def 解读对比结果(
    对比结果: Dict[str, Any],
    分析需求: str = "",
    llm_config: Any = None,
) -> Optional[str]:
    """调用大模型写结论；未配置/失败返回 None（由调用方回退 `生成对比结论`）。"""
    if not llm_config:
        return None
    try:
        from 后端_核心.agent.llm_client import chat_completion, is_llm_configured
    except ImportError:
        return None
    if not is_llm_configured(getattr(llm_config, "api_key", None)):
        return None
    明细 = (对比结果.get("明细") or [])[:10]
    提示 = _解读提示.format(
        轴类型=对比结果.get("轴类型"),
        指标=对比结果.get("指标"),
        聚合方式=对比结果.get("聚合方式"),
        主体轴=对比结果.get("主体轴") or "整体",
        标签="、".join(对比结果.get("标签") or []),
        明细=json.dumps(明细, ensure_ascii=False),
    )
    if 分析需求:
        提示 += f"\n用户的分析需求是：{分析需求}"
    try:
        回答 = chat_completion(
            [{"role": "user", "content": 提示}],
            llm_config=llm_config,
        )
    except Exception:  # noqa: BLE001 —— 解读是可选增强，任何失败都不能影响主流程
        return None
    if isinstance(回答, dict):
        回答 = 回答.get("content") or ""
    文本 = str(回答 or "").strip()
    return 文本 or None


# ═══════════════════════════════════════════════════════════════
# 六、报表装配：产出与单表报表同构的结构，直接复用报表页
# ═══════════════════════════════════════════════════════════════

def 构建对比报表(
    对比结果: Dict[str, Any],
    分析需求: str = "",
    标题: str = "",
    数据集ID列表: Optional[Sequence[str]] = None,
    筛选条件: Optional[Sequence[Dict[str, Any]]] = None,
    llm_config: Any = None,
    数据列表: Optional[Sequence[pd.DataFrame]] = None,
) -> Dict[str, Any]:
    """把 `执行对比` 的结果装配成报表结构（键名对齐 report_generator 的 result）。

    `图表配置.数据` 用长表（前端按 颜色=来源 画多系列），`报表数据` 同样用长表
    以保证分享页/导出不乱；对比明细放在 `对比配置.明细` 里供专门展示。

    `数据列表` 只用于生成数据画像（"共几份文件、合计多少行"）；不传则退化为
    用长表统计——报表页照常能显示，只是行数口径变成对比结果的行数。
    """
    长表 = 对比结果.get("长表") or []
    标签 = 对比结果.get("标签") or []
    主体轴 = 对比结果.get("主体轴")
    指标 = 对比结果.get("指标") or "记录数"
    X轴 = 主体轴 or 列_主体
    标题文本 = (标题 or "").strip() or f"{指标}跨数据集对比（{' · '.join(标签)}）"
    报表行 = _可_json行(pd.DataFrame(长表)) if 长表 else []

    图表配置: Dict[str, Any] = {
        "类型": 对比结果.get("plotly类型") or "stacked_bar",
        "标题": 标题文本,
        "X轴": X轴,
        "Y轴": [指标],
        # 颜色=来源 → EChartsChart 的 bar/stacked_bar 分支按来源分系列
        "颜色": 列_来源,
        "数据": 报表行,
        "筛选条件": list(筛选条件 or []),
        "筛选说明": "；".join(对比结果.get("警告") or []) if 对比结果.get("警告") else "",
        "TopN": None,
        "对比": None,
        "数据集ID列表": list(数据集ID列表 or []),
    }

    推荐说明 = 生成推荐说明(对比结果)
    风险提示 = list(对比结果.get("警告") or [])
    结论 = 解读对比结果(对比结果, 分析需求, llm_config)
    结论来源 = "LLM"
    if not 结论:
        结论 = 生成对比结论(对比结果)
        结论来源 = "规则"

    报表: Dict[str, Any] = {
        "标题": 标题文本,
        "分析需求": 分析需求,
        "图表类型": 对比结果.get("图表类型") or 默认对比图表,
        "图表配置": 图表配置,
        "报表数据": 报表行,
        "数据画像": _对比数据画像(对比结果, list(数据列表 or [])),
        "推荐说明": 推荐说明,
        "风险提示": 风险提示,
        "Agent Trace": _对比_agent_trace(对比结果, list(数据列表 or [])),
        "结论": 结论,
        "结论来源": 结论来源,
        "对比配置": {
            "轴类型": 对比结果.get("轴类型"),
            "来源轴": 对比结果.get("来源轴"),
            "推导方式": 对比结果.get("推导方式"),
            "标签": 标签,
            "主体轴": 主体轴,
            "指标": 指标,
            "聚合方式": 对比结果.get("聚合方式"),
            "明细": _可_json行(pd.DataFrame(对比结果.get("明细") or []))
            if 对比结果.get("明细") else [],
            "警告": 风险提示,
        },
        "数据集ID列表": list(数据集ID列表 or []),
    }

    # 导出数据：与单表报表同构（前端导出 HTML/JSON 直接取这两个键）
    导出数据: Dict[str, Any] = {
        "推荐文件名": "compare-report.html",
        "格式": "html",
    }
    try:
        导出数据["HTML"] = _生成HTML报告(报表)
    except Exception:  # noqa: BLE001 - 导出是附加能力，失败不能拖垮对比主流程
        导出数据.pop("HTML", None)
    try:
        导出数据["JSON"] = json.dumps(报表, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        导出数据.pop("JSON", None)
    报表["导出数据"] = 导出数据
    return 报表
