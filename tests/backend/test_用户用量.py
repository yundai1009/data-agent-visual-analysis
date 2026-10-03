# -*- coding: utf-8 -*-
"""阶段 53 · C10：账号页用量透明。

用户视角痛点：账号页只有改名/改密/注销，看不到"我今天用了多少次分析、
还剩多少配额"，只能等 429 被拦才知道。期望：
  - GET /auth/usage 返回本人用量（今日次数/token、近 30 天、配额上限与剩余）
  - 只统计本人（他人用量不串），无记录时为 0
  - 配额上限 0 = 不限（返回 null 而不是误导性的 0）
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("usage53")
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


def _send_and_get_code(client, email: str) -> str:
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    return _SENT_CODES[email]


def _reg(client, username):
    email = f"{username}@test.com"
    code = _send_and_get_code(client, email)
    r = client.post("/auth/register", json={"username": username, "email": email, "code": code, "password": "secret123"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    return tok, me["user_id"]


def test_未登录访问用量接口_401(client):
    r = client.get("/auth/usage")
    assert r.status_code == 401


def test_新用户用量为0且字段齐全(client):
    tok, _ = _reg(client, "usage53a")
    r = client.get("/auth/usage", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ("今日分析次数", "今日token", "每日次数上限", "每日token上限", "剩余次数", "近30天分析次数", "近30天token"):
        assert k in j, f"缺字段 {k}：{j}"
    assert j["今日分析次数"] == 0
    assert j["今日token"] == 0


def test_用量只统计本人_他人记录不串(client):
    from repositories import usage_repo
    tok_a, uid_a = _reg(client, "usage53b")
    tok_b, _ = _reg(client, "usage53c")
    # 直接给 A 写两条用量（避免真实调用 LLM）
    usage_repo.记录用量(uid_a, "deepseek", "deepseek-chat", 100, 50)
    usage_repo.记录用量(uid_a, "deepseek", "deepseek-chat", 200, 100)

    ja = client.get("/auth/usage", headers={"Authorization": f"Bearer {tok_a}"}).json()
    assert ja["今日分析次数"] == 2
    assert ja["今日token"] == 450  # (100+50)+(200+100)

    jb = client.get("/auth/usage", headers={"Authorization": f"Bearer {tok_b}"}).json()
    assert jb["今日分析次数"] == 0
    assert jb["今日token"] == 0


def test_剩余次数等于上限减今日次数_上限0时为null(client, monkeypatch):
    from config import settings
    from repositories import usage_repo
    tok, uid = _reg(client, "usage53d")
    monkeypatch.setattr(settings.EnvConfig, "LLM_DAILY_REQUEST_QUOTA", 200)
    usage_repo.记录用量(uid, "deepseek", "deepseek-chat", 10, 10)

    j = client.get("/auth/usage", headers={"Authorization": f"Bearer {tok}"}).json()
    assert j["每日次数上限"] == 200
    assert j["剩余次数"] == 199

    monkeypatch.setattr(settings.EnvConfig, "LLM_DAILY_REQUEST_QUOTA", 0)
    j2 = client.get("/auth/usage", headers={"Authorization": f"Bearer {tok}"}).json()
    assert j2["每日次数上限"] == 0
    assert j2["剩余次数"] is None  # 不限 → 不给误导性的 0