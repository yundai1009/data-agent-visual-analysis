# -*- coding: utf-8 -*-
"""阶段 54-5 · Fix 4 + Fix 5：50MB 上传边界 + Windows 文件名清洗。

Fix 4（Minor）：中间件 MAX_BODY_BYTES 按整个 multipart 请求体 Content-Length
拦截（含 boundary 头开销），接口层 _MAX_UPLOAD_BYTES 的 413 分支成了死代码
（恰好 50MB 文件被中间件 413）。方案 A：中间件上限给 1MB 余量
（50MB+1MB），接口层 50MB 业务限制真正生效。

Fix 5（Minor）：Path(f.filename).name 在 Windows 把 ":" 当路径分隔符截断
（a:b.csv → b.csv）静默改名入库。改为显式清洗：取末段路径组件（防穿越）
→ Windows 非法字符 : \\ / * ? " < > | 替换为 _ → 去首尾空白/点。

本文件覆盖
==========
Fix 4:
1. 中间件上限常量 = 50MB+1MB（红：现为 50MB）
2. 中间件 dispatch：Content-Length 超 51MB → 413；≤余量 → 穿透
3. 接口层业务 413 可达：monkeypatch _MAX_UPLOAD_BYTES 调小 → 业务文案
   「文件超过 50MB 限制」而非中间件文案
4. 真实边界：恰好 50MB+1B 文件 → 业务 413（红：现被中间件 413 拦截）
Fix 5:
5. a:b.csv → a_b.csv（红：现被 Windows 截断为 b.csv）
6. ..\\..\\evil.csv → evil.csv（路径穿越防护保留）
7. 超长文件名 → 400（长度校验作用于清洗后文件名）
"""

from __future__ import annotations

import asyncio
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
    tmp_dir = tmp_path_factory.mktemp("fix_upload")
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


def _上传(client, token, filename, content):
    return client.post(
        "/datasets/upload",
        files={"file": (filename, content, "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )


# ============================================================================
# Fix 4：中间件 50MB+1MB 余量 + 接口层分支可达
# ============================================================================

def _构造请求(total: int):
    """构造带指定 content-length 的 http scope（不传输真实 body，轻量测边界）。"""
    from starlette.requests import Request
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/datasets/upload",
        "raw_path": b"/datasets/upload",
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"content-length", str(total).encode()),
            (b"content-type", b"multipart/form-data; boundary=----fix54"),
            (b"host", b"testserver"),
        ],
        "client": ("127.0.0.1", 5555),
        "server": ("testserver", 80),
    }
    return Request(scope)


async def _穿透(request):
    from starlette.responses import Response
    return Response("ok", status_code=200)


class Test中间件余量:
    def test_上限为50MB加1MB余量(self):
        from api.middleware import MAX_BODY_BYTES
        # 红：现为 50MB（multipart boundary 头开销导致恰好 50MB 文件被误杀）
        assert MAX_BODY_BYTES == 51 * 1024 * 1024, (
            "中间件上限应 = 50MB+1MB 余量：总量防 DoS，单文件 50MB 业务限制交接口层"
        )

    def test_总长超51MB_中间件413(self):
        from api.middleware import RequestBodyLimitMiddleware
        mw = RequestBodyLimitMiddleware(_穿透)
        resp = asyncio.run(mw.dispatch(_构造请求(51 * 1024 * 1024 + 1), _穿透))
        assert resp.status_code == 413
        assert "请求体过大" in resp.body.decode()

    def test_总长50MB_可穿透到接口层(self):
        from api.middleware import RequestBodyLimitMiddleware
        mw = RequestBodyLimitMiddleware(_穿透)
        resp = asyncio.run(mw.dispatch(_构造请求(50 * 1024 * 1024), _穿透))
        assert resp.status_code == 200


class Test接口层分支可达:
    def test_小限额_业务413文案可达(self, client, monkeypatch):
        """monkeypatch 把业务限额调小 → 请求穿透中间件到达接口层，命中业务 413。"""
        token = _注册(client, "bnd1")
        monkeypatch.setattr("api.routes.datasets._MAX_UPLOAD_BYTES", 2048)
        r = _上传(client, token, "big.csv", b"0" * 4096)
        assert r.status_code == 400, r.text  # 单文件失败经批量包装返回 400
        assert "文件超过 50MB 限制" in r.text, r.text  # 业务文案（接口层）
        assert "请求体过大" not in r.text, r.text  # 非中间件文案

    def test_恰好50MB边界_业务413(self, client):
        """真实边界：50MB+1B 文件 → 穿透中间件，由接口层业务 413 拦截。

        红：现中间件按含 multipart 开销的总长拦截，返回中间件文案。
        """
        token = _注册(client, "bnd2")
        big = b"0" * (50 * 1024 * 1024 + 1)
        r = _上传(client, token, "fifty.csv", big)
        assert r.status_code == 400, r.text
        assert "文件超过 50MB 限制" in r.text, r.text
        assert "请求体过大" not in r.text, r.text


# ============================================================================
# Fix 5：Windows 文件名清洗
# ============================================================================

class Test文件名清洗:
    def test_冒号文件名不再被静默截断(self, client):
        """红：Path('a:b.csv').name 在 Windows 把 ':' 当分隔符 → 'b.csv'。"""
        token = _注册(client, "fn1")
        r = _上传(client, token, "a:b.csv", b"x,y\n1,2\n")
        assert r.status_code == 200, r.text
        item = r.json()["上传成功"][0]
        assert item["文件名"] == "a_b.csv", item
        # 入库名与响应一致
        d = client.get(f"/datasets/{item['数据集ID']}", headers={"Authorization": f"Bearer {token}"})
        assert d.status_code == 200, d.text
        assert d.json()["文件名"] == "a_b.csv"

    def test_路径穿越文件名被净化(self, client):
        """保留原路径穿越防护：..\\..\\evil.csv → evil.csv。"""
        token = _注册(client, "fn2")
        r = _上传(client, token, "..\\..\\evil.csv", b"x,y\n1,2\n")
        assert r.status_code == 200, r.text
        assert r.json()["上传成功"][0]["文件名"] == "evil.csv"

    def test_超长清洗后文件名400(self, client):
        """长度校验作用于清洗后文件名（清洗不会变长，超长即 400）。"""
        token = _注册(client, "fn3")
        long_name = "a" * 130 + ".csv"
        r = _上传(client, token, long_name, b"x,y\n1,2\n")
        assert r.status_code == 400, r.text
        assert "文件名过长" in r.text, r.text