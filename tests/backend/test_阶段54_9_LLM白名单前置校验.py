# -*- coding: utf-8 -*-
"""阶段 54-9 · Fix L1（LLM P2-2）：M25 图表白名单前置校验。

走查证据（_stage52_llm_vcr/报告.md P2-2，复现 3b2）：
- `_从消息提取意图` 先由 tool 内容行「推荐图表：3D饼图」置 chart_type，
  白名单分支只做「同值覆盖」（`if _候选图表 in _图表类型白名单` 才覆盖，
  否则保留原值）→ 幻觉值「3D饼图」直通响应（超前端枚举），引擎静默回退 table。

修复语义：tool 内容解析出的图表名**必须命中 `_图表类型白名单` 才采纳**，
否则不采纳（保持 None/未置 → 走后续语义推断或自动推荐）；聚合参数
（推荐图表 tool_call args）同样前置校验。枚举外 → 静默走自动推荐（不 500）。
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.agent.orchestrator import _从消息提取意图, _图表类型白名单  # noqa: E402


def _画像() -> Dict[str, Any]:
    return {
        "行数": 6,
        "列数": 4,
        "字段列表": ["月份", "地区", "销售额", "订单数"],
        "数值字段": ["销售额", "订单数"],
        "日期字段": ["月份"],
        "分类字段": ["地区"],
        "文本字段": [],
        "数据质量": {"评级": "A", "等级": "优秀"},
    }


def _消息(图表类型: str, 理由: str = "测试理由") -> List[Dict[str, Any]]:
    """构造「推荐图表」tool_call + 其结果 tool 消息（对齐 _结果转文本 的输出形态）。"""
    return [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_3",
                "type": "function",
                "function": {
                    "name": "推荐图表",
                    "arguments": json.dumps({"图表类型": 图表类型, "理由": 理由}, ensure_ascii=False),
                },
            }],
        },
        {
            "role": "tool",
            "tool_call_id": "call_3",
            "content": f"推荐图表：{图表类型}\n理由：{理由}",
        },
    ]


# ---- 前置校验：tool 内容行 ---------------------------------------------------

def test_tool内容_幻觉3D饼图_白名单外不采纳():
    """tool 内容「推荐图表：3D饼图」→ 图表类型不采纳（返回 None → 自动推荐兜底）。"""
    意图 = _从消息提取意图(_消息("3D饼图"), _画像())
    assert 意图 is None, f"幻觉图表类型不应进结论：{意图}"


def test_tool内容_合法饼图_采纳():
    意图 = _从消息提取意图(_消息("饼图"), _画像())
    assert 意图 is not None
    assert 意图["图表类型"] == "饼图"


def test_tool内容_箱型图非枚举_不采纳():
    """「箱型图」不在白名单（白名单是「箱线图」）→ 不采纳。"""
    意图 = _从消息提取意图(_消息("箱型图"), _画像())
    assert 意图 is None, f"非枚举图表不应进结论：{意图}"


# ---- 聚合参数（推荐图表 tool_call args）前置校验 --------------------------------

def test聚合参数_热力图_采纳():
    意图 = _从消息提取意图(_消息("热力图"), _画像())
    assert 意图 is not None
    assert 意图["图表类型"] == "热力图"


def test聚合参数_箱型图非枚举_不采纳():
    意图 = _从消息提取意图(_消息("箱型图"), _画像())
    assert 意图 is None


def test_tool内容幻觉_args合法_取合法值():
    """tool 内容为幻觉值、args 为合法值 → 采纳合法值（args 覆盖幻觉内容）。"""
    消息 = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_3", "type": "function",
                "function": {"name": "推荐图表",
                             "arguments": json.dumps({"图表类型": "饼图", "理由": "合法"}, ensure_ascii=False)},
            }],
        },
        {"role": "tool", "tool_call_id": "call_3", "content": "推荐图表：3D饼图\n理由：幻觉"},
    ]
    意图 = _从消息提取意图(消息, _画像())
    assert 意图 is not None
    assert 意图["图表类型"] == "饼图", f"args 合法值应被采纳：{意图}"


def test_tool内容合法_args幻觉_保留合法值():
    """tool 内容为合法值、args 为幻觉值 → 保留 tool 内容的合法值。"""
    消息 = [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_3", "type": "function",
                "function": {"name": "推荐图表",
                             "arguments": json.dumps({"图表类型": "3D饼图", "理由": "幻觉"}, ensure_ascii=False)},
            }],
        },
        {"role": "tool", "tool_call_id": "call_3", "content": "推荐图表：饼图\n理由：合法"},
    ]
    意图 = _从消息提取意图(消息, _画像())
    assert 意图 is not None
    assert 意图["图表类型"] == "饼图"


# ---- 白名单一致性 ------------------------------------------------------------

def test_采纳值恒在白名单():
    """任意合法输入采纳出的图表类型必须 ∈ 白名单。"""
    for 名称 in ("柱状图", "折线图", "面积图", "饼图", "环形图", "散点图", "直方图",
                 "热力图", "词云图", "漏斗图", "桑基图", "箱线图", "瀑布图", "旭日图",
                 "K线图", "表格", "堆积柱状图"):
        意图 = _从消息提取意图(_消息(名称), _画像())
        assert 意图 is not None and 意图["图表类型"] == 名称
    assert "3D饼图" not in _图表类型白名单, "白名单不应含幻觉图表"
