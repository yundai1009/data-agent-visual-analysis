"""阶段六十九 回归：SSE 断连必须能在断连当刻置位取消令牌。

为什么单开一个文件而不是改阶段六十七的用例：阶段六十七的实现用的是**同步**生成器
`event_stream()`，Starlette 1.3.1 会把它包进 `iterate_in_threadpool`，客户端断连时
只关掉外层 async 包装，内层同步生成器的 `finally` 要等 worker 推结束哨兵才跑——
那时分析早跑完了，取消令牌等于形同虚设。

真机探针实测（scripts/probe_sse_断连传导.py，uvicorn 0.34.0 + starlette 1.3.1，
客户端读完首帧就 close()）：
  - 同步生成器：断连后 8.5s（worker 推哨兵那一刻）finally 才跑；
  - async generator：断连当刻 0.000s 就跑。
所以「body_iterator 是 async generator」是取消令牌生效的**不可见前提**，
这里把它钉成回归测试：一旦有人把 `event_stream` 改回 `def`，本文件立刻红。
"""

import asyncio
import inspect
import threading
from types import SimpleNamespace
from typing import Any, Dict

from api.contracts import ReportGenerateRequest


def _造响应(monkeypatch, 假流式):
    import api.routes.reports as 路由_mod

    monkeypatch.setattr(路由_mod, "_生成报表流式", 假流式)
    monkeypatch.setattr(路由_mod, "_准备上下文", lambda payload, request, user: (None, None))
    payload = ReportGenerateRequest(数据集ID="ds_1", 分析需求="帮我分析一下销售情况")
    return 路由_mod.generate_report_stream(payload, SimpleNamespace(headers={}), user={"user_id": "u_1"})


def test_流式body_iterator必须是async_generator(monkeypatch):
    """同步生成器会被 Starlette 包进线程池迭代器 → 断连传导不进来 → 令牌永不置位。"""

    def _假流式(payload, df, llm_config, user, on_event=None, source_page=None, cancel=None):
        if on_event:
            on_event({"type": "step", "data": {"说明": "第一步"}})
        return "r_测试", {"标题": "t", "图表类型": "柱状图"}

    响应 = _造响应(monkeypatch, _假流式)
    try:
        assert inspect.isasyncgen(响应.body_iterator), (
            "event_stream 不再是 async generator：Starlette 会用 iterate_in_threadpool "
            "包一层，客户端断连关不掉内层同步生成器，finally 里的 cancel.set() 要等 "
            "worker 推结束哨兵才跑 —— 取消令牌等于没实现（真机实测差 8.5 秒）"
        )
    finally:
        asyncio.run(响应.body_iterator.aclose())


def test_断连当刻置位令牌_不等worker跑完(monkeypatch):
    """worker 还在跑（没有推哨兵）时，仅关闭生成器就必须置位令牌。

    这正是真机上失效的那条路径：如果置位依赖 worker 推结束哨兵，用户关页面后
    整条分析照样把后续轮次的 LLM 全部烧完。
    """
    已推首帧 = threading.Event()
    可结束worker = threading.Event()
    worker已结束 = threading.Event()
    捕获: Dict[str, Any] = {}

    def _假流式(payload, df, llm_config, user, on_event=None, source_page=None, cancel=None):
        捕获["cancel"] = cancel
        if on_event:
            on_event({"type": "step", "data": {"说明": "第一步"}})
        已推首帧.set()
        可结束worker.wait(10)  # 模拟「分析还在跑」，绝不主动推结束哨兵
        worker已结束.set()
        return "r_测试", {"标题": "t", "图表类型": "柱状图"}

    响应 = _造响应(monkeypatch, _假流式)

    async def _读首帧后断开() -> str:
        迭代器 = 响应.body_iterator
        首条 = await 迭代器.__anext__()
        await 迭代器.aclose()  # 等价于 Starlette 在客户端断开时取消 stream_response
        return 首条

    首条 = asyncio.run(_读首帧后断开())
    try:
        assert "第一步" in 首条
        assert 已推首帧.wait(5), "worker 线程没有启动"
        assert 捕获.get("cancel") is not None, "令牌没有透传给 worker"
        assert not worker已结束.is_set(), "worker 已经跑完，这条用例就证明不了『断连当刻置位』"
        assert 捕获["cancel"].is_set(), "生成器已关闭（客户端断开）但令牌未置位：后续轮次仍会继续烧 Token"
    finally:
        可结束worker.set()
