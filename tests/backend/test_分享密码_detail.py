# -*- coding: utf-8 -*-
"""阶段 53 · A3：分享密码错误区分——无密码与密码错误给出不同 detail，
前端才能做到"首次打开不显示'密码不正确'"。"""

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
    """TestClient + 临时 SQLite + 验证码捕获。"""
    tmp_dir = tmp_path_factory.mktemp("share53")
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
    code = _SENT_CODES.get(email)
    assert code, f"未捕获到 {email} 的验证码"
    return code


def _reg(client, username):
    email = f"{username}@test.com"
    code = _send_and_get_code(client, email)
    r = client.post("/auth/register", json={"username": username, "email": email, "code": code, "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def test_分享密码_无密码与错误密码_detail区分(client):
    tok = _reg(client, "sharepwd53")
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post("/datasets/upload", files={"file": ("a.csv", b"x,y\n1,2\n3,4\n", "text/csv")}, headers=h)
    j = r.json()
    did = j["上传成功"][0]["数据集ID"] if "上传成功" in j else j["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "按y统计"}, headers=h)
    rid = r.json()["报表ID"]
    r = client.post(f"/reports/{rid}/share?密码=abc123", headers=h)
    sid = r.json()["链接ID"]

    # 无密码：message = 需要访问密码（前端据此只显示密码框，不报"密码不正确"）
    r = client.get(f"/share-data/{sid}")
    assert r.status_code == 401
    assert r.json()["message"] == "需要访问密码", r.json()

    # 错误密码：message = 访问密码不正确（前端据此提示"密码不正确，请重试"）
    r = client.get(f"/share-data/{sid}?password=wrong")
    assert r.status_code == 401
    assert r.json()["message"] == "访问密码不正确", r.json()

    # 正确密码：200
    r = client.get(f"/share-data/{sid}?password=abc123")
    assert r.status_code == 200 and "图表配置" in r.json()

    # 不带密码的普通分享：无密码字段 → 200（不受影响）
    r2 = client.post(f"/reports/{rid}/share", headers=h)
    sid2 = r2.json()["链接ID"]
    assert client.get(f"/share-data/{sid2}").status_code == 200