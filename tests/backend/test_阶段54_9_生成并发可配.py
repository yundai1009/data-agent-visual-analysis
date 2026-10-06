# -*- coding: utf-8 -*-
"""阶段 54-9 · Fix E3（压测 P2-6）· generate 信号量可配：

`_STREAM_SEMAPHORE = BoundedSemaphore(4)` 硬编码 → 默认 `max(4, os.cpu_count() or 4)`，
env `DAA_GENERATE_CONCURRENCY` 可覆盖。
- 默认值断言：= max(4, cpu_count)；
- env=2 → 占满 2 后第 3 个请求 503（验证可配，503 语义不破坏）；
- 非法 env 值回落默认。
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix549_e3_gen")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True

    from services import email_service

    def _fake_send(email: str, code: str) -> bool:
        _SENT_CODES[email] = code
        return True

    _orig_send = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake_send
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            yield c
    finally:
        email_service.发送验证码邮件 = _orig_send


def _register(client, username):
    email = f"{username}@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_生成并发上限_默认按核数(monkeypatch: pytest.MonkeyPatch):
    """E3：默认 = max(4, os.cpu_count() or 4)——不再硬编码 4。"""
    from api.routes.reports import _生成并发上限
    monkeypatch.delenv("DAA_GENERATE_CONCURRENCY", raising=False)
    assert _生成并发上限() == max(4, os.cpu_count() or 4)


def test_生成并发上限_env可覆盖(monkeypatch: pytest.MonkeyPatch):
    """E3：DAA_GENERATE_CONCURRENCY=2 → 上限=2（可配）。"""
    from api.routes.reports import _生成并发上限
    monkeypatch.setenv("DAA_GENERATE_CONCURRENCY", "2")
    assert _生成并发上限() == 2


def test_生成并发上限_非法env回落默认(monkeypatch: pytest.MonkeyPatch):
    """E3：非法/非正数 env 回落默认（不因配置错误静默崩服务）。"""
    from api.routes.reports import _生成并发上限
    monkeypatch.setenv("DAA_GENERATE_CONCURRENCY", "abc")
    assert _生成并发上限() == max(4, os.cpu_count() or 4)
    monkeypatch.setenv("DAA_GENERATE_CONCURRENCY", "0")
    assert _生成并发上限() == max(4, os.cpu_count() or 4)


def test_信号量按env可配_占满2后第3个503(client, monkeypatch: pytest.MonkeyPatch):
    """E3 端到端：env=2 创建的信号量占满 2 后，第 3 个 generate 请求仍 503
    （并发上限语义不破坏，只是上限值可配更高）。"""
    from api.routes import reports as _routes
    token = _register(client, "gen_user1")
    monkeypatch.setenv("DAA_GENERATE_CONCURRENCY", "2")
    sem2 = _routes._创建生成信号量()  # 按 env 重新创建（模块加载时已建过一次默认值）
    _原信号量 = _routes._STREAM_SEMAPHORE
    _routes._STREAM_SEMAPHORE = sem2
    held = []
    try:
        for _ in range(2):
            assert _routes._STREAM_SEMAPHORE.acquire(blocking=False), "应能占满 2 个并发名额"
            held.append(True)
        r = client.post(
            "/reports/generate",
            json={"数据集ID": "fake", "分析需求": "x"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 503, r.text
    finally:
        for _ in held:
            _routes._STREAM_SEMAPHORE.release()
        _routes._STREAM_SEMAPHORE = _原信号量
