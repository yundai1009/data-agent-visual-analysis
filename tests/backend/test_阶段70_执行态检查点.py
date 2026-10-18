# -*- coding: utf-8 -*-
"""阶段七十 · 编排器执行态检查点：断点续跑（而不是从第 1 轮重来）。

背景（这是缺陷，不是需求）：
  阶段六十二 真机实测单轮 LLM 调用 10.94 秒、三轮 ReAct 合计 30+ 秒。
  用户在最后 10 秒关页面（或进程被杀）时，前两轮已经花掉的 20 秒成果**全部作废**，
  下次点「开始分析」仍从第 1 轮重跑——钱和时间都白花了。
  阶段六十七 的取消令牌只挡住「还没发出的请求」，挡不住「已经做完的轮次被丢掉」。

判据同样只看 **LLM 被调用的次数**（桩计数，不看日志、不看耗时）：
  - 不传检查点 → 3 轮照跑，且每轮跑完都把执行态交给落库回调（回归底线）
  - 命中「已完成第 2 轮」的检查点 → 只发生 1 次调用（第 3 轮），且这次调用看得见
    存档里的聚合结果（尾消息 = 存档的最后一条 tool 返回）
  - 命中「已完成第 1 轮」→ 2 次调用，且第 2 轮的成果回落库
  - 存档坏了（messages 不足 2 条）→ 当没有存档，3 轮照跑，绝不报错
  - 落库回调抛异常 → 本次分析照样跑完（检查点是加速手段，不是分析链路的一环）
  - 续跑时不再重复检索向量记忆（第 1 轮已经检索过，messages 里带着结论）
"""

import json
import threading
from typing import Any, Dict, List, Optional

import pytest

from 后端_核心.agent import llm_client as llm客户端_mod
from 后端_核心.agent import orchestrator as 编排器_mod


# ── 夹具 ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _启用LLM(monkeypatch):
    """编排Agent 内部用 is_llm_configured 覆盖传入的 enable_llm，
    conftest 的占位 Key（your_llm_api_key）会让它静默降级走不到 ReAct 分支——
    那样测出来的「续跑少调了 LLM」是假绿。这里换成非占位 Key。"""
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
    """合法的 OpenAI tool_call 响应（extract_tool_call 能解析）。"""
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


class _LLM桩:
    """chat_completion 计数桩：记录每次调用的尾消息（用来看 LLM 究竟看到了什么）。"""

    def __init__(self, monkeypatch) -> None:
        self.调用: List[Dict[str, Any]] = []

        def _桩(messages, tools=None, tool_choice=None, llm_config=None, **_kw):
            self.调用.append({
                "尾消息": (messages[-1] or {}).get("content", "") or "",
                "消息数": len(messages),
                "角色序列": [m.get("role") for m in messages],
            })
            return _工具响应()

        monkeypatch.setattr(编排器_mod, "chat_completion", _桩)
        monkeypatch.setattr(llm客户端_mod, "chat_completion", _桩)

    @property
    def 次数(self) -> int:
        return len(self.调用)


@pytest.fixture
def llm桩(monkeypatch) -> _LLM桩:
    return _LLM桩(monkeypatch)


def _存档消息(尾内容: str = "聚合结果：华南区 销售额 12345") -> List[Dict[str, Any]]:
    """一段真实形状的 ReAct 对话体：system + user + (assistant tool_call + tool 返回) × 2。

    关键点：最后一条是 **tool 返回**（不是用户的话）。续跑若只恢复「轮次号」而不恢复
    这段消息，LLM 看到的就只是原始需求，等于换了道题在答。
    """
    return [
        {"role": "system", "content": "你是数据分析助手……"},
        {"role": "user", "content": "那华南区呢？"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "获取数据画像", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "画像：4 列 100 行，含分类字段 地区"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "c2", "type": "function",
                "function": {"name": "聚合分析", "arguments": "{}"},
            }],
        },
        {"role": "tool", "tool_call_id": "c2", "content": 尾内容},
    ]


def _说明列表(意图: Dict[str, Any]) -> List[str]:
    return [s.get("说明") or "" for s in (意图.get("Agent_Trace") or [])]


