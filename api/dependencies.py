"""FastAPI 依赖注入：认证、鉴权、会话等。

认证策略（阶段 3 起）
====================
- `AUTH_ENABLED=true` 时：强制 JWT 校验，任意伪造 token 直接 401
- `AUTH_ENABLED=false` 时：仍返回 demo 用户（开发便利），但保留校验逻辑
- `require_admin`：普通用户访问返回 403
"""

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import EnvConfig
from services import auth_service

security = HTTPBearer(auto_error=False)


def _demo_user() -> dict:
    """开发模式下的占位用户。"""
    return {"user_id": "demo", "username": "demo", "roles": ["analyst"]}


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """解析当前登录用户。

    - AUTH_ENABLED=false：返回 demo 用户（开发便利）
    - AUTH_ENABLED=true：校验 JWT，失败抛 401
    """
    if not EnvConfig.AUTH_ENABLED:
        return _demo_user()

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息",
        )

    payload = auth_service.verify_access_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌无效或已过期",
        )

    # P1 加固：JWT 吊销校验——载荷 token_version 必须等于当前用户版本（改密/改用户名后旧 token 失效）
    from repositories import user_repo as _repo
    if int(payload.get("ver") or 0) != _repo.读取token版本(payload.get("sub", "")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌已失效，请重新登录",
        )

    return {
        "user_id": payload.get("sub", ""),
        "username": payload.get("username", ""),
        "role": payload.get("role", "analyst"),
        "roles": [payload.get("role", "analyst")],
    }


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理员权限依赖：普通用户访问返回 403。"""
    roles = user.get("roles") or []
    if "admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user


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
