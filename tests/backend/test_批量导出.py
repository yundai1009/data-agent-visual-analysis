# -*- coding: utf-8 -*-
"""阶段 53 · D：批量导出（导出全部报表 ZIP）。

用户视角痛点：报表要一份份点开导出，多次下载被浏览器拦、文件散落。
期望：GET /reports/export-all 一次打包本人全部报表为 ZIP。
"""

import io
import os
import sys
import zipfile

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
    tmp_dir = tmp_path_factory.mktemp("batch53")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True
    from services import email_service

    def _fake_send(email: str, code: str) -> bool:
        _SENT_CODES[email] = code
        return True

    _orig = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake_send
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            yield c
    finally:
        email_service.发送验证码邮件 = _orig


def _send_and_get_code(client, email):
    client.post("/auth/send-code", json={"email": email})
    return _SENT_CODES[email]


def _reg(client, username):
    email = f"{username}@test.com"
    code = _send_and_get_code(client, email)
    r = client.post("/auth/register", json={"username": username, "email": email, "code": code, "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _make_report(client, tok, 需求="按y统计"):
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post("/datasets/upload", files={"file": ("a.csv", b"x,y\n1,2\n3,4\n", "text/csv")}, headers=h)
    j = r.json()
    did = j["上传成功"][0]["数据集ID"] if "上传成功" in j else j["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": 需求}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["报表ID"]


def test_导出全部_返回zip含全部报表(client):
    tok = _reg(client, "batch53a")
    _make_report(client, tok, "按y统计")
    _make_report(client, tok, "按x统计")
    r = client.get("/reports/export-all?format=xlsx", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert "zip" in r.headers.get("content-type", "")
    assert ".zip" in r.headers.get("content-disposition", "")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
    assert len(names) == 2, names
    assert all(n.endswith(".xlsx") for n in names), names


def test_导出全部_只含本人报表(client):
    tok_a = _reg(client, "batch53b")
    tok_b = _reg(client, "batch53c")
    _make_report(client, tok_a, "按y统计")
    _make_report(client, tok_b, "按x统计")
    r = client.get("/reports/export-all?format=csv", headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200, r.text
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
    assert len(names) == 1, names
    assert names[0].endswith(".csv")


def test_导出全部_重名报表不互相覆盖(client):
    tok = _reg(client, "batch53d")
    _make_report(client, tok, "同样标题一")
    _make_report(client, tok, "同样标题二")  # 标题取需求文本，两份不同
    r = client.get("/reports/export-all?format=csv", headers={"Authorization": f"Bearer {tok}"})
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = z.namelist()
    assert len(names) == 2
    assert len(set(names)) == 2, f"ZIP 内文件名冲突：{names}"


def test_导出全部_无报表返回明确提示(client):
    tok = _reg(client, "batch53e")
    r = client.get("/reports/export-all?format=xlsx", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400, r.text
    assert "暂无报表" in r.text


def test_导出全部_未登录401(client):
    r = client.get("/reports/export-all?format=xlsx")
    assert r.status_code == 401


def test_导出全部_非法格式422(client):
    tok = _reg(client, "batch53f")
    r = client.get("/reports/export-all?format=pdf", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422