# -*- coding: utf-8 -*-
"""阶段六十九 回归：取消令牌置位后，流程里**最后一个** LLM 调用也必须停。

为什么单开一个文件：阶段六十七的用例全部围绕 `编排Agent` 展开，而「结论润色」是编排
结束**之后**、报表落库之前单独飞的一次 LLM 请求（`report_generator._生成结论_含来源`
→ `后端_核心/agent/conclusion.py 润色结论`）。这条链路上原本没有任何地方读取消令牌，
于是「客户端断开后不再发起新的 LLM 调用」这句话在真机上并不成立——E2E P14 实测断开
之后仍然飞了一次润色请求。

修复后的真机现象：P14 后端日志在 `第 N 轮后收到取消信号，跳过后续 LLM 调用` 之后还会
出现 `客户端已断开，跳过结论润色 LLM 调用，改用模板结论`；修复前那一行不存在（这也是
`scripts/e2e_real_user.py::跑取消令牌` 里那条日志断言的依据）。

语义上「跳过润色、改用模板结论」正好等于取消时的既定降级策略：取消的是**继续推理**，
不是这次分析——报表照常算完落库，只是不再花钱调 LLM。
"""

import threading

import pandas as pd

from 后端_核心 import report_generator as rg


def _画像():
    return {"行数": 3, "列数": 2, "总缺失值": 0, "数据质量": {"提示": [], "等级": "良好"}}


def _报表df():
    return pd.DataFrame({"地区": ["华东", "华南", "华北"], "销售额": [300, 200, 100]})


def _推荐说明():
    return {"理由": ["销售额是数值列，适合做聚合"], "推荐字段": {"X轴": "地区", "Y轴": ["销售额"]}}


def _跑(monkeypatch, cancel, agent_trace):
    """桩掉润色结论，返回（调用记录, （结论文本, 来源））。"""
    调用 = []

    def _假润色(*args, **kwargs):
        调用.append(1)
        return "LLM 润色后的结论"

    monkeypatch.setattr(rg, "润色结论", _假润色)
    结果 = rg._生成结论_含来源(
        "看各地区销售额", _画像(), _报表df(), "bar", _推荐说明(), [],
        agent_trace, "规则", cancel=cancel,
    )
    return 调用, 结果


def test_令牌已置位_最后一个LLM调用也不发出去(monkeypatch):
    取消 = threading.Event()
    取消.set()
    轨迹 = [{"轮次": 2, "步骤": "观察", "说明": "客户端已断开（连接已关闭），已停止后续 LLM 推理，本次结果按规则降级生成", "状态": "需关注"}]
    调用, (文本, 来源) = _跑(monkeypatch, 取消, 轨迹)
    assert 调用 == [], "令牌已置位还调了润色结论：断开后仍在发起新的 LLM 调用"
    assert 来源 == "模板", f"取消后来源应该是模板，实际={来源!r}"
    assert "看各地区销售额" in 文本, "回退路径必须真的产出模板结论，而不是空字符串"


def test_令牌未置位_照常走LLM润色(monkeypatch):
    调用, (文本, 来源) = _跑(monkeypatch, None, [{"轮次": 1, "步骤": "观察", "说明": "命中规则", "状态": "成功"}])
    assert 调用 == [1], "没取消却不调润色结论：正常路径被改坏了"
    assert 来源 == "LLM"
    assert 文本 == "LLM 润色后的结论"


def test_空轨迹_本来就不走润色(monkeypatch):
    """规则短路/异常兜底路径返回空 trace，本来就没有可润色的分析过程。"""
    调用, (文本, 来源) = _跑(monkeypatch, None, [])
    assert 调用 == []
    assert 来源 == "模板"
    assert "看各地区销售额" in 文本
