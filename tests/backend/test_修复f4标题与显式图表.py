# -*- coding: utf-8 -*-
"""Fix 4（阶段54-7）· 188 字需求原样作标题 + 显式「饼图」被改写为直方图。

走查证据：需求「图表类型:饼图 请分析数据中各个类别的分布情况并给出详细建议和后续
改进方向…」（188 字）→ 标题=需求原文 188 字未截断；图表类型变直方图（规则意图
「分布情况」优先级压过显式「饼图」）。

修复：
1. 标题截断：生成报表时标题超 60 字截断加省略号（后端标题生成处截断）。
2. 显式「图表类型:XXX」/图表名关键词优先于语义推断：用户明确说了饼图就该是饼图。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心 import report_generator as generator
from 后端_核心.field_selector import _受控语句配置


@pytest.fixture
def 画像():
    return {
        "行数": 150,
        "列数": 5,
        "字段列表": ["SepalLength", "SepalWidth", "PetalLength", "PetalWidth", "Name"],
        "数值字段": ["SepalLength", "SepalWidth", "PetalLength", "PetalWidth"],
        "分类字段": ["Name"],
        "日期字段": [],
        "文本字段": [],
    }


@pytest.fixture
def irisdf():
    # Name 用短枚举值（avg_len ≤ 6），保证画像分类为 分类字段——
    # 真实 iris 的 setosa/versicolor/virginica 平均 8.3 字会被归为文本字段，
    # 自动选字段的 X 轴兜底将落到字段列表第一列（与图表类型断言无关）。
    return pd.DataFrame({
        "SepalLength": [5.1, 4.9, 5.0, 5.4, 5.6, 5.2],
        "SepalWidth": [3.5, 3.0, 3.6, 3.9, 3.4, 3.1],
        "PetalLength": [1.4, 1.4, 1.4, 1.7, 1.5, 1.2],
        "PetalWidth": [0.2, 0.2, 0.2, 0.4, 0.3, 0.3],
        "Name": ["se", "se", "ve", "ve", "vi", "vi"],
    })


# ═══ 1. 标题截断 ═══

def test_生成报表_长需求标题截断到60字(irisdf):
    """188 字需求原样作标题 → 截断到 60 字 + 省略号（≤61 字符）。"""
    长需求 = "图表类型:饼图 请分析数据中各个类别的分布情况并给出详细建议和后续改进方向。" * 6
    assert len(长需求) > 100  # 前置：确认确实是长需求
    r = generator.生成报表数据(
        irisdf,
        分析需求=长需求,
        图表类型="自动推荐",
        x轴="Name", y轴=["SepalLength"],
        分组字段=None, 聚合方式="平均值",
    )
    assert len(r["标题"]) <= 61
    assert r["标题"].endswith("…")


def test_生成报表_短标题不截断(irisdf):
    r = generator.生成报表数据(
        irisdf, 分析需求="按Name统计SepalLength平均值",
        图表类型="柱状图", x轴="Name", y轴=["SepalLength"],
        分组字段=None, 聚合方式="平均值",
    )
    assert r["标题"] == "按Name统计SepalLength平均值"


# ═══ 2. 显式图表类型优先于语义推断 ═══

def test_受控语句_显式饼图不被分布语义改写(画像):
    """「图表类型:饼图 …各个类别的分布情况…」修复前被"分布情况"→直方图改写。"""
    out = _受控语句配置(画像, "图表类型:饼图 请分析数据中各个类别的分布情况并给出详细建议")
    assert out["图表类型"] == "饼图"
    assert out["x轴"] == "Name"


def test_受控语句_显式饼图不被统计数量语义改写(画像):
    """「图表类型:饼图 按Name统计数量的占比」修复前被"统计+数量"→柱状图改写。"""
    out = _受控语句配置(画像, "图表类型:饼图 按Name统计数量的占比")
    assert out["图表类型"] == "饼图"
    assert out["x轴"] == "Name"


def test_生成报表_显式饼图优先(irisdf):
    r = generator.生成报表数据(
        irisdf,
        分析需求="图表类型:饼图 请分析数据中各个类别的分布情况并给出详细建议",
        图表类型="自动推荐",
        x轴=None, y轴=[], 分组字段=None, 聚合方式="求和",
    )
    assert r["图表类型"] == "饼图"
    assert r["图表配置"]["X轴"] == "Name"


def test_受控语句_无显式声明时语义推断不变(画像):
    """回归：没有显式图表声明时，「分布情况」仍走直方图语义。"""
    out = _受控语句配置(画像, "请分析数据中各个类别的分布情况")
    assert out["图表类型"] == "直方图"