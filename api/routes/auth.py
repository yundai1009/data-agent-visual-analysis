"""认证接口：注册（邮箱验证码）、登录（用户名/邮箱）、当前用户、登出。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import get_current_user
from repositories import email_code_repo, user_repo
from services import auth_service, email_service

router = APIRouter(prefix="/auth", tags=["auth"])

# 简单邮箱格式校验（正则，避免引入 email-validator 依赖）
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterRequest(BaseModel):
    # extra="forbid"：拒绝一切多余字段（如 role=admin），杜绝自注册提权
    model_config = ConfigDict(extra="forbid")
    username: str = Field(..., min_length=2, max_length=50,
                          pattern=r"^[a-zA-Z0-9_\-\u4e00-\u9fa5]+$")  # 禁止 @，避免与邮箱登录歧义
    email: str = Field(..., pattern=_EMAIL_PATTERN)
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    password: str = Field(..., min_length=6, max_length=128)


class SendCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(..., pattern=_EMAIL_PATTERN)


class LoginRequest(BaseModel):
    username: str  # 用户名或邮箱
    password: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


@router.post("/send-code")
def send_code(payload: SendCodeRequest) -> Dict[str, str]:
    """发送注册验证码到邮箱。

    - 邮箱需未被注册；
    - 同邮箱 60 秒限频（429）；
    - 未配置 SMTP 时 dry-run：验证码打印到后端日志（本地调试可用）。
    """
    email = payload.email.strip().lower()
    if user_repo.按邮箱查询(email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱已被注册")

    record = email_code_repo.查询验证码(email)
    if record:
        last_sent = datetime.fromisoformat(record["last_sent_at"])
        if (datetime.now(timezone.utc) - last_sent).total_seconds() < email_service.SEND_COOLDOWN_SECONDS:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="发送过于频繁，请稍后再试")

    code = email_service.生成验证码()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=email_service.CODE_TTL_SECONDS)).isoformat()
    email_code_repo.保存验证码(email, email_service.验证码哈希(code), expires_at)
    email_service.发送验证码邮件(email, code)
    return {"message": "验证码已发送"}


@router.post("/register", response_model=AuthResponse)
def register(payload: RegisterRequest) -> AuthResponse:
    """邮箱验证码注册，注册成功固定为普通账号（analyst），不接收 role 字段。"""
    email = payload.email.strip().lower()

    # 1. 验证码校验（存在 / 未使用 / 未过期 / 尝试限频 / 内容匹配）
    record = email_code_repo.查询验证码(email)
    if record is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先获取验证码")
    if record["used"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已使用，请重新获取")
    now = datetime.now(timezone.utc)
    if now > datetime.fromisoformat(record["expires_at"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已过期，请重新获取")
    if record["verify_attempts"] >= email_service.MAX_VERIFY_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail="验证码尝试次数过多，请重新获取")
    if not email_service.校验验证码(payload.code, record["code_hash"]):
        email_code_repo.增加尝试次数(email)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")

    # 2. 邮箱未注册复查（send-code 已查，这里再查防竞态）
    if user_repo.按邮箱查询(email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该邮箱已被注册")

    # 3. 创建用户（固定 analyst）成功后标记验证码已用（防重放）
    password_hash = auth_service.hash_password(payload.password)
    try:
        user = user_repo.创建用户(payload.username, password_hash, role="analyst", email=email)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    email_code_repo.标记已用(email)

    token = auth_service.create_access_token(user["user_id"], user["role"], user["username"])
    return AuthResponse(access_token=token, user=user)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> AuthResponse:
    """用户名或邮箱 + 密码登录，返回 token。"""
    identifier = payload.username.strip()
    if "@" in identifier:
        user = user_repo.按邮箱查询(identifier)
    else:
        user = user_repo.按用户名查询(identifier)
    if not user or not auth_service.verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    token = auth_service.create_access_token(user["user_id"], user["role"], user["username"])
    return AuthResponse(
        access_token=token,
        user={
            "user_id": user["user_id"],
            "username": user["username"],
            "role": user["role"],
            "email": user.get("email"),
            "created_at": user["created_at"],
        },
    )


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """返回当前登录用户信息。"""
    return user


# ---- 账号级 LLM Key（BYOK 后端存储）----


@router.get("/llm-key")
def get_llm_key(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """返回账号是否已配置 LLM Key（不回传明文，仅脱敏后缀）。"""
    api_key = user_repo.读取LLMKey(user["user_id"])
    masked = f"sk-…{api_key[-4:]}" if len(api_key) >= 8 else ""
    return {"has_key": bool(api_key), "masked": masked}


@router.put("/llm-key")
def put_llm_key(payload: dict, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """保存账号级 LLM Key（仅服务端使用，不进入日志与响应）。"""
    api_key = str(payload.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API Key 不能为空")
    if len(api_key) > 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API Key 格式不合法")
    user_repo.保存LLMKey(user["user_id"], api_key)
    return {"message": "已保存"}


@router.delete("/llm-key")
def delete_llm_key(user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """清除账号级 LLM Key，回退服务端 .env Key。"""
    user_repo.清除LLMKey(user["user_id"])
    return {"message": "已清除"}


@router.post("/logout")
def logout() -> Dict[str, str]:
    """登出。无服务端 token 黑名单，由前端清理 token。"""
    return {"message": "已登出"}
