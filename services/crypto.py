"""静态加密工具（P1 加固：LLM API Key 不再明文落库）。

- 使用 cryptography 的 Fernet（AES-128-CBC + HMAC）。
- 密钥来源：LLM_KEY_ENCRYPTION_KEY 环境变量（生产显式配置）；缺省从
  JWT_SECRET_KEY SHA-256 派生（向后兼容本地开发，不新增必配项）。
- 读取侧兼容历史明文（旧库在 P1 加密落地前存的 sk-... 明文 Key）：
  非密文令牌一律按明文返回，下次保存自动改写为加密存储（迁移零破坏）。
- M6 区分「历史明文」与「损坏密文」：只有结构上是合法 Fernet 令牌的才进解密；
  密文解密失败（密钥不匹配/被截断）才显式抛错、调用方降级“未配置”，
  不再把损坏密文当可用 Key 用。
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


def _是密文令牌(value: str) -> bool:
    """结构判定：是否形如合法 Fernet 令牌（用于在「历史明文」与「真密文」间分流）。

    Fernet 令牌 = urlsafe-base64( version(1, 恒为 0x80) || timestamp(8) ||
    iv(16) || ciphertext(16n) || hmac(32) )，故字节总长必为 57 + 16n 且首字节 0x80。
    只做结构校验、绝不尝试解密：历史明文 Key（sk-... 等）既不是合法 base64、
    又过不了长度/版本位，会被准确判为非密文；再用「回编一致」排除被宽容解码的明文。
    """
    if not value:
        return False
    try:
        raw = base64.urlsafe_b64decode(value.encode())
    except (ValueError, base64.binascii.Error):
        return False
    if len(raw) < 57 or (len(raw) - 57) % 16 != 0 or raw[0] != 0x80:
        return False
    return base64.urlsafe_b64encode(raw).decode() == value


def 解密(value: str) -> str:
    """解密；非密文历史明文原样返回；真密文解密失败显式抛 ValueError。

    M6 修复：损坏密文（密钥不匹配/被截断）不再静默按明文返回——
    旧行为会把解不开的密文原样回传给调用方与内存，形同把“密文”当可用 Key 用。
    但 M6 误伤了「历史明文 Key」：P1 加密落地前旧库的 sk-... 明文被同一刀判为
    “解密失败”并降级，导致 BYOK 静默回落共享 Key。这里先按结构分流：
    非密文令牌 = 历史明文 → 直接返回；密文才进 Fernet，解不开才抛错。
    """
    if not value:
        return value
    if not _是密文令牌(value):
        # 历史明文兼容：下次保存时 保存LLMKey/保存自定义供应商 会改写成加密存储
        return value
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise ValueError("LLM Key 解密失败（密钥不匹配/密文损坏）") from exc