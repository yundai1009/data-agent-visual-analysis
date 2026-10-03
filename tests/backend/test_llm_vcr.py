"""LLM 链路 VCR 回放测试（阶段 50）：走真实 chat_completion + 编排器，离线回放。

背景
====
- 现有 227 测试的 LLM 路径全部 monkeypatch 桩掉 chat_completion（见 test_agent_意图.py），
  真实「HTTP 请求 → JSON 解析 → 工具调用提取 → ReAct 编排」这条链路从没被测试过；
- 本文件用自研 cassette（backend/llm_cassette.py）在 **requests.post 层**回放
  录制好的响应，让智能路径在 CI（无 key、无网络）上可回归。

模式
====
- 回放（默认，CI）：读 tests/cassettes/<scenario>/<指纹>.json，未命中抛 CassetteMiss；
- 录制（真实 Key，用户本机）：
    LLM_VCR_RECORD=1 LLM_VCR_API_KEY=sk-xxx LLM_VCR_BASE_URL=... LLM_VCR_MODEL=... \\
    python -m pytest tests/backend/test_llm_vcr.py
- 黄金样本（无 Key，脚本响应落盘）：
    python scripts/generate_llm_goldens.py

注意
====
- 记忆链路（检索/保存/清理/embedding）全部打桩，避免 chromadb 把 cassette 范围污染；
- 录制时模型实际选了什么字段/图表不保证与黄金一致——断言只校验不变量
  （意图来源 / 白名单图表 / 字段在画像内 / trace 非空），黄金样本管精确值。
"""

