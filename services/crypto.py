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
    """解密；无法解密（历史明文或密钥变更）时按原样返回并告警。"""
    if not value:
        return value
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        logger.warning("LLM Key 解密失败（按明文兼容返回，保存时将重新加密）: %s", type(exc).__name__)
        return value