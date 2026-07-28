from __future__ import annotations

from typing import AsyncGenerator, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from config.settings import EnvConfig

security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    if not EnvConfig.AUTH_ENABLED:
        return {"user_id": "demo", "roles": ["analyst"]}
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息",
        )
    if not credentials.credentials or len(credentials.credentials.strip()) < 8:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证令牌",
        )
    # TODO: 替换为真实 JWT 校验
    return {"user_id": "demo", "roles": ["analyst"]}


def get_db_session():
    # TODO: 接入真实数据库会话
    yield None


def get_redis_client():
    # TODO: 接入真实 Redis 客户端
    return None


def get_chroma_client():
    # TODO: 接入真实 Chroma 客户端
    return None


def get_token_bucket():
    # TODO: 接入真实 Token 桶
    return None