import json
import os
import sys
from contextlib import contextmanager
from typing import Any, Dict, List
from unittest import mock

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(PROJECT_ROOT, "tests")
for _p in (PROJECT_ROOT, TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from 后端_核心.agent.llm_client import chat_completion, extract_tool_call  # noqa: E402
from 后端_核心.agent.orchestrator import 编排Agent  # noqa: E402
from backend.llm_cassette import CASSETTES_ROOT, CassetteMiss, LLMCassette  # noqa: E402
from config.settings import LLMRequestConfig  # noqa: E402

# 与编排器 _图表类型白名单 对齐的本地断言白名单（避免引用模块私有常量）
_图表白名单 = {
    "柱状图", "折线图", "面积图", "饼图", "环形图", "散点图", "直方图",
    "热力图", "词云图", "漏斗图", "桑基图", "箱线图", "瀑布图", "旭日图",
    "K线图", "表格", "堆积柱状图", "自动推荐",
}

# 黄金样本默认供应商（与 config/providers.toml 的 deepseek 一致）；
# 录制时可用环境变量覆盖（LLM_VCR_BASE_URL / LLM_VCR_MODEL / LLM_VCR_API_KEY）。
_DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
_DEFAULT_MODEL = "deepseek-chat"


# ============================================================================
# 共享样本：画像 / df / llm 配置（黄金生成器与回放测试必须一致）
# ============================================================================

def 样本画像() -> Dict[str, Any]:
    return {
        "行数": 6,
        "列数": 4,
        "字段列表": ["月份", "地区", "销售额", "订单数"],
        "字段类型": {
            "月份": "object",
            "地区": "object",
            "销售额": "int64",
            "订单数": "int64",
        },
        "数值字段": ["销售额", "订单数"],
        "日期字段": ["月份"],
        "分类字段": ["地区"],
        "文本字段": [],
        "数据质量": {"等级": "良好", "评级": "良好", "等级说明": "完整无缺失"},
    }


def 样本df() -> pd.DataFrame:
    return pd.DataFrame({
        "月份": ["2026-01", "2026-01", "2026-02", "2026-02", "2026-03", "2026-03"],
        "地区": ["华东", "华南", "华东", "华南", "华东", "华南"],
        "销售额": [100, 80, 120, 90, 110, 95],
        "订单数": [10, 8, 12, 9, 11, 9],
    })


def 测试llm配置() -> LLMRequestConfig:
    """回放用固定配置；录制时由环境变量注入真实 Key / 供应商。"""
    return LLMRequestConfig(
        provider="deepseek",
        base_url=os.getenv("LLM_VCR_BASE_URL", _DEFAULT_BASE_URL),
        model=os.getenv("LLM_VCR_MODEL", _DEFAULT_MODEL),
        api_key=os.getenv("LLM_VCR_API_KEY", "sk-replay"),
    )


# ============================================================================
# 记忆链路打桩：VCR 只测 chat_completion HTTP 层，chromadb 不参与
# ============================================================================

@contextmanager
def 记忆桩():
    from 后端_核心.agent import memory as 记忆模块
    from 后端_核心.agent import orchestrator as 编排器模块
    with (
        mock.patch.object(编排器模块, "检索相似记忆", return_value=[]),
        mock.patch.object(编排器模块, "保存记忆", return_value=None),
        mock.patch.object(编排器模块, "生成_few_shot_prompt", return_value=""),
        mock.patch.object(记忆模块, "清理记忆", return_value=0),
    ):
        yield


# ============================================================================
# 脚本响应（黄金样本内容）：按调用序返回 OpenAI 格式 dict
# ============================================================================

def _工具响应(tool_name: str, arguments: Dict[str, Any], call_id: str) -> Dict[str, Any]:
    return {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion",
        "created": 0,
        "model": _DEFAULT_MODEL,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _文字响应(content: str) -> Dict[str, Any]:
    return {
        "id": "chatcmpl-text",
        "object": "chat.completion",
        "created": 0,
        "model": _DEFAULT_MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def 脚本_完整三轮(url: str, payload: Dict[str, Any], call_index: int) -> Dict[str, Any]:
    """轮1 画像 → 轮2 聚合 → 轮3 推荐图表（黄金：饼图/地区/销售额）。"""
    if call_index == 0:
        return _工具响应("获取数据画像", {}, "call_1")
    if call_index == 1:
        return _工具响应(
            "聚合分析",
            {"X轴": "地区", "Y轴": ["销售额"], "聚合方式": "求和", "前N行": 5},
            "call_2",
        )
    return _工具响应(
        "推荐图表",
        {"图表类型": "饼图", "理由": "地区销售构成适合饼图展示"},
        "call_3",
    )


def 脚本_首轮失败(url: str, payload: Dict[str, Any], call_index: int) -> Dict[str, Any]:
    """第 1 轮 LLM 只回文字、不调工具 → 应触发整体降级到规则。"""
    return _文字响应("抱歉，我无法完成这项分析。")


def 脚本_工具调用提取(url: str, payload: Dict[str, Any], call_index: int) -> Dict[str, Any]:
    """单次调用：聚合分析，arguments 为 JSON 字符串（OpenAI 典型形态）。"""
    return _工具响应(
        "聚合分析",
        {"X轴": "地区", "Y轴": ["销售额"], "聚合方式": "求和"},
        "call_1",
    )


# ============================================================================
# pytest fixture：拦 requests.post → LLMCassette（scenario 由 indirect 参数化）
# ============================================================================

@pytest.fixture
def llm_vcr(monkeypatch, request):
    import requests as requests_mod
    scenario = getattr(request, "param", "default")
    cassette = LLMCassette(scenario=scenario)
    monkeypatch.setattr(requests_mod, "post", cassette.wrap(requests_mod.post))
    return cassette


# ============================================================================
# 黄金样本录制入口（scripts/generate_llm_goldens.py 调用，无网络）
# ============================================================================

_脚本表: Dict[str, Any] = {
    "react_multi_round": 脚本_完整三轮,
    "degrade_round1": 脚本_首轮失败,
    "tool_call_direct": 脚本_工具调用提取,
}


def 录制黄金样本(scenarios: List[str]) -> Dict[str, int]:
    """以脚本响应录制指定场景的 cassette（真实指纹，供回放测试使用）。"""
    import requests as requests_mod
    recorded: Dict[str, int] = {}
    for scenario in scenarios:
        if scenario not in _脚本表:
            raise ValueError(f"未知场景：{scenario}")
        cassette = LLMCassette(scenario, script=_脚本表[scenario])
        real_post = requests_mod.post
        requests_mod.post = cassette.wrap(real_post)
        try:
            if scenario in ("react_multi_round", "degrade_round1"):
                with 记忆桩():
                    编排Agent(
                        样本画像(), "帮我看看这份数据整体怎么样",
                        df=样本df(), enable_llm=True,
                        llm_config=测试llm配置(), user_id="golden",
                    )
            elif scenario == "tool_call_direct":
                chat_completion(
                    messages=[{"role": "user", "content": "按地区统计销售额"}],
                    tools=[], tool_choice="auto", llm_config=测试llm配置(),
                )
        finally:
            requests_mod.post = real_post
        recorded[scenario] = len(list((CASSETTES_ROOT / scenario).glob("*.json")))
    return recorded


# ============================================================================
# 回放测试
# ============================================================================

@pytest.mark.parametrize("llm_vcr", ["react_multi_round"], indirect=True)
def test_多轮回放_意图来源LLM(llm_vcr):
    """三轮 ReAct 走真实 chat_completion 回放：意图来源=LLM、字段在画像内、trace 非空。"""
    with 记忆桩():
        result = 编排Agent(
            样本画像(), "帮我看看这份数据整体怎么样",
            df=样本df(), enable_llm=True,
            llm_config=测试llm配置(), user_id="u1",
        )
    assert result is not None
    assert result["意图来源"] == "LLM"
    assert result["图表类型"] in _图表白名单
    assert result["x轴"] in 样本画像()["字段列表"]
    assert set(result["y轴"]).issubset(样本画像()["字段列表"])
    assert result["Agent_Trace"], "LLM 路径应产出推理 trace"


@pytest.mark.parametrize("llm_vcr", ["degrade_round1"], indirect=True)
def test_首轮LLM只回文字_真实HTTP层触发降级(llm_vcr):
    """LLM 第 1 轮不调工具 → 编排器降级规则兜底（经真实 chat_completion 返回）。"""
    with 记忆桩():
        result = 编排Agent(
            样本画像(), "帮我看看这份数据整体怎么样",
            df=样本df(), enable_llm=True,
            llm_config=测试llm配置(), user_id="u1",
        )
    assert result is not None
    assert result["意图来源"] == "规则"
    assert result["图表类型"] in _图表白名单


@pytest.mark.parametrize("llm_vcr", ["tool_call_direct"], indirect=True)
def test_HTTP层工具调用提取_字符串arguments解析(llm_vcr):
    """真实 chat_completion 响应 → extract_tool_call：arguments JSON 字符串正确解析。"""
    resp = chat_completion(
        messages=[{"role": "user", "content": "按地区统计销售额"}],
        tools=[], tool_choice="auto", llm_config=测试llm配置(),
    )
    tc = extract_tool_call(resp)
    assert tc is not None
    assert tc["name"] == "聚合分析"
    assert tc["arguments"]["X轴"] == "地区"
    assert tc["arguments"]["Y轴"] == ["销售额"]


def test_回放未命中抛CassetteMiss():
    """缺失 cassette 时必须抛 CassetteMiss——保证 CI 只红、不假绿。"""
    cassette = LLMCassette("missing_scenario_xyz")
    wrapped = cassette.wrap(lambda *a, **k: pytest.fail("回放模式不应发起真实请求"))
    with pytest.raises(CassetteMiss):
        wrapped(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": "Bearer sk"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": "x"}]},
        )