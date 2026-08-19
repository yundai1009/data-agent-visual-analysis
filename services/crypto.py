"""静态加密工具（P1 加固：LLM API Key 不再明文落库）。

- 使用 cryptography 的 Fernet（AES-128-CBC + HMAC）。
- 密钥来源：LLM_KEY_ENCRYPTION_KEY 环境变量（生产显式配置）；缺省从
  JWT_SECRET_KEY SHA-256 派生（向后兼容本地开发，不新增必配项）。
- 读取侧兼容历史明文（解密失败按明文返回，保存时总是加密迁移）。
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from config.settings import EnvConfig

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    secret = EnvConfig.LLM_KEY_ENCRYPTION_KEY or EnvConfig.JWT_SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    _fernet = Fernet(key)
    return _fernet


def 加密(value: str) -> str:
    """加密并返回 token 字符串；空值原样返回。"""
    if not value:
        return value
    return _get_fernet().encrypt(value.encode()).decode()


def 解密(value: str) -> str:
    """解密；失败抛 ValueError（显式）。

    M6 修复：解密失败不再静默按明文返回。
    旧行为会把历史明文 key / 密钥轮换后无法解密的数据原样回传给调用方与内存，
    形同把"密文"当作可用 Key 使用——在 Key 遗忘/密钥轮换后安全风险。
    改为显式抛错，调用方捕获后降级为"未配置"。
    """
    if not value:
        return value
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise ValueError("LLM Key 解密失败（密钥不匹配/历史明文）") from exc