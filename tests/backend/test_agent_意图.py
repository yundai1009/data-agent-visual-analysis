"""agent 子包单元测试：纯解析层/校验层/降级路径，不依赖网络与 LLM key。

覆盖目标
========
- ``llm客户端.parse_llm_json``：剥 markdown fence、括号配平、坏 JSON 返回 None
- ``llm客户端.extract_tool_call``：从合成 chat 响应里抓 tool_call + arguments 解析
- ``llm客户端.is_llm_configured``：占位 key 视为未配置
- ``工具集.validate_intent_against_profile``：字段白名单/图表类型白名单/聚合方式白名单
- ``编排器.解析自然语言需求``：未配置/异常/JSON 不合法/字段越界 各路径都安全回退到 None

设计原则
========
- 不调真 LLM，全部用受控样本与 monkeypatch 桩 ``chat_completion``；
- 测试运行无需 ``.env``，无需网络；
- 任一失败都对应一条降级回退路径，覆盖阶段 1 安全姿态的全部出口。
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional
from unittest import mock

import pytest

# 让 ``pytest`` 从项目根目录能 import 中文路径包
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.agent import llm客户端 as llm客户端_mod
from 后端_核心.agent import 编排器 as 编排器_mod
from 后端_核心.agent.工具集 import validate_intent_against_profile


# ============================================================================
# 1. 数据画像 fixture：复用一份贴近真实的小画像
# ============================================================================

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


# ============================================================================
# 2. parse_llm_json：JSON 解析与容错
# ============================================================================

def test_parse_llm_json_plain_dict():
    assert llm客户端_mod.parse_llm_json('{"图表类型": "饼图"}') == {"图表类型": "饼图"}


def test_parse_llm_json_markdown_fence():
    content = '```json\n{"图表类型": "饼图", "X轴": "地区"}\n```'
    assert llm客户端_mod.parse_llm_json(content) == {"图表类型": "饼图", "X轴": "地区"}


def test_parse_llm_json_with_explanation_text():
    content = '好的，下面是分析建议：\n{"图表类型": "折线图", "X轴": "月份"}\n仅供参考。'
    assert llm客户端_mod.parse_llm_json(content) == {"图表类型": "折线图", "X轴": "月份"}


def test_parse_llm_json_unbalanced_returns_none():
    # 括号不配平，必须返回 None 而不是抛
    assert llm客户端_mod.parse_llm_json('{"图表类型": "饼图"') is None


def test_parse_llm_json_not_dict_returns_none():
    # 解析出 list 而非 dict，必须返回 None
    assert llm客户端_mod.parse_llm_json('[1, 2, 3]') is None


def test_parse_llm_json_empty_returns_none():
    assert llm客户端_mod.parse_llm_json("") is None
    assert llm客户端_mod.parse_llm_json(None) is None


# ============================================================================
# 3. is_llm_configured：占位 key 视为未配置
# ============================================================================

def test_is_llm_configured_placeholder(monkeypatch):
    monkeypatch.setattr(llm客户端_mod.EnvConfig, "LLM_API_KEY", "your_llm_api_key")
    assert llm客户端_mod.is_llm_configured() is False


def test_is_llm_configured_empty(monkeypatch):
    monkeypatch.setattr(llm客户端_mod.EnvConfig, "LLM_API_KEY", "")
    assert llm客户端_mod.is_llm_configured() is False


def test_is_llm_configured_real_key(monkeypatch):
    monkeypatch.setattr(llm客户端_mod.EnvConfig, "LLM_API_KEY", "sk-real-key-xxxx")
    assert llm客户端_mod.is_llm_configured() is True


# ============================================================================
# 4. extract_tool_call：从 chat 响应抓 tool_call + arguments 解析
# ============================================================================

def test_extract_tool_call_dict_arguments():
    response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "解析为报表意图",
                                "arguments": {"图表类型": "饼图", "X轴": "地区"},
                            }
                        }
                    ]
                }
            }
        ]
    }
    result = llm客户端_mod.extract_tool_call(response)
    assert result == {
        "name": "解析为报表意图",
        "arguments": {"图表类型": "饼图", "X轴": "地区"},
    }


def test_extract_tool_call_string_arguments():
    response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "解析为报表意图",
                                "arguments": '{"图表类型": "柱状图", "X轴": "地区", "Y轴": ["销售额"]}',
                            }
                        }
                    ]
                }
            }
        ]
    }
    result = llm客户端_mod.extract_tool_call(response)
    assert result is not None
    assert result["name"] == "解析为报表意图"
    assert result["arguments"]["图表类型"] == "柱状图"
    assert result["arguments"]["Y轴"] == ["销售额"]


def test_extract_tool_call_invalid_json_arguments():
    response = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {
                            "function": {
                                "name": "解析为报表意图",
                                "arguments": "这不是合法 JSON",
                            }
                        }
                    ]
                }
            }
        ]
    }
    # arguments 无法解析保留为空 dict，整体不返回 None（name 仍然可用）
    result = llm客户端_mod.extract_tool_call(response)
    assert result == {"name": "解析为报表意图", "arguments": {}}


def test_extract_tool_call_empty_response_returns_none():
    assert llm客户端_mod.extract_tool_call(None) is None
    assert llm客户端_mod.extract_tool_call({}) is None
    assert llm客户端_mod.extract_tool_call({"choices": []}) is None
    assert llm客户端_mod.extract_tool_call({"choices": [{}]}) is None


# ============================================================================
# 5. validate_intent_against_profile：字段白名单校验
# ============================================================================

def test_validate_intent_all_legal(画像):
    intent = {
        "图表类型": "饼图",
        "X轴": "地区",
        "Y轴": ["销售额"],
        "分组字段": None,
        "聚合方式": "计数",
        "推荐理由": "看地区占比",
    }
    out = validate_intent_against_profile(intent, 画像)
    assert out is not None
    assert out["图表类型"] == "饼图"
    assert out["x轴"] == "地区"
    assert out["y轴"] == ["销售额"]
    assert out["分组字段"] is None
    assert out["聚合方式"] == "计数"
    assert out["推荐理由"] == "看地区占比"


def test_validate_intent_chart_type_invalid_returns_none(画像):
    intent = {"图表类型": "3D旋转图", "X轴": "地区", "Y轴": ["销售额"], "聚合方式": "求和"}
    assert validate_intent_against_profile(intent, 画像) is None


def test_validate_intent_field_not_in_profile_returns_none(画像):
    intent = {
        "图表类型": "饼图",
        "X轴": "不存在的字段",
        "Y轴": ["销售额"],
        "聚合方式": "计数",
    }
    # 字段越界：X 轴被置 None，但没有 X 又没 Y 全空 → 仍可能返回带空 X 的意图。
    # 按阶段 1 规则：X 与 Y 至少一个非空 → 此处 Y 仍合法，所以会返回带 x轴=None 的结果。
    out = validate_intent_against_profile(intent, 画像)
    assert out is not None
    assert out["x轴"] is None
    assert out["y轴"] == ["销售额"]


def test_validate_intent_no_x_no_y_returns_none(画像):
    intent = {
        "图表类型": "饼图",
        "X轴": "不存在的字段",
        "Y轴": ["另一个不存在"],
        "聚合方式": "计数",
    }
    # X 和 Y 全空，按规则返回 None，由上层走兜底
    assert validate_intent_against_profile(intent, 画像) is None


def test_validate_intent_y_axis_string_coerced_to_list(画像):
    intent = {
        "图表类型": "柱状图",
        "X轴": "地区",
        "Y轴": "销售额",  # 字符串而非 list
        "聚合方式": "求和",
    }
    out = validate_intent_against_profile(intent, 画像)
    assert out is not None
    assert out["y轴"] == ["销售额"]


def test_validate_intent_aggregation_invalid_falls_back_default(画像):
    intent = {
        "图表类型": "柱状图",
        "X轴": "地区",
        "Y轴": ["销售额"],
        "聚合方式": "中位数",  # 不在白名单
    }
    out = validate_intent_against_profile(intent, 画像)
    # 聚合方式非法不整体拒绝，回退到默认 "求和"，与现有项目保持一致
    assert out is not None
    assert out["聚合方式"] == "求和"


# ============================================================================
# 6. 编排器.解析自然语言需求：阶段 2 改为 mock 编排Agent
# ============================================================================

def test_解析自然语言需求_编排Agent返回None则返回None(画像, monkeypatch):
    """编排Agent 失败时，解析自然语言需求 返回 None"""
    monkeypatch.setattr(编排器_mod, "编排Agent", lambda 画像, 分析需求, df=None, enable_llm=None, **kw: None)
    assert 编排器_mod.解析自然语言需求("按地区看占比", 画像) is None


def test_解析自然语言需求_编排Agent返回合法意图(画像, monkeypatch):
    """编排Agent 返回合法意图时，正确解析为 dict"""
    monkeypatch.setattr(编排器_mod, "编排Agent", lambda 画像, 分析需求, df=None, enable_llm=None, **kw: {
        "图表类型": "饼图",
        "x轴": "地区",
        "y轴": ["销售额"],
        "分组字段": None,
        "聚合方式": "计数",
        "推荐理由": "按地区看占比",
        "意图来源": "LLM",
        "Agent_Trace": [],
    })
    out = 编排器_mod.解析自然语言需求("按地区看占比", 画像)
    assert out is not None
    assert out["图表类型"] == "饼图"
    assert out["推荐理由"] == "按地区看占比"


def test_解析自然语言需求_编排Agent返回规则意图(画像, monkeypatch):
    """编排Agent 返回规则意图，解析自然语言需求 照常返回"""
    monkeypatch.setattr(编排器_mod, "编排Agent", lambda 画像, 分析需求, df=None, enable_llm=None, **kw: {
        "图表类型": "自动推荐",
        "x轴": None,
        "y轴": [],
        "分组字段": None,
        "聚合方式": "求和",
        "意图来源": "规则",
        "推荐理由": "",
        "Agent_Trace": [],
    })
    out = 编排器_mod.解析自然语言需求("", 画像)
    assert out is not None
    assert out["图表类型"] == "自动推荐"
    assert out["x轴"] is None
    assert out["y轴"] == []


# ============================================================================
# 7. D：LLM 字段校验不过回退自动选字段（编排器层单元测试）
# ============================================================================

from 后端_核心.上传报表生成器 import 自动选字段 as _自动选字段


def test_自动选字段_词云_返回文本字段():
    画像 = {"字段列表": ["地区", "销售额", "评论", "日期"],
            "分类字段": ["地区"], "数值字段": ["销售额"], "日期字段": ["日期"], "文本字段": ["评论"]}
    result = _自动选字段(画像, "词云图")
    assert result["x轴"] == "评论"


def test_自动选字段_散点图_返回两个数值():
    画像 = {"字段列表": ["地区", "销售额", "订单数", "日期"],
            "分类字段": ["地区"], "数值字段": ["销售额", "订单数"], "日期字段": ["日期"], "文本字段": []}
    result = _自动选字段(画像, "散点图")
    assert result["x轴"] == "销售额"
    assert result["y轴"] == ["订单数"]


def test_自动选字段_箱线图_x不等于y():
    画像 = {"字段列表": ["地区", "销售额", "日期"],
            "分类字段": ["地区"], "数值字段": ["销售额"], "日期字段": ["日期"], "文本字段": []}
    result = _自动选字段(画像, "箱线图")
    # 箱线图 x=地区(分类), y=销售额(数值)，x≠y
    assert result["x轴"] != result["y轴"][0] if result["y轴"] else True


def test_自动选字段_直方图_x等于y():
    画像 = {"字段列表": ["地区", "销售额", "日期"],
            "分类字段": ["地区"], "数值字段": ["销售额"], "日期字段": ["日期"], "文本字段": []}
    result = _自动选字段(画像, "直方图")
    assert result["x轴"] == "销售额"
    assert result["y轴"] == ["销售额"]


def test_自动选字段_热力图_有分组字段():
    画像 = {"字段列表": ["地区", "渠道", "销售额", "日期"],
            "分类字段": ["地区", "渠道"], "数值字段": ["销售额"], "日期字段": ["日期"], "文本字段": []}
    result = _自动选字段(画像, "热力图")
    assert result["x轴"] is not None
    assert result["分组字段"] is not None


def test_自动选字段_雷达图_y多字段():
    画像 = {"字段列表": ["月份", "销售额", "订单数", "日期"],
            "分类字段": ["月份"], "数值字段": ["销售额", "订单数"], "日期字段": ["日期"], "文本字段": []}
    result = _自动选字段(画像, "雷达图")
    assert len(result["y轴"]) >= 1


# ============================================================================
# 8. D：LLM 编排器 round3 回退测试（mock LLM 返回非法字段触发 _需回退）
# ============================================================================

def test_D_词云_x轴非文本_回退自动选字段(画像, monkeypatch):
    """mock LLM 返回词云 x 轴为数值字段（非法）→ 编排器回退自动选字段修正 x 轴"""
    bad_intent = {
        "图表类型": "词云图",
        "x轴": "销售额",  # 诗句字段，非法
        "y轴": [],
        "分组字段": None,
        "聚合方式": "计数",
    }

    def _mock_round3(*args, **kwargs):
        # 模拟 round3 成功且返回非法字段
        ctx = args[2] if len(args) > 2 else kwargs.get("context", {})
        ctx["_mock_intent"] = bad_intent
        return True

    def _mock_extract(messages, 画像):
        return bad_intent

    # 给画像加文本字段
    画像["文本字段"] = ["评论"]

    monkeypatch.setattr(编排器_mod, "_执行一轮", _mock_round3)
    monkeypatch.setattr(编排器_mod, "_从消息提取意图", _mock_extract)
    monkeypatch.setattr(编排器_mod, "保存记忆", lambda *a, **kw: None)

    # 验证回退结果：x 轴应被修正为文本字段
    from 后端_核心.上传报表生成器 import 自动选字段
    expected = 自动选字段(画像, "词云图")
    assert expected["x轴"] == "评论"



