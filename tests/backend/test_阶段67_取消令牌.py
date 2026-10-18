# -*- coding: utf-8 -*-
"""阶段六十七 · 编排器取消令牌：客户端断开后不再发起后续 LLM 调用。

背景（这是缺陷，不是需求）：
  SSE 流式分析的 worker 是 daemon 线程（api/routes/reports.py 的 generate_report_stream），
  客户端断开/关页面后没有任何停止条件，仍会把 3 轮 ReAct 全部跑完。
  阶段六十二 真机实测：单轮 LLM 调用 10.94 秒，用户在这 10 秒里关页面，
  请求照样发出、Token 照样烧完。

判据只有一个：**LLM 被调用的次数**（桩计数，不看日志、不看耗时）。
  - 不传令牌 → 3 轮照跑（行为不变，这是回归底线）
  - 令牌已置位 → 0 次调用，且仍按规则降级出图（不报错、不空白页）
  - 第 N 轮之后置位 → 只发生 N 次调用
  - 单轮内部「没调工具就重试」的分支也必须先查令牌，否则重试那一次照样烧 Token
  - 路由层：event_stream 的 finally 必须置位同一个 Event（客户端断开的唯一信号源）
"""

import json
import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from 后端_核心.agent import llm_client as llm客户端_mod
from 后端_核心.agent import orchestrator as 编排器_mod
from 后端_核心.agent import multi_agent as 多智能体_mod
from 后端_核心.agent.trace import TraceRecorder


# ── 夹具 ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _启用LLM(monkeypatch):
    """编排Agent 内部会用 is_llm_configured 覆盖传入的 enable_llm，
    环境默认的占位 Key（conftest 里 your_llm_api_key）会让它静默降级走不到
    ReAct 分支——那样测出来的「0 次调用」是假绿。这里换成非占位 Key。"""
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


def _工具响应(工具名: str = "获取数据画像") -> Dict[str, Any]:
    """构造一个合法的 OpenAI tool_call 响应（extract_tool_call 能解析）。"""
    return {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": "call_stub",
                    "type": "function",
                    "function": {"name": 工具名, "arguments": json.dumps({}, ensure_ascii=False)},
                }],
            },
        }],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


