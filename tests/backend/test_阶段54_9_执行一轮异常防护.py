# -*- coding: utf-8 -*-
"""阶段 54-9 · Fix L2（LLM P2-3）：_执行一轮 中段异常 trace 证据链保留。

走查证据（_stage52_llm_vcr/报告.md P2-3，复现 5b/1x）：
- `_执行一轮` 对 `chat_completion` 无 try/except，CassetteMiss 穿透 →
  整段 trace（含轮 1 命中证据）丢弃，报表显示模板 trace 与规则路径不可区分。

修复语义：LLM 调用包 try/except——捕获异常（Exception，含 CassetteMiss）→
`trace.记录LLM调用(状态="失败", 理由=str(e))` → 返回 False（上层决定降级/重试）；
工具执行部分保持原语义，不吞其他必需异常。
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.agent import orchestrator as 编排器_mod  # noqa: E402
from 后端_核心.agent.trace import TraceRecorder  # noqa: E402
from backend.llm_cassette import CassetteMiss  # noqa: E402


def _文字响应(content: str) -> Dict[str, Any]:
    return {
        "id": "chatcmpl-text", "object": "chat.completion", "created": 0,
        "model": "deepseek-chat",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
    }


def _基础消息() -> List[Dict[str, Any]]:
    return [{"role": "user", "content": "帮我看看这份数据整体怎么样"}]


def test_执行一轮_LLM调用抛异常_返回False且trace含失败记录():
    """chat_completion 抛异常（CassetteMiss）→ False + trace 失败记录（轮次正确）。"""
    trace = TraceRecorder()
    with mock.patch.object(编排器_mod, "chat_completion",
                           side_effect=CassetteMiss("cassette 缺失: tests/cassettes/x/abc.json")):
        ok = 编排器_mod._执行一轮(
            _基础消息(), tools=[], context={}, 轮次=1, trace=trace,
        )
    assert ok is False
    记录 = trace.to_list()
    assert 记录, "异常路径也必须留下 trace 证据"
    失败 = [r for r in 记录 if r["步骤"] == "LLM推理" and r["状态"] == "失败"]
    assert 失败, f"trace 应含 LLM 失败记录：{记录}"
    assert 失败[0]["轮次"] == 1
    assert "cassette 缺失" in 失败[0]["理由"], f"失败理由应透传异常信息：{失败[0]}"


def test_执行一轮_重试分支异常_返回False且trace含轮次2失败():
    """轮 2 重试分支（先回文字再调用）抛异常 → False + 轮次 2 失败记录。"""
    calls: List[str] = []

    def fake_chat(messages, **kw):
        calls.append(1)
        if len(calls) == 1:
            return _文字响应("抱歉，我无法完成这项分析。")
        raise CassetteMiss("cassette 缺失: retry.json")

    trace = TraceRecorder()
    with mock.patch.object(编排器_mod, "chat_completion", fake_chat):
        ok = 编排器_mod._执行一轮(
            _基础消息(), tools=[], context={}, 轮次=2, trace=trace,
        )
    assert ok is False
    assert len(calls) == 2, "应先文字后重试调用"
    失败 = [r for r in trace.to_list() if r["步骤"] == "LLM推理" and r["状态"] == "失败"]
    assert 失败 and 失败[-1]["轮次"] == 2, f"trace 应含轮次 2 失败记录：{trace.to_list()}"


def test_执行一轮_异常不吞工具执行异常():
    """只保护 LLM 调用：工具执行失败仍按原语义返回 False 并记录失败（非异常穿透）。"""
    trace = TraceRecorder()
    # chat_completion 返回合法 tool_call，但 execute_tool 返回 None（工具失败）
    def fake_chat(messages, **kw):
        return {
            "choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "聚合分析", "arguments": "{}"},
            }]}}],
            "usage": {},
        }

    with (
        mock.patch.object(编排器_mod, "chat_completion", fake_chat),
        mock.patch.object(编排器_mod, "execute_tool", return_value=None),
    ):
        ok = 编排器_mod._执行一轮(
            _基础消息(), tools=[], context={}, 轮次=1, trace=trace,
        )
    assert ok is False
    记录 = trace.to_list()
    assert any(r["状态"] == "失败" for r in 记录)
