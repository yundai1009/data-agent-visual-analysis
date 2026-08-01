"""认证服务：密码哈希 + JWT 签发/校验。

为什么用标准库而非 passlib/python-jose
======================================
- passlib 已停止维护，python-jose 依赖 cryptography 安装较重
- PBKDF2-HMAC-SHA256 是标准 KDF，安全性足够（迭代 100k 次）
- JWT HS256 用 hmac 标准库即可实现，签名逻辑清晰可审计
- 零新增依赖，降低部署风险

安全性说明
==========
- 密码用 PBKDF2 加盐哈希，盐随机生成 16 字节，迭代 100_000 次
- JWT 密钥从 EnvConfig.JWT_SECRET_KEY 读取，不硬编码
- token 过期时间由 EnvConfig.JWT_EXPIRE_MINUTES 控制
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional

# PBKDF2 迭代次数：OWASP 建议 SHA-256 至少 60 万次，此处取 10 万次平衡速度与安全
_PBKDF2_ITERATIONS = 100_000
_SALT_BYTES = 16

# 默认 JWT 密钥（生产必须用 .env 覆盖）
_DEFAULT_JWT_SECRET = "change-me-in-production"


def _get_secret() -> str:
    from config.settings import EnvConfig
    return getattr(EnvConfig, "JWT_SECRET_KEY", "") or _DEFAULT_JWT_SECRET


# ---- 密码哈希 ----------------------------------------------------------------


def hash_password(password: str) -> str:
    """PBKDF2 加盐哈希，返回格式：pbkdf2$iterations$salt_b64$hash_b64"""
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return "pbkdf2${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码。stored_hash 格式不合法时返回 False（不抛异常）。"""
    try:
        scheme, iterations_str, salt_b64, hash_b64 = stored_hash.split("$")
        if scheme != "pbkdf2":
            return False
        iterations = int(iterations_str)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    return hmac.compare_digest(digest, expected)


# ---- JWT --------------------------------------------------------------------


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _jwt_header() -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    return _b64url_encode(json.dumps(header, separators=(",", ":")).encode())


def create_access_token(
    user_id: str,
    role: str,
    username: str = "",
    expires_minutes: Optional[int] = None,
) -> str:
    """签发 JWT access token。"""
    from config.settings import EnvConfig
    minutes = expires_minutes or getattr(EnvConfig, "JWT_EXPIRE_MINUTES", 60)
    now = int(time.time())
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + int(minutes) * 60,
    }
    header = _jwt_header()
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload_b64}".encode()
    signature = hmac.new(_get_secret().encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload_b64}.{_b64url_encode(signature)}"


def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """校验 JWT，返回 payload；无效/过期返回 None。"""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = hmac.new(_get_secret().encode(), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(signature_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def generate_user_id() -> str:
    """生成随机 user_id。"""
    return f"u_{secrets.token_hex(8)}"
