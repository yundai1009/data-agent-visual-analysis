# -*- coding: utf-8 -*-
"""阶段 51：LLM 配额 API 级验证——共享 Key 超限 429、BYOK 豁免、重放同受限。

链路：_准备上下文（generate / generate-stream / replay 三路汇合点）在 LLM
花费前检查配额；超限 429 + 可读消息；用户自带 Key（x-llm-api-key 请求头）豁免。
"""
import os
import sys
from unittest import mock

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("quota_api")
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


def _注册(client, username, password="secret123"):
    email = f"{username}@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code, f"未捕获到 {email} 的验证码"
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _上传数据集(client, token):
    r = client.post(
        "/datasets/upload",
        files={"file": ("配额测试.csv", "地区,销售额\n华东,100\n华南,200\n".encode(), "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["上传成功"][0]["数据集ID"]


def _生成载荷(ds_id):
    return {"数据集ID": ds_id, "分析需求": "帮我看看整体情况"}


def test_共享Key超限_返回429且不生成报表(client):
    token = _注册(client, "quota1")
    ds_id = _上传数据集(client, token)
    with mock.patch("services.llm_quota.检查LLM配额", side_effect=__import__(
            "services.llm_quota", fromlist=["QuotaExceeded"]).QuotaExceeded(
            "已达今日 LLM 用量上限（1000000 / 1000000 token），请明天再试，或使用自己的 API Key（BYOK）"
    )) as 检查, mock.patch("api.routes.reports._单Agent报表") as 生成:
        resp = client.post(
            "/reports/generate",
            headers={"Authorization": f"Bearer {token}"},
            json=_生成载荷(ds_id),
        )
    assert resp.status_code == 429, resp.text
    assert "用量上限" in resp.json()["message"]
    生成.assert_not_called()


def test_共享Key未超限_正常生成(client):
    token = _注册(client, "quota2")
    ds_id = _上传数据集(client, token)
    resp = client.post(
        "/reports/generate",
        headers={"Authorization": f"Bearer {token}"},
        json=_生成载荷(ds_id),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["意图来源"] == "规则"  # 测试环境占位 key → 规则路径，配额门已放行


def test_BYOK请求头_豁免配额(client):
    token = _注册(client, "quota3")
    ds_id = _上传数据集(client, token)
    假报表 = {
        "标题": "配额豁免测试", "图表类型": "饼图",
        "图表配置": {"X轴": "地区", "Y轴": ["销售额"]},
        "报表数据": [], "数据画像": {}, "Agent Trace": [], "意图来源": "LLM",
        "推荐说明": {}, "风险提示": [], "导出数据": {}, "结论": "",
    }
    with mock.patch("services.llm_quota.检查LLM配额") as 检查, \
            mock.patch("api.routes.reports._单Agent报表", return_value=假报表) as 生成:
        resp = client.post(
            "/reports/generate",
            headers={"Authorization": f"Bearer {token}", "x-llm-api-key": "sk-user-own"},
            json=_生成载荷(ds_id),
        )
    assert resp.status_code == 200, resp.text
    检查.assert_not_called()          # BYOK 不查共享配额
    生成.assert_called_once()         # 越过配额门、正常进入生成


def test_重放报表_同样受配额限制(client):
    token = _注册(client, "quota4")
    ds_id = _上传数据集(client, token)
    gen = client.post(
        "/reports/generate",
        headers={"Authorization": f"Bearer {token}"},
        json=_生成载荷(ds_id),
    )
    assert gen.status_code == 200, gen.text
    报表ID = gen.json()["报表ID"]

    with mock.patch("services.llm_quota.检查LLM配额", side_effect=__import__(
            "services.llm_quota", fromlist=["QuotaExceeded"]).QuotaExceeded("已达今日分析次数上限")):
        resp = client.post(
            f"/reports/{报表ID}/replay",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )
    assert resp.status_code == 429, resp.text
    assert "次数上限" in resp.json()["message"]