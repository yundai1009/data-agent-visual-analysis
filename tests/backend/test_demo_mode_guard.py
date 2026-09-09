"""演示模式账号操作拦截专项测试（后端兜底）。

AUTH_ENABLED=false（演示模式）下后端返回 demo 虚拟用户（不在 users 表），
改密/注销会误报"旧密码不正确"、改名/导出会查无此人——账号类接口
必须直接返回明确错误，而不是误导性的验证失败。
"""
import pytest
from fastapi import HTTPException

from api.routes.auth import (
    _演示模式拦截账号操作,
    change_password,
    change_username,
    delete_account,
    export_user_data,
)
from config.settings import EnvConfig

_DEMO_USER = {"user_id": "demo", "username": "demo", "role": "analyst", "roles": ["analyst"]}


@pytest.fixture
def 演示模式(monkeypatch):
    monkeypatch.setattr(EnvConfig, "AUTH_ENABLED", False)


@pytest.fixture
def 正式模式(monkeypatch):
    monkeypatch.setattr(EnvConfig, "AUTH_ENABLED", True)


def test_演示模式_修改密码_明确拒绝(演示模式):
    with pytest.raises(HTTPException) as ei:
        change_password({"old_password": "x", "new_password": "y" * 6}, _DEMO_USER)
    assert ei.value.status_code == 400
    assert "演示模式" in ei.value.detail


def test_演示模式_修改用户名_明确拒绝(演示模式):
    with pytest.raises(HTTPException) as ei:
        change_username({"username": "someone"}, _DEMO_USER)
    assert ei.value.status_code == 400
    assert "演示模式" in ei.value.detail


def test_演示模式_注销账号_明确拒绝(演示模式):
    with pytest.raises(HTTPException) as ei:
        delete_account({"password": "whatever"}, _DEMO_USER)
    assert ei.value.status_code == 400
    assert "演示模式" in ei.value.detail


def test_演示模式_导出数据_明确拒绝(演示模式):
    with pytest.raises(HTTPException) as ei:
        export_user_data(_DEMO_USER)
    assert ei.value.status_code == 400
    assert "演示模式" in ei.value.detail


def test_正式模式_不拦截(正式模式):
    # 正式模式（AUTH_ENABLED=true）下不应触发演示拦截
    _演示模式拦截账号操作()  # 不应抛