def _纯文本响应() -> Dict[str, Any]:
    """构造一个「只回文字、不调工具」的响应——用来触发 _执行一轮 的重试分支。"""
    return {
        "choices": [{"message": {"role": "assistant", "content": "分析如下……"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }


class _LLM桩:
    """chat_completion 计数桩：记录调用次数，并可在第 N 次调用返回前置位取消令牌。

    置位时机刻意放在「响应返回之后」——模拟真实时序：用户在 LLM 已经跑完、
    下一轮还没发起的那一刻关掉了页面。
    """

    def __init__(self, monkeypatch) -> None:
        self.调用: List[Dict[str, Any]] = []
        self._取消: Optional[threading.Event] = None
        self._置位于第几次 = 0
        self._纯文本 = False

        def _桩(messages, tools=None, tool_choice=None, llm_config=None, **_kw):
            self.调用.append({"尾消息": (messages[-1] or {}).get("content", "")[:30]})
            resp = _纯文本响应() if self._纯文本 else _工具响应()
            if self._取消 is not None and len(self.调用) == self._置位于第几次:
                self._取消.set()
            return resp

        # 两处都要打：编排器是 import-time 绑定到模块全局的，
        # 多智能体审查员是调用时从 llm_client 现取（multi_agent._运行_agent）。
        monkeypatch.setattr(编排器_mod, "chat_completion", _桩)
        monkeypatch.setattr(llm客户端_mod, "chat_completion", _桩)

    def 会在第几次后置位(self, 取消: threading.Event, 第几次: int = 1, 纯文本: bool = False) -> None:
        self._取消 = 取消
        self._置位于第几次 = 第几次
        self._纯文本 = 纯文本

    @property
    def 次数(self) -> int:
        return len(self.调用)


@pytest.fixture
def llm桩(monkeypatch) -> _LLM桩:
    return _LLM桩(monkeypatch)


def _说明列表(意图: Dict[str, Any]) -> List[str]:
    return [s.get("说明") or "" for s in (意图.get("Agent_Trace") or [])]


# ── 编排器：不传令牌时行为不变（回归底线） ──────────────────────────────────


def test_不传取消令牌_三轮照跑(画像, llm桩):
    """编排Agent(cancel=None) → 3 轮 ReAct 一次不少，LLM 被调 3 次。

    这是本次改动的回归底线：新增可选参数不得改变任何既有调用方（同步端点、
    追问链、评测脚本、多智能体都不传令牌）。
    """
    意图 = 编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True)
    assert 意图 is not None
    assert llm桩.次数 == 3, [c["尾消息"] for c in llm桩.调用]


# ── 编排器：令牌已置位 ────────────────────────────────────────────────────────


def test_令牌已置位_一次LLM都不调(画像, llm桩):
    """进入 ReAct 前令牌已置位 → 0 次 LLM 调用，且仍按规则降级出图。"""
    取消 = threading.Event()
    取消.set()
    意图 = 编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True, cancel=取消)
    assert llm桩.次数 == 0, "令牌已置位仍发起了 LLM 请求，用户已断开还在烧 Token"
    assert 意图 is not None
    assert 意图["意图来源"] == "规则", 意图["意图来源"]
    assert 意图["图表类型"], "取消后必须仍能出一份规则版报表，而不是空"


def test_令牌已置位_trace里写明断开原因(画像, llm桩):
    """取消要在 trace 里留痕：后来打开历史报表的人得知道这份图为什么不是 LLM 版的。"""
    取消 = threading.Event()
    取消.set()
    意图 = 编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True, cancel=取消)
    assert any("断开" in 说明 for 说明 in _说明列表(意图)), _说明列表(意图)


def test_第一轮后置位_不再发起第二轮(画像, llm桩):
    """用户在第 1 轮跑完后关页面 → 只发生 1 次调用（第 2/3 轮不再发起）。"""
    取消 = threading.Event()
    llm桩.会在第几次后置位(取消, 第几次=1)
    意图 = 编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True, cancel=取消)
    assert llm桩.次数 == 1, [c["尾消息"] for c in llm桩.调用]
    assert 意图 is not None and 意图["图表类型"]


def test_第二轮后置位_不再发起第三轮(画像, llm桩):
    """同上前移：第 2 轮跑完后断开 → 2 次调用，不烧第 3 轮。"""
    取消 = threading.Event()
    llm桩.会在第几次后置位(取消, 第几次=2)
    意图 = 编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True, cancel=取消)
    assert llm桩.次数 == 2, [c["尾消息"] for c in llm桩.调用]
    assert 意图 is not None and 意图["图表类型"]


def test_取消后不写长期记忆(画像, llm桩):
    """降级出的规则意图不该被当成"LLM 分析成功"写进向量记忆库。

    记忆库是 few-shot 的事实来源，灌进规则版本会污染后续检索质量。
    """
    保存: List[Any] = []
    import 后端_核心.agent.orchestrator as _编排器
    原始保存 = _编排器.保存记忆
    _编排器.保存记忆 = lambda *a, **k: 保存.append(a)
    try:
        取消 = threading.Event()
        取消.set()
        编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True, cancel=取消)
    finally:
        _编排器.保存记忆 = 原始保存
    assert not 保存, "取消后的规则降级结果被写进了长期记忆"


# ── 单轮内部：入口 + 重试分支 ────────────────────────────────────────────────


def test_单轮入口令牌已置位_直接判失败(画像, llm桩):
    """_执行一轮 自身也要认令牌（多智能体路径会直接调它）。"""
    取消 = threading.Event()
    取消.set()
    ok = 编排器_mod._执行一轮(
        [{"role": "user", "content": "看画像"}], [], {"画像": 画像, "df": None},
        轮次=1, trace=TraceRecorder(), cancel=取消,
    )
    assert ok is False
    assert llm桩.次数 == 0


