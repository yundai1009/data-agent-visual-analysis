# -*- coding: utf-8 -*-
"""阶段 51：删除数据集必须同步清理物理上传文件（数据卫生）。

链路：API 上传（物理文件落盘 data/uploads/{数据集ID}_{文件名}）→ 删除数据集
→ 断言 DB 记录已删 + 物理文件已同步删除（孤儿文件的源头被堵上）。
合并数据集（存储路径为空）删除不报错。
"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """TestClient + 临时 SQLite + 验证码捕获（同 test_api_integration 模式）。"""
    tmp_dir = tmp_path_factory.mktemp("data_hygiene")
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


def _上传(client, token, filename, content):
    return client.post(
        "/datasets/upload",
        files={"file": (filename, content.encode() if isinstance(content, str) else content, "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )


def _成功ID(resp):
    j = resp.json()
    assert "上传成功" in j, j
    return j["上传成功"][0]


def _删除(client, token, ds_id):
    return client.delete(f"/datasets/{ds_id}", headers={"Authorization": f"Bearer {token}"})


def test_删除数据集_物理文件同步删除(client):
    token = _注册(client, "hygiene1")
    resp = _上传(client, token, "阶段51删除测试.csv", "地区,销售额\n华东,100\n华南,200\n")
    上传项 = _成功ID(resp)
    ds_id, 文件名 = 上传项["数据集ID"], 上传项["文件名"]

    物理文件 = Path("data/uploads") / f"{ds_id}_{文件名}"
    assert 物理文件.exists(), "上传后物理文件应落盘"

    r = _删除(client, token, ds_id)
    assert r.status_code == 200, r.text
    assert not 物理文件.exists(), "删除数据集后物理文件必须同步删除（堵住孤儿文件源头）"


def test_删除数据集_合并产物空路径不报错(client):
    token = _注册(client, "hygiene2")
    a = _成功ID(_上传(client, token, "a_阶段51.csv", "地区,销售额\n华东,1\n"))
    b = _成功ID(_上传(client, token, "b_阶段51.csv", "地区,订单数\n华东,2\n"))
    r = client.post(
        "/datasets/merge",
        json={"数据集ID列表": [a["数据集ID"], b["数据集ID"]], "文件名": "合并_阶段51"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    合并ID = r.json()["数据集ID"]

    r = _删除(client, token, 合并ID)
    assert r.status_code == 200, r.text

    # 顺带清理本测试上传的两个源文件（避免给真实 uploads 目录留孤儿）
    assert _删除(client, token, a["数据集ID"]).status_code == 200
    assert _删除(client, token, b["数据集ID"]).status_code == 200