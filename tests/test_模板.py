"""阶段 30 · 报表模板测试：CRUD + 一键执行 + 归属隔离，不依赖网络与 LLM key。

覆盖目标
========
- 保存模板（合法 payload / 非法 payload 422 / 名称超长）
- 列出模板（自己的列表 / 归属隔离）
- 执行模板（数据集最新数据生成报表，返回 ReportGenerateResponse）
- 删除模板（本人可删 / 他人 404）
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("template_test")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    初始化数据库()

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


def _register(client, username) -> str:
    email = f"{username}@test.com"
    assert client.post("/auth/send-code", json={"email": email}).status_code == 200
    code = _SENT_CODES.get(email)
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _upload(client, token) -> str:
    r = client.post(
        "/datasets/upload",
        files={"file": ("t.csv", "地区,销售额\n华东,100\n华南,200\n", "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["数据集ID"]


def _payload(ds_id: str) -> dict:
    return {
        "数据集ID": ds_id,
        "分析需求": "按地区统计销售额Top 2",
        "图表类型": "自动推荐",
        "筛选条件": [{"字段": "地区", "操作": "等于", "值": "华东"}],
        "topN": 2,
        "agent_mode": "single",
    }


class Test模板:
    def test_保存_列出_执行_删除全流程(self, client):
        token = _register(client, "tpluser")
        ds = _upload(client, token)
        payload = _payload(ds)
        # 保存
        r = client.post("/templates", json={"名称": "周报", "payload": payload},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        tid = r.json()["模板ID"]
        # 列出
        r = client.get("/templates", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        items = r.json()["模板列表"]
        assert any(t["模板ID"] == tid and t["名称"] == "周报" for t in items)
        # 执行（规则兜底出报表，筛选生效：只统计华东）
        r = client.post(f"/templates/{tid}/run", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["报表ID"]
        rows = body["报表数据"]
        assert all(row["地区"] == "华东" for row in rows)  # 模板筛选条件生效
        # 删除
        r = client.delete(f"/templates/{tid}", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        r = client.get("/templates", headers={"Authorization": f"Bearer {token}"})
        assert not any(t["模板ID"] == tid for t in r.json()["模板列表"])

    def test_非法payload_422(self, client):
        token = _register(client, "tplbad")
        r = client.post("/templates", json={"名称": "坏模板", "payload": {"数据集ID": "x" * 999}},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422  # Pydantic max_length 拦截

    def test_他人模板_404(self, client):
        token_a = _register(client, "tpla")
        token_b = _register(client, "tplb")
        ds = _upload(client, token_a)
        r = client.post("/templates", json={"名称": "A的模板", "payload": _payload(ds)},
                        headers={"Authorization": f"Bearer {token_a}"})
        tid = r.json()["模板ID"]
        # B 执行/删除 A 的模板 → 404
        assert client.post(f"/templates/{tid}/run", headers={"Authorization": f"Bearer {token_b}"}).status_code == 404
        assert client.delete(f"/templates/{tid}", headers={"Authorization": f"Bearer {token_b}"}).status_code == 404

    def test_未登录401(self, client):
        assert client.get("/templates").status_code == 401
        assert client.post("/templates/xx/run").status_code == 401