def _落库收集器() -> Any:
    """返回 (回调, 记录列表)；记录形如 (轮次, 消息条数)。"""
    记录: List[Any] = []

    def 回调(轮次: int, messages: List[Dict[str, Any]]) -> None:
        记录.append((轮次, len(messages)))

    return 回调, 记录


# ── 不传检查点：行为不变（回归底线）+ 逐轮落库 ────────────────────────────────


def test_不传检查点_三轮照跑且逐轮落库(画像, llm桩):
    """编排Agent(检查点=None, 落检查点=回调) → 3 轮一次不少，第 1/2 轮各落一次库。

    这是回归底线：新增可选参数不得改变任何既有调用方（同步端点、追问链、
    评测脚本、多智能体都不传检查点）。
    """
    回调, 记录 = _落库收集器()
    意图 = 编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, 落检查点=回调,
    )
    assert 意图 is not None
    assert llm桩.次数 == 3, [c["尾消息"] for c in llm桩.调用]
    assert [r[0] for r in 记录] == [1, 2], f"落库轮次不对：{记录}"
    # 落库的是"逐轮长大的对话体"，不是光秃秃一个轮次号
    assert 记录[0][1] < 记录[1][1], f"messages 没有随轮次增长：{记录}"


def test_不传落库回调_照跑不报错(画像, llm桩):
    """只读端点/评测脚本不会传落库回调——不能因此抛错。"""
    意图 = 编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True)
    assert 意图 is not None
    assert llm桩.次数 == 3


# ── 命中检查点：真续跑 ────────────────────────────────────────────────────────


def test_命中第2轮检查点_只调一次LLM(画像, llm桩):
    """存档「已完成第 2 轮」→ 只发生 1 次 LLM 调用（第 3 轮）。

    这是本阶段的核心收益：前两轮合计 20+ 秒的推理＋聚合不再重跑。
    """
    检查点 = {"轮次": 2, "messages": _存档消息()}
    意图 = 编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, 检查点=检查点,
    )
    assert 意图 is not None
    assert llm桩.次数 == 1, f"命中第 2 轮检查点后仍发生 {llm桩.次数} 次调用：{[c['尾消息'] for c in llm桩.调用]}"


def test_命中第2轮检查点_LLM看得见存档里的聚合结果(画像, llm桩):
    """续跑的正确性依赖 messages 完整恢复，而不是只恢复轮次号。

    判据：这次调用发给 LLM 的尾消息，必须是存档里第 2 轮工具返回的**聚合结果**。
    若实现退化成"只恢复轮次、messages 从零重建"，尾消息会变回用户需求原文，
    第 3 轮就是凭空推断（换了道题在答）。
    """
    检查点 = {"轮次": 2, "messages": _存档消息()}
    编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True, 检查点=检查点)
    assert llm桩.次数 == 1
    assert "聚合结果" in llm桩.调用[0]["尾消息"], llm桩.调用[0]
    # system + user + 两条 assistant(tool_call) + 两条 tool 返回 = 6 条，且末条是 tool
    assert llm桩.调用[0]["消息数"] == 6, llm桩.调用[0]
    assert llm桩.调用[0]["角色序列"] == ["system", "user", "assistant", "tool", "assistant", "tool"]


def test_命中第2轮检查点_trace首条写明续跑(画像, llm桩):
    """看 trace 的人必须能知道"这份报表为什么只跑了一轮"，否则会以为流程缺了步骤。"""
    检查点 = {"轮次": 2, "messages": _存档消息()}
    意图 = 编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, 检查点=检查点,
    )
    说明 = _说明列表(意图)
    assert 说明, "续跑没有在 trace 里留痕"
    首条 = 说明[0]
    assert "检查点" in 首条 and "续跑" in 首条, 说明


def test_命中第1轮检查点_从第2轮续跑并回落库(画像, llm桩):
    """存档「已完成第 1 轮」→ 2 次调用（第 2/3 轮），第 2 轮的成果继续回落库。"""
    回调, 记录 = _落库收集器()
    检查点 = {"轮次": 1, "messages": _存档消息()}
    意图 = 编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, 检查点=检查点, 落检查点=回调,
    )
    assert 意图 is not None
    assert llm桩.次数 == 2, [c["尾消息"] for c in llm桩.调用]
    assert [r[0] for r in 记录] == [2], f"续跑后半程没有继续落库：{记录}"


