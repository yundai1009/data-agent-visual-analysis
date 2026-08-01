"""认证接口：注册、登录、当前用户、登出。"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.dependencies import get_current_user
from repositories import user_repo
from services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=128)
    role: str = Field(default="analyst", pattern="^(analyst|admin)$")


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest) -> AuthResponse:
    """注册新用户，返回 token。"""
    password_hash = auth_service.hash_password(payload.password)
    try:
        user = user_repo.创建用户(payload.username, password_hash, payload.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    token = auth_service.create_access_token(user["user_id"], user["role"], user["username"])
    return AuthResponse(access_token=token, user=user)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    """用户名密码登录，返回 token。"""
    user = user_repo.按用户名查询(payload.username)
    if not user or not auth_service.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = auth_service.create_access_token(user["user_id"], user["role"], user["username"])
    return AuthResponse(
        access_token=token,
        user={
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "created_at": user["created_at"],
        },
    )


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """返回当前登录用户信息。"""
    return user


@router.post("/logout")
def logout() -> Dict[str, str]:
    """登出。无服务端 token 黑名单，由前端清理 token。"""
    return {"message": "已登出"}
