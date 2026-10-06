# -*- coding: utf-8 -*-
"""阶段 54-10 · 测试 F1 · LLM失败原因全局串扰（orchestrator L433 兜底）

复现：llm_config 存在且 LLM 成功（fail_reason 空）时，L433 的
`(llm_config.llm_fail_reason if llm_config else "") or 最近LLM失败().get("reason","")`
会回退到全局串扰值 → 本请求成功却带别的前序请求失败原因。

修复预期：**仅当 llm_config is None（纯规则/无请求级配置路径）才回退全局**。
判定逻辑抽取为 orchestrator._LLM失败原因(llm_config) 模块函数以便单测。
"""
import pytest

llm_client = pytest.importorskip("后端_核心.agent.llm_client")


def test_有llm_config且成功时不回退全局失败原因():
    """请求级 llm_config 未失败 → 空字符串，不带全局串扰值（红：当前 L433 会带）。"""
    from 后端_核心.agent.orchestrator import _LLM失败原因

    # 制造全局串扰值（模拟另一个请求失败留下的全局状态）
    llm_client._record_llm_fail("【串扰】另一个请求的失败原因", None)
    assert llm_client.最近LLM失败().get("reason")  # 前置：全局确实有值

    class FakeCfg:
        llm_fail_reason = ""   # LLM 成功场景

    try:
        assert _LLM失败原因(FakeCfg()) == "", "有请求级 config 且成功时应为空，不应带全局串扰值"
    finally:
        llm_client._last_llm_fail.clear()


def test_有llm_config且失败时用请求级原因():
    """请求级 llm_config 自身有失败原因 → 用之（不回退全局）。"""
    from 后端_核心.agent.orchestrator import _LLM失败原因

    llm_client._record_llm_fail("【串扰】另一个请求的失败原因", None)

    class FakeCfg:
        llm_fail_reason = "本请求的失败原因"

    try:
        assert _LLM失败原因(FakeCfg()) == "本请求的失败原因"
    finally:
        llm_client._last_llm_fail.clear()


def test_无llm_config时回退全局():
    """llm_config is None（纯规则路径）→ 仍回退全局失败原因（保持既有行为）。"""
    from 后端_核心.agent.orchestrator import _LLM失败原因

    llm_client._record_llm_fail("【串扰】某请求失败", None)
    try:
        assert _LLM失败原因(None) == "【串扰】某请求失败"
    finally:
        llm_client._last_llm_fail.clear()