def test_命中第2轮检查点_不重复落库(画像, llm桩):
    """第 1/2 轮都没再跑，自然没有新成果要落库——不能拿存档回写出一份假存档。"""
    回调, 记录 = _落库收集器()
    检查点 = {"轮次": 2, "messages": _存档消息()}
    编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, 检查点=检查点, 落检查点=回调,
    )
    assert 记录 == [], f"跳过的轮次不应产生落库：{记录}"


def test_命中检查点_不再重复检索向量记忆(画像, llm桩, monkeypatch):
    """第 1 轮已经检索过、结论就在存档 messages 的 system 里——续跑不必再检索一次。"""
    次数 = {"值": 0}

    def _计数检索(*_a, **_k):
        次数["值"] += 1
        return []

    monkeypatch.setattr(编排器_mod, "检索相似记忆", _计数检索)
    monkeypatch.setattr(编排器_mod, "生成_few_shot_prompt", lambda *_: "")

    编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True,
        检查点={"轮次": 2, "messages": _存档消息()},
    )
    assert 次数["值"] == 0, "续跑时又去检索了一次向量记忆（白花一次 embedding 调用）"

    编排器_mod.编排Agent(画像, "帮我分析一下销售情况", enable_llm=True)
    assert 次数["值"] == 1, "未命中检查点时应当照常检索记忆"


# ── 坏存档 / 回调异常：都不得影响正常分析 ────────────────────────────────────


@pytest.mark.parametrize("坏存档", [
    {"轮次": 1, "messages": [{"role": "user", "content": "只有一条"}]},
    {"轮次": 1, "messages": []},
    {"轮次": 0, "messages": _存档消息()},
    {"轮次": "不是数字", "messages": _存档消息()},
    {"messages": _存档消息()},
    {"轮次": 1, "messages": None},
])
def test_坏存档_当没有存档照跑三轮(画像, llm桩, 坏存档):
    """坏存档必须是"没有存档"，不能抛异常也不能半信半疑地接上去。"""
    意图 = 编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, 检查点=坏存档,
    )
    assert 意图 is not None
    assert llm桩.次数 == 3, f"{坏存档} → {llm桩.次数} 次调用"


def test_落库回调抛异常_不拖垮本次分析(画像, llm桩):
    """检查点是加速手段，不是分析链路的一环：磁盘满/表被锁时分析照样要出结果。"""
    def _炸(**kwargs):
        raise RuntimeError("磁盘满了")

    意图 = 编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, 落检查点=_炸,
    )
    assert 意图 is not None
    assert 意图.get("图表类型"), "落库失败把整条分析链路带崩了"
    assert llm桩.次数 == 3


# ── 与取消令牌的交互 ──────────────────────────────────────────────────────────


def test_命中检查点后令牌置位_一次LLM都不调(画像, llm桩):
    """续跑的第 3 轮也必须先查令牌：用户在续跑途中又关了页面，不能再发请求。"""
    取消 = threading.Event()
    取消.set()
    意图 = 编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, cancel=取消,
        检查点={"轮次": 2, "messages": _存档消息()},
    )
    assert llm桩.次数 == 0, [c["尾消息"] for c in llm桩.调用]
    assert 意图 is not None and 意图["图表类型"]


def test_令牌在续跑前已置位_仍能出规则版报表(画像, llm桩):
    """令牌已置位 + 命中检查点 → 一次 LLM 都不调，且仍按规则降级出一份可用报表。

    时序说明：用户上一次断在这里，这次点了「开始分析」又马上关掉页面——
    续跑不能因为"存档说还有一轮要跑"就无视令牌把请求发出去。
    """
    取消 = threading.Event()
    取消.set()
    意图 = 编排器_mod.编排Agent(
        画像, "帮我分析一下销售情况", enable_llm=True, cancel=取消,
        检查点={"轮次": 2, "messages": _存档消息()},
    )
    assert llm桩.次数 == 0, [c["尾消息"] for c in llm桩.调用]
    assert 意图 is not None
    assert 意图["意图来源"] == "规则", 意图["意图来源"]
    assert 意图["图表类型"], "取消后必须仍能出一份规则版报表，而不是空"
    assert any("断开" in 说明 for 说明 in _说明列表(意图)), _说明列表(意图)
