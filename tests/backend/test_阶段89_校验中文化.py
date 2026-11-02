# -*- coding: utf-8 -*-
"""阶段八十九：Pydantic 校验错误中文化（英文原文透出修复）。

问题：密码输 200 位时，后端返回
    {"message": "参数错误：password String should have at most 128 characters"}
用户看到的是英文原文。修法是在统一错误处理器里按 Pydantic 的 error type 翻译。
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.error_handlers import register_error_handlers  # noqa: E402


class _登录体(BaseModel):
    password: str = Field(..., min_length=1, max_length=128)
    username: str = Field(..., min_length=1, max_length=128)


class _分页体(BaseModel):
    limit: int = Field(..., ge=1, le=500)


def _应用() -> TestClient:
    from fastapi import Query

    应用 = FastAPI()
    register_error_handlers(应用)

    @应用.post("/login")
    def 登录(payload: _登录体):
        return {"ok": True}

    @应用.get("/list")
    def 列表(limit: int = Query(10, ge=1, le=500)):
        return {"ok": True}

    return TestClient(应用, raise_server_exceptions=False)


def test_密码超长_返回中文且不含英文原文():
    r = _应用().post("/login", json={"username": "u", "password": "x" * 200})
    assert r.status_code == 422
    msg = r.json()["message"]
    assert "参数错误" in msg
    assert "密码最多 128 个字符" in msg
    assert "String should have at most" not in msg, f"仍透出英文原文：{msg}"


def test_密码过短_返回中文():
    r = _应用().post("/login", json={"username": "u", "password": ""})
    assert r.status_code == 422
    msg = r.json()["message"]
    assert "密码至少 1 个字符" in msg
    assert "should have at least" not in msg


def test_缺少字段_返回缺X提示():
    r = _应用().post("/login", json={"username": "u"})
    assert r.status_code == 422
    assert "缺少密码" in r.json()["message"]


def test_数值越界仍是中文():
    r = _应用().get("/list", params={"limit": 0})
    assert r.status_code == 422
    assert "不能小于 1" in r.json()["message"]


def test_结构保持code_message_request_id三键():
    """既有前端 parseError 依赖这三个键，翻译层不能改动结构。"""
    r = _应用().post("/login", json={"username": "u", "password": "x" * 200})
    body = r.json()
    assert set(body.keys()) == {"code", "message", "request_id"}
    assert body["code"] == "VALIDATION_ERROR"


def test_未映射类型回落Pydantic原文_不丢信息():
    """翻译层只覆盖常见类型；未知类型必须回落到原文，绝不吞成笼统提示。"""
    from api.error_handlers import _中文校验错误

    说明 = _中文校验错误({"type": "some_future_error", "msg": "Future detail", "loc": ["body", "x"]})
    assert 说明 == "Future detail"


def test_真实登录接口_200位密码不再透出英文():
    """走真实 /auth/login：确保线上那条路径确实被中文化覆盖。"""
    os.environ.setdefault("AUTH_ENABLED", "true")
    from api.main import app as 真实应用

    with TestClient(真实应用, raise_server_exceptions=False) as c:
        r = c.post("/auth/login", json={"username": "u", "password": "x" * 200})
    assert r.status_code == 422, r.text
    msg = r.json()["message"]
    assert "密码最多 128 个字符" in msg
    assert "String should have at most" not in msg
