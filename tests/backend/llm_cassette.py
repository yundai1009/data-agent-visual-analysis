# -*- coding: utf-8 -*-
"""自研 LLM VCR：把 chat_completion 的 HTTP 请求/响应录制为 cassette，离线回放。

为什么自研而不是 vcrpy（阶段 50）
- 项目原则：依赖轻、可讲解（同「为什么不用 langchain」的叙事；
  见 后端_核心/agent/llm_client.py 顶部注）；
- 本项目仅需拦 ``requests.post`` 这一个点，核心逻辑不到 60 行；
- JSON cassette 只存 url + 请求体 + 响应体，headers（含 Authorization）永不落盘——
  天然无密钥泄露面；vcrpy 默认连 headers 一起存，需额外配置过滤。

两种模式
- 回放（默认）：未设置 LLM_VCR_RECORD → 按请求指纹查 cassette，命中返回存储响应；
  未命中抛 ``CassetteMiss``（测试失败并提示如何录制）——CI 只红、不假绿。
- 录制：LLM_VCR_RECORD=1 → 走真实网络（无 script）或脚本响应（有 script，黄金样本
  生成用），并把响应落盘；新响应覆盖旧 cassette，git diff 可审查真实模型行为变化。

指纹：sha256(url + 请求体 JSON)。prompt / 工具 / 模型 / 温度任一变化都会 miss——
故意设计：行为变了就必须重新录制并人工审查 diff，这正是「LLM 链路回归」的意义。

录制（真实 Key，用户本机）：
    LLM_VCR_RECORD=1 python -m pytest tests/backend/test_llm_vcr.py
黄金样本（无 Key，CI 可离线跑）：
    python scripts/generate_llm_goldens.py
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# cassette 根目录：tests/cassettes/<scenario>/<指纹>.json
CASSETTES_ROOT = Path(__file__).resolve().parent.parent / "cassettes"


class CassetteMiss(Exception):
    """回放未命中：该请求缺少 cassette。"""


class FakeResponse:
    """回放用最小响应对象：只暴露 chat_completion 用到的 status_code / json()。"""

    def __init__(self, status_code: int, body: Dict[str, Any]):
        self.status_code = status_code
        self._body = body

    def json(self) -> Dict[str, Any]:
        return self._body


def _请求指纹(url: str, payload: Dict[str, Any]) -> str:
    """请求指纹：url + 请求体 JSON 的 sha256 前 24 位。"""
    raw = json.dumps({"url": url, "body": payload}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _cassette_path(scenario: str, fingerprint: str) -> Path:
    return CASSETTES_ROOT / scenario / f"{fingerprint}.json"


class LLMCassette:
    """一个测试场景的 cassette 上下文：把 requests.post 包装成回放 / 录制。

    用法（pytest fixture 内）：
        cassette = LLMCassette("react_multi_round")
        monkeypatch.setattr(requests, "post", cassette.wrap(requests.post))

    参数：
        scenario: cassette 目录名（一个测试场景一个目录）
        script: 录制时替代真实网络的脚本响应 callable(url, payload, call_index)
                -> OpenAI 格式响应 dict（黄金样本生成用）；None = 走真实网络
    """

    def __init__(
        self,
        scenario: str,
        script: Optional[Callable[[str, Dict[str, Any], int], Dict[str, Any]]] = None,
    ):
        self.scenario = scenario
        self.script = script
        self._real_post: Optional[Callable[..., Any]] = None
        self._calls = 0
        self.recording = os.getenv("LLM_VCR_RECORD") == "1"

    def wrap(self, real_post: Callable[..., Any]) -> Callable[..., Any]:
        """返回替换 requests.post 的包装函数。"""
        self._real_post = real_post

        def _post(url: str, *args: Any, **kwargs: Any) -> Any:
            payload: Dict[str, Any] = kwargs.get("json") or {}
            fp = _请求指纹(url, payload)
            path = _cassette_path(self.scenario, fp)

            if not self.recording:
                if path.exists():
                    entry = json.loads(path.read_text(encoding="utf-8"))
                    return FakeResponse(entry["status_code"], entry["json"])
                raise CassetteMiss(
                    f"cassette 缺失：tests/cassettes/{self.scenario}/{fp}.json\n"
                    f"请用真实 Key 录制：LLM_VCR_RECORD=1 python -m pytest "
                    f"tests/backend/test_llm_vcr.py\n"
                    f"或生成黄金样本：python scripts/generate_llm_goldens.py"
                )

            # ── 录制分支 ──
            if self.script is not None:
                body = self.script(url, payload, self._calls)
                self._calls += 1
                resp: Any = FakeResponse(200, body)
            else:
                assert self._real_post is not None
                resp = self._real_post(url, *args, **kwargs)

            # 安全：只落盘 url/请求体/响应体；headers（含 Authorization）永不保存
            entry = {
                "request": {"url": url, "json": payload},
                "status_code": int(resp.status_code),
                "json": resp.json(),
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return resp

        return _post