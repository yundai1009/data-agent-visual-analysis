# -*- coding: utf-8 -*-
"""阶段七十 · 执行态检查点接线（report_generator → checkpoint_repo）。

背景（接续 b104/b105）：
   仓储层（checkpoint_repo）与编排器续跑分支都已就位，但**没人调用它们**——
   检查点建好了却读不到、写不出，等于没做。本文件锁死「开关 → 读取 → 落库回调
   → 一次性消费」这条链路在 生成报表数据 层的四个判据：

   1. 默认关闭（启用检查点=None 且环境变量未开）→ 一次读取/写入都不发生，
      既有单测全走无检查点路径，行为零变化（回归底线）；
   2. 显式开启 + 命中 → 编排器真的收到 检查点，且本次续跑成功后一次性消费
      （已消费的行下次读取读不到，一次续跑只兑现一次）；
   3. 显式开启 + 未命中 → 落库回调生效：每跑完一轮把完整 messages 存进去，
      下次同需求请求读得到；
   4. 存档坏了 / 读写异常 → 当没有存档，照跑不炸。

「命中」的判据不看日志不看耗时，只看**桩计数**：
   - LLM 被调次数（续跑 = 1，非续跑 = 3）；
   - 消费/保存调用次数与参数。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心 import report_generator as generator
from 后端_核心.agent import llm_client as llm客户端_mod
from 后端_核心.agent import orchestrator as 编排器_mod
from repositories import checkpoint_repo


# ── 夹具 ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def 样例df():
    return pd.DataFrame({
        "地区": ["华东", "华南", "华北", "华东", "华南"],
        "销售额": [100, 120, 110, 130, 140],
    })


def _工具响应(工具名: str = "获取数据画像") -> Dict[str, Any]:
    """合法的 OpenAI tool_call 响应（编排器能解析出工具调用）。"""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_stub",
                    "type": "function",
                    "function": {"name": 工具名, "arguments": "{}"},
                }],
            },
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


@pytest.fixture
def llm桩(monkeypatch):
    """让 LLM 路径真的走起来（否则 is_llm_configured 判 False 走规则降级，
    检查点链路根本没被执行），同时计数每次调用并记下尾消息/消息数。

    真编排器通过 generator.生成报表数据 内部引用，无需替换；只把底层的
    chat_completion 桩掉即可。
    """
    monkeypatch.setattr(llm客户端_mod.EnvConfig, "LLM_API_KEY", "sk-real-key-xxxx")
    调用: List[Dict[str, Any]] = []

    def _桩(messages, tools=None, tool_choice=None, llm_config=None, **_kw):
        调用.append({
            "尾消息": (messages[-1] or {}).get("content", "") or "",
            "消息数": len(messages),
            "角色序列": [m.get("role") for m in messages],
        })
        return _工具响应()

    monkeypatch.setattr(编排器_mod, "chat_completion", _桩)
    monkeypatch.setattr(llm客户端_mod, "chat_completion", _桩)
    return 调用


@pytest.fixture
def 落库探针(monkeypatch):
    """记录 checkpoint_repo 的读/写/消费调用（打在生产代码引用的同一模块对象上）。"""
    记录: Dict[str, List[Any]] = {"读取": [], "保存": [], "消费": []}
    原读 = checkpoint_repo.读取检查点
    原存 = checkpoint_repo.保存检查点
    原消 = checkpoint_repo.消费检查点

    def _读(*a, **kw):
        记录["读取"].append((a, kw))
        return 原读(*a, **kw)

    def _存(*a, **kw):
        记录["保存"].append((a, kw))
        return 原存(*a, **kw)

    def _消(检查点ID, **kw):
        记录["消费"].append(检查点ID)
        return 原消(检查点ID, **kw)

    monkeypatch.setattr(checkpoint_repo, "读取检查点", _读)
    monkeypatch.setattr(checkpoint_repo, "保存检查点", _存)
    monkeypatch.setattr(checkpoint_repo, "消费检查点", _消)
    return 记录


# ── 判据 1：默认关闭，行为零变化 ──────────────────────────────────────────────


def test_默认关闭_不读不写不消费(样例df, llm桩, 落库探针, monkeypatch):
    """开关没开（环境变量也没有）→ checkpoint_repo 一次都不该被碰。

    这是回归底线：既有单测里 15 处 生成报表数据 调用全都不传 启用检查点，
    若默认开启会凭空多出 DB 访问与检查点残留。
    """
    monkeypatch.delenv("DAA_CHECKPOINT_ENABLED", raising=False)
    r = generator.生成报表数据(样例df, 分析需求="帮我分析一下销售情况", user_id="u1")
    assert r["图表配置"]
    assert 落库探针["读取"] == [], 落库探针
    assert 落库探针["保存"] == [], 落库探针
    assert 落库探针["消费"] == [], 落库探针


def test_显式关闭_即使环境变量开着也不读(样例df, llm桩, 落库探针, monkeypatch):
    """启用检查点=False 优先于环境变量——调用方说了算（同步端点无取消语义，
    也就不该留下检查点）。"""
    monkeypatch.setenv("DAA_CHECKPOINT_ENABLED", "1")
    r = generator.生成报表数据(
        样例df, 分析需求="帮我分析一下销售情况", user_id="u1", 启用检查点=False,
    )
    assert r["图表配置"]
    assert 落库探针["读取"] == [], 落库探针


# ── 判据 2：开关开 + 命中 → 续跑 + 一次性消费 ────────────────────────────────


def _预置检查点(轮次: int = 2, 消息: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """伪造一份「最近一份可用」检查点，供读取探针返回。"""
    return {
        "检查点ID": "cp-pre-1",
        "轮次": 轮次,
        "messages": 消息 if 消息 is not None else [
            {"role": "system", "content": "你是数据分析助手……"},
            {"role": "user", "content": "帮我分析一下销售情况"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "获取数据画像", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "画像：2 列"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c2", "type": "function",
                 "function": {"name": "聚合分析", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c2", "content": "聚合结果：华南区 12345"},
        ],
        "状态": "可用",
    }


def test_开关开且命中_编排器收到完整存档(样例df, llm桩, 落库探针, monkeypatch):
    """读到检查点 → 必须原样透传给编排器。

    判据：续跑只发生 1 次 LLM 调用，且这次调用发给 LLM 的 messages 是存档里
    那 6 条（不是从零重建的 2 条）——只有 messages 完整恢复才会这样。

    读取用本地探针记录（直接覆盖 读取检查点 会顶掉 落库探针 的包装，故不复用
    落库探针["读取"]）。
    """
    monkeypatch.setenv("DAA_CHECKPOINT_ENABLED", "1")
    存档 = _预置检查点()
    读取记录: List[Any] = []

    def _假读(*a, **kw):
        读取记录.append((a, kw))
        return 存档

    monkeypatch.setattr(generator.checkpoint_repo, "读取检查点", _假读)

    generator.生成报表数据(
        样例df, 分析需求="帮我分析一下销售情况", user_id="u1", dataset_id="ds-1",
    )
    assert 读取记录, "开关开着却一次都没读"
    assert len(llm桩) == 1, f"命中第 2 轮检查点后仍发生 {len(llm桩)} 次调用"
    assert llm桩[0]["消息数"] == 6, llm桩[0]
    assert llm桩[0]["角色序列"] == ["system", "user", "assistant", "tool", "assistant", "tool"]
    # 第二把钥匙：dataset_id 必须带进读取条件（换数据集不能拿旧中间态）
    _, 读参数 = 读取记录[0]
    assert 读参数.get("dataset_id") == "ds-1", 读参数


def test_开关开且命中_续跑成功后一次性消费(样例df, llm桩, 落库探针, monkeypatch):
    """续跑兑现后必须消费掉这份存档——否则下次还会再续一次，同一份中间态
    被反复续跑，前几轮的账也重复计入。"""
    monkeypatch.setenv("DAA_CHECKPOINT_ENABLED", "1")
    存档 = _预置检查点()
    monkeypatch.setattr(generator.checkpoint_repo, "读取检查点", lambda *a, **kw: 存档)

    generator.生成报表数据(
        样例df, 分析需求="帮我分析一下销售情况", user_id="u1", dataset_id="ds-1",
    )
    assert 落库探针["消费"] == ["cp-pre-1"], 落库探针["消费"]


def test_开关开且命中_续跑真的少调LLM且看得见聚合结果(样例df, llm桩, 落库探针, monkeypatch):
    """核心收益判据：命中「已完成第 2 轮」→ LLM 只被调 1 次（第 3 轮）。

    这条把编排器的续跑收益一路验到 生成报表数据：链路断了任何一环
    （没读、没透传、编排器没接）都会表现为 3 次调用。且这次调用看得见存档里
    的聚合结果（messages 完整恢复，不是只恢复轮次号）。
    """
    monkeypatch.setenv("DAA_CHECKPOINT_ENABLED", "1")
    存档 = _预置检查点()
    monkeypatch.setattr(generator.checkpoint_repo, "读取检查点", lambda *a, **kw: 存档)

    generator.生成报表数据(
        样例df, 分析需求="帮我分析一下销售情况", user_id="u1", dataset_id="ds-1",
    )
    assert len(llm桩) == 1, f"命中第 2 轮检查点后仍发生 {len(llm桩)} 次调用"
    assert "聚合结果" in llm桩[0]["尾消息"], llm桩[0]


# ── 判据 3：开关开 + 未命中 → 落库回调生效 ───────────────────────────────────


def test_开关开未命中_逐轮落库(样例df, llm桩, 落库探针, monkeypatch):
    """没读到存档 → 落库回调必须挂上：每跑完一轮把 messages 存进去，
    下次同需求请求才读得到。参数要带全（user_id/dataset_id/需求/画像/轮次）。"""
    monkeypatch.setenv("DAA_CHECKPOINT_ENABLED", "1")
    monkeypatch.setattr(generator.checkpoint_repo, "读取检查点", lambda *a, **kw: None)

    generator.生成报表数据(
        样例df, 分析需求="帮我分析一下销售情况", user_id="u1", dataset_id="ds-9",
    )
    轮次 = [调[0][5] for 调 in 落库探针["保存"]]
    assert 轮次 == [1, 2], f"落库轮次不对：{轮次}"
    首调 = 落库探针["保存"][0][0]
    assert 首调[0] == "u1" and 首调[1] == "ds-9", 首调
    assert 首调[2] == "帮我分析一下销售情况" and 首调[3]["行数"] == 5, 首调
    # 没有存档就不该消费（本次是全新存档，留给下次）
    assert 落库探针["消费"] == [], 落库探针["消费"]


# ── 判据 4：坏存档 / 落库异常 → 不炸 ────────────────────────────────────────


@pytest.mark.parametrize("坏存档", [
    {"轮次": 1, "messages": [{"role": "user", "content": "只有一条"}]},
    {"轮次": 0, "messages": []},
    {"轮次": "不是数字", "messages": None},
    {},
])
def test_坏存档_当没有存档照跑(样例df, llm桩, 落库探针, monkeypatch, 坏存档):
    """读到的存档坏了 → 编排器当没存档跑满 3 轮，且不抛异常。"""
    monkeypatch.setenv("DAA_CHECKPOINT_ENABLED", "1")
    monkeypatch.setattr(generator.checkpoint_repo, "读取检查点", lambda *a, **kw: 坏存档)

    r = generator.生成报表数据(
        样例df, 分析需求="帮我分析一下销售情况", user_id="u1", dataset_id="ds-1",
    )
    assert r["图表配置"]
    assert len(llm桩) == 3, f"{坏存档} → {len(llm桩)} 次调用"
    # 坏存档不算命中，不消费
    assert 落库探针["消费"] == [], 落库探针["消费"]


def test_读取检查点抛异常_降级为无检查点(样例df, llm桩, 落库探针, monkeypatch):
    """表被锁/连不上库 → 按全新分析处理，绝不能把报表生成带崩。"""
    monkeypatch.setenv("DAA_CHECKPOINT_ENABLED", "1")

    def _炸(*a, **kw):
        raise RuntimeError("检查点表被锁")

    monkeypatch.setattr(generator.checkpoint_repo, "读取检查点", _炸)

    r = generator.生成报表数据(
        样例df, 分析需求="帮我分析一下销售情况", user_id="u1", dataset_id="ds-1",
    )
    assert r["图表配置"]
    assert len(llm桩) == 3


def test_消费检查点抛异常_不影响已算好的报表(样例df, llm桩, 落库探针, monkeypatch):
    """消费失败只意味着这份存档下次还会被读到再续一次——不能因此丢掉整张报表。"""
    monkeypatch.setenv("DAA_CHECKPOINT_ENABLED", "1")
    存档 = _预置检查点()
    monkeypatch.setattr(generator.checkpoint_repo, "读取检查点", lambda *a, **kw: 存档)

    def _炸(检查点ID, **kw):
        raise RuntimeError("消费失败")

    monkeypatch.setattr(generator.checkpoint_repo, "消费检查点", _炸)

    r = generator.生成报表数据(
        样例df, 分析需求="帮我分析一下销售情况", user_id="u1", dataset_id="ds-1",
    )
    assert r["图表配置"]
    assert r["报表数据"]
