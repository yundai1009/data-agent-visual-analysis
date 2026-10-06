# -*- coding: utf-8 -*-
"""阶段 54-5 · Fix 3：generate_report async def → 普通 def（事件循环不被同步阻塞）。

走查证据
========
generate_report 是 async def，但在事件循环内同步调用 _准备上下文（读库/画像）
+ _生成报表流式（LLM 网络 I/O）——整个事件循环停摆：实测 1万×300 表生成时
/healthz 延迟 2241ms，8 并发完全串行（20.7s）。同文件 generate_report_stream
是普通 def（FastAPI 自动 run_in_threadpool），无此问题。

本文件覆盖
==========
1. 确定性断言：generate_report 必须是「非 coroutine 函数」（sync 端点）
   —— FastAPI 对 sync 端点自动丢线程池，LLM/画像同步阻塞不再卡死事件循环。
   （TestClient 计时并发不可靠，故用 inspect 固定端点形态，见测试内注释）
2. 前置保护：_流式并发配额（并发信号量）行为不变——占满 4 名额后
   generate 端点仍 503，改 def 不破坏并发防线。
"""

from __future__ import annotations

import inspect
import os
import sys
import threading

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix_eventloop")
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


def _注册(client, username):
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


def test_generate_report_是同步端点_不阻塞事件循环():
    """Fix 3 确定性断言。

    意图注释：async def + 循环内同步阻塞 = 事件循环停摆（服务级 DoS）。
    改普通 def 后 FastAPI 自动 run_in_threadpool，LLM/画像阻塞不再卡住
    /healthz 等所有异步请求。TestClient 并发精确计时不可靠（同进程共享
    事件循环），故用 inspect.iscoroutinefunction 把端点形态钉死为 sync：
    这是能确定断言该修复的测试（红：现在是 coroutine 函数 → 修复后绿）。
    """
    from api.routes.reports import generate_report
    assert inspect.iscoroutinefunction(generate_report) is False, (
        "generate_report 必须是普通 def（FastAPI 自动线程池），"
        "否则同步 LLM/画像调用会阻塞整个事件循环"
    )


def test_信号量并发配额_占满后仍503(client):
    """前置保护：改 def 后 _流式并发配额 作用不变——并发占满立即 503。

    Fix E3（阶段54-9）：默认并发上限改为 max(4, CPU核数)（本机可能 >4），
    占满名额数不再固定——测试显式把信号量替换为 BoundedSemaphore(4)，
    验证「并发上限存在、占满仍 503」语义不因上限值上调而破坏。
    """
    from api.routes import reports as _routes
    token = _注册(client, "sem5fix")
    _原信号量 = _routes._STREAM_SEMAPHORE
    _routes._STREAM_SEMAPHORE = threading.BoundedSemaphore(4)
    held = []
    try:
        for _ in range(4):
            assert _routes._STREAM_SEMAPHORE.acquire(blocking=False), "应能占满 4 个并发名额"
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