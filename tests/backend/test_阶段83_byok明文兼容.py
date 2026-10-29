# -*- coding: utf-8 -*-
"""阶段八十三 · BYOK 历史明文 Key 读取回归（欠账 4 修复）。

锁住一条会被误杀的业务语义：P1 加密落地前旧库存的是 sk-... 明文 Key，
M6 让 解密() 对任何解不开的值一律抛错，误把「历史明文」当成「损坏密文」
降级，导致 BYOK 静默回落共享 Key、桌面 backend.log 反复刷「解密失败」。
修复后：非密文令牌（历史明文）原样返回，密文解密失败才抛错降级。

两条分支都要绿：
  1. 历史明文 sk-... 能原样读回（不再被误判解密失败）。
  2. 真密文但密钥不匹配 → 仍显式抛 ValueError（M6 的安全语义不丢）。
"""
import base64
import hashlib

import pytest

from services import crypto


def _派生(secret: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode()


def test_历史明文sk不做解密直接返回():
    # 结构分流：sk-... 不是合法 base64 令牌 → 视为历史明文原样返回
    assert crypto.解密("sk-account-12345678") == "sk-account-12345678"


def test_空值原样返回():
    assert crypto.解密("") == ""


def test_非base64明文不误判为密文():
    # 任意含特殊字符、长度/首字节不像 Fernet 的串都当明文
    for 明文 in ["hello-world", "abc", "AKIA-xxxx", "line1\nline2"]:
        assert crypto.解密(明文) == 明文


def test_合法密文能解_且用错误密钥抛错(monkeypatch):
    # 用密钥 A 加密，再用密钥 B 解密 → 仍属「密文」分支，但解不开 → 抛错（M6 语义保留）
    密文 = crypto.加密("sk-real-secret-key")
    assert crypto._是密文令牌(密文) is True
    monkeypatch.setattr(crypto.EnvConfig, "JWT_SECRET_KEY", "wrong-key")
    monkeypatch.setattr(crypto.EnvConfig, "LLM_KEY_ENCRYPTION_KEY", "")
    crypto._fernet = None  # 清缓存让派生用新密钥
    with pytest.raises(ValueError, match="解密失败"):
        crypto.解密(密文)


def test_结构判定只认_fernet_令牌():
    import os

    # 合法长度(73)但首字节不是 0x80 → 不是 Fernet 令牌（首字节钉死，避免随机 flake）
    假 = base64.urlsafe_b64encode(b"\x00" + os.urandom(72)).decode()
    assert crypto._是密文令牌(假) is False
    # 首字节对的短串也不行（长度不是 57+16n）
    assert crypto._是密文令牌(base64.urlsafe_b64encode(b"\x80abc").decode()) is False
    # 真密文认得
    assert crypto._是密文令牌(crypto.加密("x")) is True
