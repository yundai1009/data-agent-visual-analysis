# -*- coding: utf-8 -*-
"""阶段 54-5 · Fix 6：agent_mode 枚举校验 + replay 旧数据兜底。

走查证据
========
contracts.ReportGenerateRequest.agent_mode: str = Field("single", max_length=16)，
传 "hack" 也 200（静默回退 single）。

本文件覆盖
==========
1. agent_mode="hack" → 422（红：现在静默通过进入业务 404/400）
2. agent_mode="single" / "multi" → 200（合法值不受影响）
3. replay 读旧报表非法 agent_mode → 兜底 "single" 不 500
   （枚举校验上线前写入的旧数据不能炸掉 replay）
"""

from __future__ import annotations

import os
import sys

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
    tmp_dir = tmp_path_factory.mktemp("fix_agentmode")
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


def _上传数据集(client, token) -> str:
    r = client.post(
        "/datasets/upload",
        files={"file": ("t.csv", "地区,销售额\n华东,100\n华南,200\n", "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["上传成功"][0]["数据集ID"]


def _生成(client, token, did, agent_mode, 图表类型="表格"):
    return client.post("/reports/generate", json={
        "数据集ID": did,
        "分析需求": "查看全部数据",
        "图表类型": 图表类型,
        "agent_mode": agent_mode,
    }, headers={"Authorization": f"Bearer {token}"})


class Test枚举校验:
    def test_非法值_422(self, client):
        """红：现在 "hack" 静默通过校验，落到业务 404（数据集不存在）。"""
        token = _注册(client, "mode1")
        r = _生成(client, token, "fake", "hack")
        assert r.status_code == 422, r.text

    def test_合法single_200(self, client):
        token = _注册(client, "mode2")
        did = _上传数据集(client, token)
        r = _生成(client, token, did, "single")
        assert r.status_code == 200, r.text
        assert r.json()["agent_mode"] == "single"

    def test_合法multi_200(self, client):
        token = _注册(client, "mode3")
        did = _上传数据集(client, token)
        r = _生成(client, token, did, "multi")
        assert r.status_code == 200, r.text
        assert r.json()["agent_mode"] == "multi"


class Test重放兜底:
    def test_旧报表非法agent_mode_重放兜底single(self, client):
        """枚举校验上线前写入的脏数据（agent_mode=hack）重放必须兜底，不 500。"""
        token = _注册(client, "mode4")
        did = _上传数据集(client, token)
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        uid = r.json()["user_id"]

        from repositories import report_repo
        legacy = {
            "标题": "旧报表",
            "分析需求": "查看全部数据",
            "图表类型": "表格",
            "图表配置": {},
            "报表数据": [],
            "结论": "",
            "agent_mode": "hack",  # 旧数据脏枚举（枚举校验上线前写入）
        }
        rid = report_repo.保存报表(
            user_id=uid, dataset_id=did, title="旧报表", chart_type="表格", report=legacy,
        )
        r = client.post(f"/reports/{rid}/replay", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["agent_mode"] == "single"