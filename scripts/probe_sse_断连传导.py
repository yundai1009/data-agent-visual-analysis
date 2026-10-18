"""探针：验证 Starlette StreamingResponse 在客户端断开时，取消信号能不能传导到生成器。

为什么要有这个探针（阶段六十九 修复的证据）：
阶段六十七 用**同步**生成器 `event_stream()` + `finally: cancel.set()` 做「用户关页面后
不再发起新的 LLM 调用」。但 Starlette 1.3.1 对同步生成器会先包一层
`iterate_in_threadpool`，客户端断连时 task group cancel 只关掉外层 async 包装，
内层同步生成器的 finally 要等 worker 推结束哨兵才跑 —— 那时分析早已跑完。
这类「单测绿、真机不生效」的洞只看代码看不出来，所以留一个可重跑的探针。

用法：python scripts/probe_sse_断连传导.py   （只用 8013 端口，不碰真库/真配置）
输出：两种生成器在「客户端读完首帧就 close()」后，各自 finally 的触发时刻。
预期（uvicorn 0.34.0 + starlette 1.3.1）：
  - /probe  同步生成器：finally 要等 worker 推哨兵（约 8s）才跑 → 取消不生效
  - /probe2 async generator：finally 在断连当刻（0.0x s）就跑 → 取消生效
"""

import asyncio
import json
import queue
import sys
import threading
import time
import urllib.request
from typing import Dict

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

PORT = 8013
BASE = f"http://127.0.0.1:{PORT}"
WORKER_SECONDS = 8.0  # 模拟「分析还在跑」
T0 = time.time()
触发: Dict[str, float] = {}

app = FastAPI()


def log(msg: str) -> None:
    print(f"{time.time() - T0:6.3f}s {msg}", flush=True)


def _worker(tag: str, q: "queue.Queue") -> None:
    time.sleep(WORKER_SECONDS)
    log(f"[{tag}] worker 跑完（{WORKER_SECONDS:.0f}s）")
    q.put(None)


def _记录(tag: str) -> None:
    触发[tag] = time.time() - T0
    log(f"[{tag}] GENERATOR FINALLY 触发")


@app.post("/probe")
def probe_sync():
    """同步生成器（阶段六十七 原实现形态）。"""
    q: "queue.Queue" = queue.Queue()
    threading.Thread(target=_worker, args=("sync", q), daemon=True).start()

    def gen():
        try:
            yield ": first\n\n"
            while True:
                ev = q.get()
                if ev is None:
                    break
                yield f"data: {json.dumps(ev)}\n\n"
        finally:
            _记录("sync")

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/probe2")
async def probe_async():
    """async generator（阶段六十九 修复后的形态）。"""
    q: "queue.Queue" = queue.Queue()
    threading.Thread(target=_worker, args=("async", q), daemon=True).start()

    async def gen():
        try:
            yield ": first\n\n"
            while True:
                ev = await asyncio.to_thread(q.get)
                if ev is None:
                    break
                yield f"data: {json.dumps(ev)}\n\n"
        finally:
            _记录("async")

    return StreamingResponse(gen(), media_type="text/event-stream")


def 起服务() -> None:
    def serve():
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")

    log(f"uvicorn {uvicorn.__version__}")
    threading.Thread(target=serve, daemon=True).start()
    for _ in range(80):
        try:
            urllib.request.urlopen(f"{BASE}/openapi.json", timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("探针服务没起来")


def 读首帧后断开(path: str, tag: str, 观察秒数: float) -> bool:
    """建连 → 读首帧 → 立刻 close 套接字（= 用户关页面）→ 看 finally 有没有在这段时间跑。"""
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=b"{}",
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=30)
    log(f"[{tag}] 客户端读到首帧 {r.readline()!r}")
    r.close()
    log(f"[{tag}] 客户端已断开（close 套接字）")
    time.sleep(观察秒数)
    断连当刻触发 = 触发.get(tag)
    if 断连当刻触发 is not None and 断连当刻触发 < WORKER_SECONDS - 1:
        log(f"[{tag}] ✅ 断连传导生效：finally 在 {断连当刻触发:.3f}s 就跑（远早于 worker 跑完）")
        return True
    log(f"[{tag}] ❌ 断连没有传导：{观察秒数:.0f}s 内 finally 没跑（要等 worker 推结束哨兵）")
    return False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    起服务()
    同步生效 = 读首帧后断开("/probe", "sync", 4.0)
    异步生效 = 读首帧后断开("/probe2", "async", 5.0)
    log("探针结束：" + f"同步生成器 {'生效' if 同步生效 else '不生效'} / async generator {'生效' if 异步生效 else '不生效'}")
    sys.exit(0 if (not 同步生效 and 异步生效) else 1)
