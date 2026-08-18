# -*- coding: utf-8 -*-
"""阶段 34 全图表回归：类饼图"明细泄漏/值列错配→全 0"问题在全部图表上的覆盖。

覆盖：
1. 通用图表（柱状图）空 y轴 → 分类计数（原返回原始明细）
2. 直方图 数值字段 → 值列指向"记录数"（原指向桶标签文本列 → 全 0）
3. 直方图 文本字段 → 分类计数（原返回原始明细）
4. 聚合分析执行器 x轴/分组字段 为 list（GLM 风格）→ 归一化不抛 unhashable
5. eval_agent._构造样例df 按画像构造可聚合样例
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心 import 上传报表生成器 as generator
from 后端_核心.agent import 执行器注册


@pytest.fixture
def 混合df():
    return pd.DataFrame({
        "地区": ["华东", "华南", "华北", "华东", "华南"],
        "销售额": [100, 120, 110, 130, 140],
        "工作经验要求": ["一年以上", "一年以上", "两年以上", "五年以上", "不限"],
    })


def test_柱状图空y轴分类计数(混合df):
    """通用图表空 y轴（LLM 漏填）→ 分类计数，而非原始明细。"""
    r = generator.生成报表数据(
        混合df, 分析需求="测试", 图表类型="柱状图",
        x轴="地区", y轴=None, 分组字段=None, 聚合方式="求和",
    )
    data = r["报表数据"]
    assert len(data) == 3  # 华东/华南/华北
    assert "记录数" in data[0]
    assert sum(row["记录数"] for row in data) == 5


def test_直方图数值字段值列指向记录数(混合df):
    """直方图数值字段：数据=[桶标签,记录数]，y轴 必须指向记录数。"""
    r = generator.生成报表数据(
        混合df, 分析需求="测试", 图表类型="直方图",
        x轴="销售额", y轴=["销售额"], 分组字段=None, 聚合方式="求和",
    )
    data = r["报表数据"]
    assert data, "直方图应有数据"
    assert "记录数" in data[0]
    assert r["图表配置"].get("Y轴") == ["记录数"]


def test_直方图文本字段分类计数(混合df):
    """直方图文本字段：按分类计数，而非原始明细。"""
    r = generator.生成报表数据(
        混合df, 分析需求="测试", 图表类型="直方图",
        x轴="工作经验要求", y轴=None, 分组字段=None, 聚合方式="求和",
    )
    data = r["报表数据"]
    assert len(data) == 4  # 一年以上/两年以上/五年以上/不限
    assert any("记录数" in row or "count" in row for row in data)


def test_聚合执行器x轴list归一化():
    """GLM 把 X轴 返回为数组 → 归一化为字符串，不抛 unhashable。"""
    df = pd.DataFrame({"地区": ["华东", "华南"] * 2, "销售额": [1, 2, 3, 4]})
    ctx = {"df": df, "画像": {"字段列表": ["地区", "销售额"], "数值字段": ["销售额"], "分类字段": ["地区"]}}
    # 修复前：x轴=["地区"] 参与 set 判断抛 unhashable type: 'list'
    result = 执行器注册._聚合分析_executor({"X轴": ["地区"], "Y轴": ["销售额"], "聚合方式": "求和"}, ctx)
    assert result is not None
    assert "数据摘要" in result


def test_聚合执行器分组字段list归一化():
    df = pd.DataFrame({"地区": ["华东", "华南"] * 2, "销售额": [1, 2, 3, 4]})
    ctx = {"df": df, "画像": {"字段列表": ["地区", "销售额"], "数值字段": ["销售额"], "分类字段": ["地区"]}}
    result = 执行器注册._聚合分析_executor(
        {"X轴": "地区", "Y轴": ["销售额"], "分组字段": ["地区"], "聚合方式": "求和"}, ctx
    )
    assert result is not None


def test_eval构造样例df():
    """eval_agent._构造样例df 按画像生成可聚合 DataFrame（字段对齐/可数值化）。"""
    from scripts import eval_agent
    import importlib
    importlib.reload(eval_agent)
    画像 = {
        "字段列表": ["地区", "销售额", "月份"],
        "数值字段": ["销售额"],
        "分类字段": ["地区"],
        "日期字段": ["月份"],
    }
    df = eval_agent._构造样例df(画像)
    assert len(df) == 60
    assert list(df.columns) == ["地区", "销售额", "月份"]
    assert pd.api.types.is_numeric_dtype(df["销售额"])
    # 可正常聚合（第 2 轮聚合分析不再因 df=None 降级）
    grouped = df.groupby("地区").size()
    assert grouped.sum() == 60