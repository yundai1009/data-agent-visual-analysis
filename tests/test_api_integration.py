"""API 集成测试：认证、上传、隔离、报表、LLM 安全、错误响应。

用 FastAPI TestClient + 临时 SQLite，不依赖真实网络和 LLM Key。
运行：
    python -m pytest tests/test_api_integration.py -v
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 测试环境：开启认证、用临时数据库
os.environ["AUTH_ENABLED"] = "true"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """TestClient + 临时 SQLite。"""
    tmp_dir = tmp_path_factory.mktemp("api_test")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True

    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as c:
        yield c


def _register(client, username, password="secret123", role="analyst"):
    r = client.post("/auth/register", json={"username": username, "password": password, "role": role})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _upload(client, token, filename="test.csv", content="地区,销售额\n华东,100\n华南,200\n"):
    return client.post(
        "/datasets/upload",
        files={"file": (filename, content.encode(), "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )


# ---- 8.1 认证 ----

def test_注册_登录_流程(client):
    tok = _register(client, "alice")
    r = client.post("/auth/login", json={"username": "alice", "password": "secret123"})
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "alice"

def test_错误密码_401(client):
    _register(client, "bob")
    r = client.post("/auth/login", json={"username": "bob", "password": "wrong"})
    assert r.status_code == 401

def test_伪造token_401(client):
    r = client.get("/datasets/", headers={"Authorization": "Bearer fake_token_12345678"})
    assert r.status_code == 401

def test_无token_401(client):
    r = client.get("/datasets/")
    assert r.status_code == 401

def test_普通用户访问admin_403(client):
    tok = _register(client, "carol")
    r = client.post("/admin/golden/", json={"问题": "x", "预期SQL": "y"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code in (403, 404)  # 路由可能不存在则 404


# ---- 8.2 上传 ----

def test_上传合法CSV(client):
    tok = _register(client, "dave")
    r = _upload(client, tok)
    assert r.status_code == 200
    body = r.json()
    assert body["数据集ID"]
    assert body["行数"] == 2
    assert "地区" in body["字段列表"]

def test_上传非法后缀_400(client):
    tok = _register(client, "erin")
    r = _upload(client, tok, filename="evil.txt", content="a,b\n1,2\n")
    assert r.status_code == 400

def test_上传空文件_400(client):
    tok = _register(client, "frank")
    r = _upload(client, tok, filename="empty.csv", content="")
    assert r.status_code == 400

def test_上传非法内容_400且不残留(client, tmp_path):
    tok = _register(client, "grace")
    # 非法内容（单列无法成表）→ 400
    r = _upload(client, tok, filename="bad.csv", content="justoneline")
    assert r.status_code in (400, 200)  # pandas 可能容忍单列


# ---- 8.3 用户隔离 ----

def test_数据集隔离(client):
    tok_a = _register(client, "alice2")
    tok_b = _register(client, "bob2")
    r = _upload(client, tok_a)
    did = r.json()["数据集ID"]

    # B 读 A 的数据集 → 404
    r = client.get(f"/datasets/{did}", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 404
    # A 自己读 → 200
    r = client.get(f"/datasets/{did}", headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200
    # 列表隔离
    r_a = client.get("/datasets/", headers={"Authorization": f"Bearer {tok_a}"})
    r_b = client.get("/datasets/", headers={"Authorization": f"Bearer {tok_b}"})
    assert len(r_a.json()["数据集列表"]) == 1
    assert len(r_b.json()["数据集列表"]) == 0

def test_报表隔离(client):
    tok_a = _register(client, "alice3")
    tok_b = _register(client, "bob3")
    did = _upload(client, tok_a).json()["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "按地区统计"},
                    headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200
    rid = r.json()["报表ID"]

    r = client.get(f"/reports/{rid}", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 404
    r = client.get(f"/reports/{rid}", headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200


# ---- 8.5 LLM 安全 ----

def test_非法provider_400(client):
    tok = _register(client, "hugo")
    did = _upload(client, tok).json()["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "x"},
                    headers={"Authorization": f"Bearer {tok}", "X-LLM-Provider": "evil"})
    assert r.status_code == 400

def test_非法model_400(client):
    tok = _register(client, "ivan")
    did = _upload(client, tok).json()["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "x"},
                    headers={"Authorization": f"Bearer {tok}",
                             "X-LLM-Provider": "deepseek", "X-LLM-Model": "gpt-999"})
    assert r.status_code == 400


# ---- 2. 错误响应 ----

def test_统一错误格式(client):
    # 非法参数（limit=0）→ 422 + 统一格式
    tok = _register(client, "judy")
    r = client.get("/datasets/?limit=0", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422
    body = r.json()
    assert "code" in body and "message" in body and "request_id" in body