def test_重试分支前先查令牌_不发起重试(画像, llm桩):
    """轮次≥2 且模型只回文字时本会重试一次——令牌已置位时必须放弃这次重试。

    这是最容易漏的一处：只看「轮次入口」的话，页面都关了还会再发一次请求。
    """
    取消 = threading.Event()
    llm桩.会在第几次后置位(取消, 第几次=1, 纯文本=True)
    messages = [{"role": "user", "content": "聚合一下"}]
    ok = 编排器_mod._执行一轮(
        messages, [], {"画像": 画像, "df": None},
        轮次=2, trace=TraceRecorder(), cancel=取消,
    )
    assert llm桩.次数 == 1, "重试请求在取消后仍被发出"
    assert ok is False
    # 重试提示语不能留在 messages 里污染后续轮次
    assert all("必须返回工具调用" not in (m.get("content") or "") for m in messages), messages


# ── 多智能体路径 ─────────────────────────────────────────────────────────────


def test_多智能体路径透传取消(画像, llm桩):
    """多智能体也走 _执行一轮，别让取消令牌在 agent_mode=multi 下失效。"""
    取消 = threading.Event()
    取消.set()
    结果 = 多智能体_mod.多智能体分析(画像, "帮我分析一下销售情况", df=None, cancel=取消)
    assert llm桩.次数 == 0, "agent_mode=multi 下取消令牌未生效"
    assert 结果 and 结果.get("图表类型")


# ── 路由层：客户端断开的唯一信号源是 event_stream 的 finally ──────────────────


def test_流式生成把令牌交给worker且生成器关闭即置位(monkeypatch):
    """generate_report_stream：worker 收到同一个 Event；生成器被关闭（=客户端断开）
    时 finally 置位。Starlette 在客户端断开时关闭 body_iterator，
    GeneratorExit 会走到 finally——这正是取消的唯一触发源。
    """
    import api.routes.reports as 路由_mod
    from api.contracts import ReportGenerateRequest

    已进worker = threading.Event()
    捕获: Dict[str, Any] = {}

    def _假流式(payload, df, llm_config, user, on_event=None, source_page=None, cancel=None):
        捕获["cancel"] = cancel
        捕获["进入时已置位"] = bool(cancel and cancel.is_set())
        if on_event:
            on_event({"type": "step", "data": {"说明": "第一步"}})
        已进worker.set()
        return "r_测试", {"标题": "t", "图表类型": "柱状图"}

    monkeypatch.setattr(路由_mod, "_生成报表流式", _假流式)
    monkeypatch.setattr(路由_mod, "_准备上下文", lambda payload, request, user: (None, None))

    payload = ReportGenerateRequest(数据集ID="ds_1", 分析需求="帮我看看销售额趋势")
    request = SimpleNamespace(headers={})
    响应 = 路由_mod.generate_report_stream(payload, request, user={"user_id": "u_1"})

    async def _读一条再断开() -> str:
        # body_iterator 是 async_generator（Starlette 把同步生成器包进线程池迭代器），
        # aclose() 会关闭内层同步生成器 → GeneratorExit → finally。
        迭代器 = 响应.body_iterator
        首条 = await 迭代器.__anext__()
        await 迭代器.aclose()
        return 首条

    import asyncio

    首条 = asyncio.run(_读一条再断开())
    assert "第一步" in 首条
    assert 已进worker.wait(5), "worker 线程没有启动"
    assert 捕获.get("cancel") is not None, "令牌没有透传给 worker"
    assert 捕获["进入时已置位"] is False, "连接正常时不应被判定为已取消"

    # 等价于客户端断开：生成器已在 _读一条再断开 里被 aclose()。
    assert 捕获["cancel"].is_set(), "生成器关闭后令牌未置位，断开后仍会继续烧 Token"
