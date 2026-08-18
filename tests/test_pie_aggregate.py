# -*- coding: utf-8 -*-
"""饼图占比 0.0% bug 回归测试。

场景：LLM 意图解析返回 图表类型=饼图、y轴=[]、聚合方式=求和（未填值字段）。
修复前：_聚合数据 空 y轴+求和 → 返回原始明细 → 前端取值列回退文本 → 占比全 0.0%。
修复后：饼图/环形图空 y轴 强制"计数"聚合 → 输出 {分类, 记录数}。
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


def _fake_llm_intent(图表类型="饼图", x轴="工作经验要求", y轴=None, 聚合方式="求和"):
    """伪造编排Agent 返回：模拟 LLM 路径的意图（空 y轴 + 求和 = bug 触发条件）。"""
    return {
        "图表类型": 图表类型,
        "x轴": x轴,
        "y轴": y轴 or [],
        "分组字段": None,
        "聚合方式": 聚合方式,
        "推荐理由": "测试",
        "筛选条件": [],
        "TopN": None,
        "对比": None,
        "意图来源": "LLM",
        "Agent_Trace": [],
        "LLM失败原因": "",
    }


@pytest.fixture
def 招聘df():
    return pd.DataFrame({
        "工作经验要求": ["一年以上", "一年以上", "两年以上", "五年以上", "五年以上", "不限"],
        "职位ID": [1001, 1002, 1003, 1004, 1005, 1006],
    })


def test_饼图空y轴强制计数聚合(monkeypatch, 招聘df):
    """LLM 给 饼图+空 y轴+求和 → 必须按分类计数，而非返回原始明细。"""
    monkeypatch.setattr(
        "后端_核心.上传报表生成器.编排Agent",
        lambda *a, **k: _fake_llm_intent(y轴=[]),
    )
    r = generator.生成报表数据(
        招聘df, 分析需求="工作经验要求占比", 图表类型="饼图",
        x轴=None, y轴=None, 聚合方式="求和",
    )
    data = r["报表数据"]
    # 3 个分类（一年以上/两年以上/五年以上/不限 → 4 类，这里数据 6 行 4 类）
    assert len(data) == 4
    assert all("记录数" in row for row in data), "必须输出聚合计数列"
    assert sum(row["记录数"] for row in data) == 6
    # 前端取值字段指向聚合列
    assert r["图表配置"].get("值") == "记录数"
    assert r["图表配置"].get("名称") == "工作经验要求"


def test_环形图空y轴同样强制计数(monkeypatch, 招聘df):
    monkeypatch.setattr(
        "后端_核心.上传报表生成器.编排Agent",
        lambda *a, **k: _fake_llm_intent(图表类型="环形图", y轴=[]),
    )
    r = generator.生成报表数据(
        招聘df, 分析需求="工作经验要求占比", 图表类型="环形图",
        x轴=None, y轴=None, 聚合方式="求和",
    )
    data = r["报表数据"]
    assert len(data) == 4
    assert all("记录数" in row for row in data)


def test_饼图有y轴时尊重聚合方式(monkeypatch, 招聘df):
    """有值字段时不强制计数，仍按 LLM 给的聚合方式（此处求和应对数值列）。"""
    monkeypatch.setattr(
        "后端_核心.上传报表生成器.编排Agent",
        lambda *a, **k: _fake_llm_intent(y轴=["职位ID"], 聚合方式="求和"),
    )
    r = generator.生成报表数据(
        招聘df, 分析需求="工作经验要求占比", 图表类型="饼图",
        x轴=None, y轴=["职位ID"], 聚合方式="求和",
    )
    data = r["报表数据"]
    assert len(data) == 4
    assert "职位ID" in data[0]  # 求和聚合保留数值列
