# -*- coding: utf-8 -*-
"""阶段 53 · A4：Agent 决策流（用户可见）不得出现开发术语。

缺陷（用户走查观察）：报表"Agent 决策流"里直接显示
「受控语句命中，跳过 LLM」「快速路由命中，跳过 LLM」——
"受控语句/快速路由/跳过 LLM" 是内部实现术语，普通用户看不懂。
期望：trace 说明改为用户能理解的行为描述，且不再出现"跳过 LLM"字样。
"""

from typing import Any, Dict

import pytest

from 后端_核心.agent import orchestrator as 编排器_mod
from 后端_核心.agent import llm_client as llm客户端_mod


@pytest.fixture(autouse=True)
def _启用LLM(monkeypatch):
    """编排Agent 内部会用 is_llm_configured 覆盖传入的 enable_llm（line 242-251）；
    测试环境默认占位 key 会让它静默降级、根本走不到受控语句/快速路由分支（假绿）。
    这里给非占位 key，且受控/快速路由命中后不进入 LLM ReAct，不产生外网调用。"""
    monkeypatch.setattr(llm客户端_mod.EnvConfig, "LLM_API_KEY", "sk-real-key-xxxx")


@pytest.fixture
def 画像() -> Dict[str, Any]:
    return {
        "行数": 100,
        "列数": 4,
        "字段列表": ["月份", "地区", "销售额", "订单数"],
        "字段类型": {
            "月份": "datetime64[ns]",
            "地区": "object",
            "销售额": "int64",
            "订单数": "int64",
        },
        "数值字段": ["销售额", "订单数"],
        "日期字段": ["月份"],
        "分类字段": ["地区"],
        "数据质量": {"等级": "良好"},
    }


def test_受控语句命中_trace说明为用户语言(画像):
    """受控语句命中（明确图表词）→ trace 说明不含"跳过 LLM"等开发术语。"""
    意图 = 编排器_mod.编排Agent(画像, "按地区统计销售额，用直方图展示", enable_llm=True)
    assert 意图 is not None
    说明列表 = [s.get("说明") or "" for s in 意图["Agent_Trace"]]
    for 说明 in 说明列表:
        assert "跳过 LLM" not in 说明, f"用户可见 trace 出现开发术语：{说明}"
        assert "受控语句" not in 说明, f"用户可见 trace 出现内部术语：{说明}"
    assert any("直方图" in 说明 or "直接" in 说明 or "关键词" in 说明 for 说明 in 说明列表), 说明列表


def test_快速路由命中_trace说明为用户语言(画像):
    """快速路由命中（占比/趋势等通用意图）→ 同样不得出现"跳过 LLM"。"""
    意图 = 编排器_mod.编排Agent(画像, "各地区销售额占比", enable_llm=True)
    assert 意图 is not None
    说明列表 = [s.get("说明") or "" for s in 意图["Agent_Trace"]]
    for 说明 in 说明列表:
        assert "跳过 LLM" not in 说明, f"用户可见 trace 出现开发术语：{说明}"
    # 推荐理由同样面向用户，不得出现开发术语
    assert "跳过 LLM" not in (意图.get("推荐理由") or ""), 意图.get("推荐理由")