# -*- coding: utf-8 -*-
"""Fix 1（Critical，阶段54-7）· 分析「按分类统计数值」静默失败：后端 x==y 聚合崩溃。

走查证据：iris +「柱状图 按Name统计SepalLength的平均值」→ 意图解析把 x轴 与 y轴
都定为 SepalLength（x==y）→ `_聚合数据` 里 `df.groupby([x])[x].agg().reset_index()`
因索引列名与数据列名冲突抛 `ValueError: cannot insert SepalLength, already exists`
→ SSE 发 error 事件 → 前端静默失败。

修复：聚合前过滤 y 轴列 == x轴（或分组字段）的字段——groupby 分组键不能同时作为
聚合值列；count 路径不经过 valid_y，天然不受影响（按分类计数仍有意义），只过滤
非 count 路径。
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


@pytest.fixture
def irisdf():
    """走查同款 iris 片段：Name 为分类，四个数值列。"""
    return pd.DataFrame({
        "SepalLength": [5.1, 4.9, 5.0, 5.4, 5.6, 5.2],
        "SepalWidth": [3.5, 3.0, 3.6, 3.9, 3.4, 3.1],
        "PetalLength": [1.4, 1.4, 1.4, 1.7, 1.5, 1.2],
        "PetalWidth": [0.2, 0.2, 0.2, 0.4, 0.3, 0.3],
        "Name": ["setosa", "setosa", "versicolor", "versicolor", "virginica", "virginica"],
    })


def test_聚合数据_xy同名不抛异常_兜底分类计数(irisdf):
    """单元级：x==y 且非 count → 不再抛 ValueError，valid_y 被过滤为空后走分类计数兜底。"""
    df = generator._聚合数据(irisdf, "SepalLength", ["SepalLength"], None, "平均值")
    assert not df.empty
    assert "记录数" in df.columns
    # 按 SepalLength 分组统计出现次数（该场景用户要的是分布计数）
    assert df["记录数"].sum() == len(irisdf)


def test_聚合数据_y含分组字段不抛异常(irisdf):
    """y 轴同时是分组字段（与 executors.py:180-182 同源防护）：聚合不崩。"""
    df = generator._聚合数据(irisdf, "Name", ["Name"], None, "求和")
    assert not df.empty
    assert "记录数" in df.columns


def test_聚合数据_xy同名count路径仍有意义(irisdf):
    """x==y 且聚合方式为 count：按分类计数依然返回（count 不经过 valid_y，不被过滤）。"""
    df = generator._聚合数据(irisdf, "SepalLength", ["SepalLength"], None, "计数")
    assert not df.empty
    assert "记录数" in df.columns


def test_聚合数据_正常xy不受影响(irisdf):
    """正常 x≠y 聚合语义不变：按 Name 求 SepalLength 平均值。"""
    df = generator._聚合数据(irisdf, "Name", ["SepalLength"], None, "平均值")
    assert "SepalLength" in df.columns
    assert "Name" in df.columns
    # setosa 组：5.1 与 4.9 平均 = 5.0
    row = df[df["Name"] == "setosa"].iloc[0]
    assert abs(row["SepalLength"] - 5.0) < 1e-9


def test_生成报表_柱状图xy同名_返回报表不崩溃(irisdf):
    """报表级：柱状图 x==y（SepalLength 平均值）→ 不再 500/error，返回可渲染报表。"""
    r = generator.生成报表数据(
        irisdf,
        分析需求="图表类型:柱状图 按SepalLength统计SepalLength的平均值",
        图表类型="自动推荐",
        x轴="SepalLength", y轴=["SepalLength"],
        分组字段=None, 聚合方式="平均值",
    )
    assert r["报表数据"], "x==y 场景应返回分类计数的报表数据（非空）"
    assert r["图表配置"]["X轴"] == "SepalLength"
    assert "记录数" in r["报表数据"][0]
