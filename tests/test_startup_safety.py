"""启动安全自检专项测试（P0 第四道防线）。

覆盖：AUTH_ENABLED=false（免认证/演示）时监听地址必须是回环，
绑定 0.0.0.0 / :: 等非回环地址直接拒绝启动——物理上杜绝"公网免登录站"。
"""
import sys

import pytest

from api.main import _解析监听地址, _启动安全自检
from config.settings import EnvConfig


@pytest.fixture(autouse=True)
def _免认证环境(monkeypatch):
    """默认切到 AUTH_ENABLED=false，并把解析回退值钉死为回环。

    直接运行分支（python api/main.py）回退 EnvConfig.HOST；
    显式覆盖为回环，避免外部 API_HOST 环境变量干扰测试。
    """
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setattr(EnvConfig, "HOST", "127.0.0.1")


def _set_argv(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)


def test_缺省AUTH_ENABLED_拒绝启动(monkeypatch):
    monkeypatch.delenv("AUTH_ENABLED")
    with pytest.raises(RuntimeError, match="必须显式设置"):
        _启动安全自检()


def test_免认证_绑定0_0_0_0_拒绝启动(monkeypatch):
    _set_argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0"])
    with pytest.raises(RuntimeError, match="只允许本机访问"):
        _启动安全自检()


def test_免认证_绑定IPv6全通配_拒绝启动(monkeypatch):
    _set_argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", "::"])
    with pytest.raises(RuntimeError, match="只允许本机访问"):
        _启动安全自检()


def test_免认证_绑定非本机网卡IP_拒绝启动(monkeypatch):
    _set_argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host=192.168.1.5"])
    with pytest.raises(RuntimeError, match="只允许本机访问"):
        _启动安全自检()


def test_免认证_绑定回环_全部通过(monkeypatch):
    for host in ("127.0.0.1", "localhost", "::1"):
        _set_argv(monkeypatch, ["python", "-m", "uvicorn", "api.main:app", "--host", host])
        _启动安全自检()  # 不应抛


def test_免认证_直接运行回退回环_通过(monkeypatch):
    # 无 --host（python api/main.py → uvicorn.run(host=EnvConfig.HOST)=127.0.0.1）
    _set_argv(monkeypatch, ["python", "api/main.py"])
    _启动安全自检()  # 不应抛


def test_解析监听地址_空格与等号两种形态(monkeypatch):
    _set_argv(monkeypatch, ["uvicorn", "api.main:app", "--host", "0.0.0.0"])
    assert _解析监听地址() == "0.0.0.0"
    _set_argv(monkeypatch, ["uvicorn", "api.main:app", "--host=192.168.1.5"])
    assert _解析监听地址() == "192.168.1.5"
    # 无 --host → 回退 EnvConfig.HOST
    _set_argv(monkeypatch, ["uvicorn", "api.main:app", "--port", "8000"])
    assert _解析监听地址() == "127.0.0.1"
