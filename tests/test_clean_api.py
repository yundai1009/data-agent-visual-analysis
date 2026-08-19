# -*- coding: utf-8 -*-
"""clean 接口回归测试（上线前审查 M13/M21 补测）：
- 清洗接口正常 200 且行数/列数正确
- 非法 fill_strategy → 400（M13）
- 数据集不存在 → 404
- 匿名 → 401
"""
from __future__ import annotations

import os
import sys
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("AUTH_ENABLED", "true")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("SEED_ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient

from api.main import app

_SENT: dict = {}


@pytest.fixture
def client(monkeypatch):
    from services import email_service
    monkeypatch.setattr(email_service, "发送验证码邮件", lambda mail, code: _SENT.__setitem__(mail, code))
    with TestClient(app) as c:
        yield c


def _register(client: TestClient, username: str) -> str:
    # username 加时间戳后缀防止跨测试会话重复
    uname = f"{username}{int(time.time()) % 100000}"
    email = f"{uname}@test.com"
    assert client.post("/auth/send-code", json={"email": email}).status_code == 200
    code = _SENT.get(email)
    assert code
    r = client.post("/auth/register", json={"username": uname, "email": email, "code": code, "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _upload(client: TestClient, tok: str) -> str:
    csv = "地区,销售额\n华东,100\n华南,200\n华东,150\n"
    r = client.post("/datasets/upload", headers={"Authorization": f"Bearer {tok}"},
                    files={"file": ("s.csv", csv.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["数据集ID"]


def test_清洗接口_200_行数列数正确(client):
    """M21 回归：clean 接口此前因 df 变量未定义 500（真实用户操作暴露）。"""
    tok = _register(client, "clean1")
    did = _upload(client, tok)
    r = client.post(f"/datasets/{did}/clean", headers={"Authorization": f"Bearer {tok}"},
                    params={"deduplicate": "true", "fill_missing": "true"})
    assert r.status_code == 200, f"clean 接口 500/异常: {r.text[:200]}"
    body = r.json()
    assert body["原行数"] == 3
    assert body["清洗后行数"] <= 3
    assert body["清洗前列数"] == 2


def test_非法fill_strategy_400(client):
    """M13：非法填充策略返回 400 而非 500。"""
    tok = _register(client, "clean2")
    did = _upload(client, tok)
    r = client.post(f"/datasets/{did}/clean", headers={"Authorization": f"Bearer {tok}"},
                    params={"fill_strategy": "bogus"})
    assert r.status_code == 400, f"期望 400，实际 {r.status_code}: {r.text[:150]}"


def test_数据集不存在_404(client):
    tok = _register(client, "clean3")
    r = client.post("/datasets/no-such-id/clean", headers={"Authorization": f"Bearer {tok}"},
                    params={"deduplicate": "true"})
    assert r.status_code == 404


def test_匿名清洗_401(client):
    r = client.post("/datasets/any/clean", params={"deduplicate": "true"})
    assert r.status_code == 401
