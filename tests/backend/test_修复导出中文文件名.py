# -*- coding: utf-8 -*-
"""阶段 61 后 spin-off · Fix：/auth/export 的 Content-Disposition 中文文件名断裂。

起因（ruff 死代码扫描挖出，非刻意构造）：api/routes/auth.py:614 的 f-string
用的是**单引号**，而 RFC 5987 的 filename* 固定写法是 `UTF-8''<pct-encoded>`——
里面那两个 `''` 在 py3.11（PEP 701 之前）会提前结束字符串字面量，
导致 `{quote(filename)}` 退化成纯文本。后端 200 照常返回、下载照常能下，
但 `filename*` 参数值是字面量 `{quote(filename)}`，浏览器只认 ASCII 兜底
`filename=export.json`——**中文文件名「我的数据-<用户名>.json」永远到不了浏览器**。

ruf 的信号：`quote` 报 F401、`filename` 报 F841——这两个名字在源码里"看起来用了"，
但解析器知道它们根本没进入插值。

本文件覆盖
==========
1. 函数级：`export_user_data` 返回的 StreamingResponse 的 Content-Disposition
   里 `filename*=` 后的值能被 `UTF-8''` 切分，且剩余部分 unquote 后
   == `我的数据-<用户名>.json`（红：现为字面量 `{quote(filename)}`）。
2. API 级：注册 → GET /auth/export → 200 + `content-disposition` 头带
   `UTF-8''` 前缀 + 不含 `{quote` 字面量。
3. 防回归：用户名含 `/`（change-username 不做字符白名单，注册才做）时，
   `filename*` 里不许出现裸 `/`（safe=''，红：现 quote 默认 safe='/' 原样留）。
"""
from __future__ import annotations

import os
import sys
from urllib.parse import quote, unquote

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
    tmp_dir = tmp_path_factory.mktemp("fix_export_cd")
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


def _取filename星(cd: str) -> str:
    """从 Content-Disposition 里取出 filename*= 的参数值（不含前缀）。"""
    assert "filename*=" in cd, f"头里没有 filename*=: {cd!r}"
    后 = cd.split("filename*=", 1)[1]
    assert 后.startswith("UTF-8''"), f"不是 RFC 5987 格式: {后!r}"
    return 后[len("UTF-8''"):].split(";", 1)[0].strip().strip('"')


# 1. 函数级：filename* 可反解出中文名 ========================================
def test_export_user_data_filename星可反解():
    from api.routes.auth import export_user_data
    user = {"user_id": "u1", "username": "测试用户"}
    resp = export_user_data(user)
    cd = resp.headers["content-disposition"]
    值 = _取filename星(cd)
    assert "{quote" not in 值, f"插值退化成字面量: {值!r}"
    assert unquote(值) == "我的数据-测试用户.json"


# 2. API 级：真实走一遍注册→导出 ============================================
def test_auth_export_头带中文文件名(client):
    tok = _注册(client, "导出用户")
    r = client.get("/auth/export", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    cd = r.headers["content-disposition"]
    值 = _取filename星(cd)
    assert "{quote" not in 值, f"插值退化成字面量: {值!r}"
    assert unquote(值) == "我的数据-导出用户.json"


# 3. 防回归：用户名含 / 时 filename* 里不许有裸斜杠 ==========================
def test_export_user_data_用户名含斜杠被编码():
    from api.routes.auth import export_user_data
    # change-username 不校验字符集（注册的 ^[a-zA-Z0-9_\-\u4e00-\u9fa5]+$ 只管注册），
    # 所以用户名里可能出现 '/'——quote 默认 safe='/' 会原样留，header 里就是分隔符。
    user = {"user_id": "u2", "username": "a/b"}
    resp = export_user_data(user)
    cd = resp.headers["content-disposition"]
    值 = _取filename星(cd)
    assert "/" not in 值, f"裸斜杠留在 filename* 里: {值!r}"
    assert unquote(值) == "我的数据-a/b.json"
    # 跟 quote(filename) 默认行为对照：不带 safe='' 时斜杠会被留下
    assert "/" in quote("我的数据-a/b.json"), "前置假设失效：quote 默认应保留 /"
