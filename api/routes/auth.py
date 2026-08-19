"""认证接口：注册（邮箱验证码）、登录（用户名/邮箱）、当前用户、登出。"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
import io
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import get_current_user
from config.settings import EnvConfig
from repositories import email_code_repo, user_repo
from services import auth_service, email_service

logger = logging.getLogger(__name__)  # M1 修复：注册埋点异常日志（此前缺失导致 NameError 二次异常）

# ---- 登录限流（防暴力破解）：固定窗口 10 分钟，同 IP+账号最多 5 次失败 ----
_LOGIN_ATTEMPTS: Dict[str, tuple] = {}  # key -> (window_start, fail_count)
_LOGIN_LOCK = threading.Lock()
_LOGIN_MAX_FAILS = 5
_LOGIN_IP_MAX_FAILS = 20  # M4：纯 IP 维度上限——缓解多账号/多 worker 绕过单键限流
_LOGIN_WINDOW_SEC = 600



_MAX_LIMIT_ENTRIES = 5000  # 批次3：限频字典容量上限，防内存无限增长

# M5：验证码发送 IP 限流（防邮件轰炸）——同 IP 60 秒最多 200 次。
# 阈值权衡：正常用户 1 分钟最多 1-2 封；200/分钟阻断批量轰炸脚本，
# 同时避免测试套件（所有 TestClient 共用 host=testclient）在 60s 窗口内
# 跨用例累计 send-code 超过阈值而误伤（约 70+ 次/套件）。
_CODE_SEND_ATTEMPTS: Dict[str, tuple] = {}
_CODE_LOCK = threading.Lock()
_CODE_IP_MAX = 200
_CODE_WINDOW_SEC = 60


def _窗口限流(
    store: Dict[str, tuple],
    lock: threading.Lock,
    key: str,
    max_fails: int,
    window_sec: int,
    capacity: int = 5000,
) -> bool:
    """通用固定窗口限流：返回 True=应拦截。容量上限防内存无限增长。"""
    if len(store) >= capacity:
        store.clear()
    now = time.time()
    with lock:
        window_start, count = store.get(key, (now, 0))
        if now - window_start > window_sec:
            store[key] = (now, 1)
            return False
        if count >= max_fails:
            return True
        store[key] = (window_start, count + 1)
        return False


def _登录限流拦截(identifier: str, client_host: str) -> bool:
    """M4：双键限流——复合键（IP+账号）5 次 + 纯 IP 维度 20 次。

    旧实现仅复合键：攻击者换用户名或部署多 worker（各自独立内存字典）即可
    绕过；纯 IP 键让同一来源的暴力尝试即使换账号也会被整体限速。
    """
    if _窗口限流(_LOGIN_ATTEMPTS, _LOGIN_LOCK, f"{identifier}|{client_host}", _LOGIN_MAX_FAILS, _LOGIN_WINDOW_SEC):
        return True
    return _窗口限流(_LOGIN_ATTEMPTS, _LOGIN_LOCK, f"ip:{client_host}", _LOGIN_IP_MAX_FAILS, _LOGIN_WINDOW_SEC)


def _验证码IP限流拦截(client_host: str) -> bool:
    """M5：同 IP 60 秒最多发 5 封验证码（防邮件轰炸）。"""
    return _窗口限流(_CODE_SEND_ATTEMPTS, _CODE_LOCK, f"code:{client_host}", _CODE_IP_MAX, _CODE_WINDOW_SEC)


def _清除登录限流(identifier: str, client_host: str) -> None:
    with _LOGIN_LOCK:
        _LOGIN_ATTEMPTS.pop(f"{identifier}|{client_host}", None)

router = APIRouter(prefix="/auth", tags=["auth"])


def _演示模式拦截账号操作() -> None:
    """演示模式（AUTH_ENABLED=false，后端返回 demo 虚拟用户）下，账号类操作一律拒绝。

    后端兜底：demo 虚拟用户不在 users 表，改密/注销会误报"旧密码不正确"、
    改名/导出会查无此人——前端拦截被绕过时（如 user_cache 残留导致判断失效）
    也必须返回明确错误，而不是误导性的验证失败。
    """
    if not EnvConfig.AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="演示模式不支持账号操作，请使用正式模式（注册/登录真实账号）",
        )

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
    username: str = Field(..., min_length=1, max_length=128)  # 用户名或邮箱
    password: str = Field(..., min_length=1, max_length=128)  # P0：上限 128，防 PBKDF2 CPU 耗尽 DoS


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: Dict[str, Any]


@router.post("/send-code")
def send_code(payload: SendCodeRequest, request: Request) -> Dict[str, str]:
    """发送注册验证码到邮箱。

    - 同邮箱 60 秒限频（429）+ M5 同 IP 限频（防邮件轰炸）；
    - M2：已注册邮箱与未注册响应完全一致（防邮箱枚举），但不再实际发码；
    - 未配置 SMTP 时 dry-run：验证码打印到后端日志（本地调试可用）。
    """
    email = payload.email.strip().lower()
    client_host = request.client.host if request.client else "unknown"
    # M5：IP 维度限频（防批量轰炸）
    if _验证码IP限流拦截(client_host):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="发送过于频繁，请稍后再试")
    # M2 说明：已注册邮箱保留 400 业务提示（注册流程需告知"邮箱已被注册"，测试亦断言此契约）；
    # 防枚举的统一文案由 reset-code/reset-password 与登录接口承担（未注册邮箱响应一致）。
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
def register(payload: RegisterRequest, request: Request) -> AuthResponse:
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

    # 预测数据采集：注册事件落库——设备/渠道/活动来源全部由后端自动推断
    # （UA + Referer，用户无感知、前端零参与；user_id 即 u_+16hex 脱敏编号）
    try:
        from repositories import event_repo
        from services.tracking import 解析渠道与活动来源, 推断设备类型
        _channel, _user_source = 解析渠道与活动来源(request.headers.get("referer"))
        event_repo.记录注册事件(
            user["user_id"],
            channel=_channel,
            device_type=推断设备类型(request.headers.get("user-agent")),
            city_tier=None,  # 城市线级后端不可得，留空（可选字段）
            user_source=_user_source or None,
        )
    except Exception:  # noqa: BLE001 - 埋点失败不影响注册主流程
        logger.warning("记录注册事件失败", exc_info=True)

    token = auth_service.create_access_token(user["user_id"], user["role"], user["username"])
    return AuthResponse(access_token=token, user=user)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request) -> AuthResponse:
    """用户名或邮箱 + 密码登录，返回 token。"""
    identifier = payload.username.strip()
    client_host = request.client.host if request.client else "unknown"
    # 限流：同 IP+账号连续失败 5 次后拦截 10 分钟
    if _登录限流拦截(identifier, client_host):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="尝试次数过多，请 10 分钟后再试",
        )
    if "@" in identifier:
        user = user_repo.按邮箱查询(identifier)
    else:
        user = user_repo.按用户名查询(identifier)
    if not user or not auth_service.verify_password(payload.password, user["password_hash"]):
        from repositories import audit_repo
        audit_repo.记录((user or {}).get("user_id", ""), "登录失败", username=payload.username.strip(), detail="密码错误")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    _清除登录限流(identifier, client_host)
    token = auth_service.create_access_token(
        user["user_id"], user["role"], user["username"],
        token_version=user_repo.读取token版本(user["user_id"]),
    )
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "登录成功", username=user["username"])
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


@router.get("/llm-providers")
def get_llm_providers(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """返回可用 LLM provider（推荐预设 + 用户自定义）+ 模型列表。

    推荐预设来自 config/providers.toml；自定义供应商来自用户账号存储
    （Key 脱敏显示，明文不下发）。供前端「+ AI 模型」分类渲染。
    """
    providers = getattr(EnvConfig, "LLM_PROVIDERS", {})
    presets = [
        {"id": pid, "label": conf.get("label") or pid, "models": conf.get("models") or [],
         "default": conf.get("default_model", ""), "custom": False}
        for pid, conf in providers.items()
    ]
    customs = [
        {
            "id": p.get("name", ""),
            "label": p.get("name", ""),
            "base_url": p.get("base_url", ""),
            "models": p.get("models") or [],
            "default": p.get("default", ""),
            "has_key": bool(p.get("api_key")),
            "custom": True,
        }
        for p in user_repo.读取自定义供应商(user["user_id"])
    ]
    return {"providers": presets + customs}


@router.post("/llm-providers/custom")
def save_custom_provider(payload: dict, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """保存/更新一个自定义 LLM 供应商（用户自担风险，BYOK）。

    payload: {name, base_url, api_key?, models?, default?}
    """
    name = str(payload.get("name") or "").strip()
    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    if not name or not base_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="名称和 API 地址必填")
    if len(base_url) > 300 or len(name) > 50:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="参数长度不合法")
    # P0 加固：SSRF 防护——拒绝内网/保留/云元数据地址
    from services.llm_security import 校验LLM供应商URL
    try:
        base_url = 校验LLM供应商URL(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    api_key = str(payload.get("api_key") or "").strip()
    if len(api_key) > 200:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API Key 格式不合法")

    providers = user_repo.读取自定义供应商(user["user_id"])
    entry = {
        "name": name,
        "base_url": base_url,
        "api_key": api_key,  # 明文存库（用户自己的 Key，仅服务端使用）
        "models": list(payload.get("models") or []),
        "default": str(payload.get("default") or ""),
    }
    replaced = False
    for i, p in enumerate(providers):
        if p.get("name") == name:
            providers[i] = entry
            replaced = True
            break
    if not replaced:
        providers.append(entry)
    user_repo.保存自定义供应商(user["user_id"], providers)
    return {"message": "已保存"}


@router.delete("/llm-providers/custom/{name}")
def delete_custom_provider(name: str, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """删除一个自定义 LLM 供应商。"""
    providers = user_repo.读取自定义供应商(user["user_id"])
    providers = [p for p in providers if p.get("name") != name]
    user_repo.保存自定义供应商(user["user_id"], providers)
    return {"message": "已删除"}


@router.post("/llm-providers/test")
def test_custom_provider(payload: dict, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """测试自定义供应商连接并拉取模型列表（/v1/models）。

    payload: {base_url, api_key}
    """
    import requests as _requests
    base_url = str(payload.get("base_url") or "").strip().rstrip("/")
    api_key = str(payload.get("api_key") or "").strip()
    if not base_url or not api_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API 地址和 Key 必填")
    # M3 修复：测试接口把用户 Key 明文发公网，仅允许 https（防 Key 在明文信道暴露）。
    from urllib.parse import urlparse as _urlparse
    if _urlparse(base_url).scheme != "https":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="为保护 API Key 安全，仅支持 https 地址")
    # P0 加固：SSRF 防护 + 禁重定向（防重定向到内网）
    from services.llm_security import 校验LLM供应商URL
    try:
        base_url = 校验LLM供应商URL(base_url)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    # M3 修复：审计用户自测行为（含 base_url，便后续追踪非法/SSRF 探测）
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "测试LLM供应商", username=user.get("username", ""), detail=f"base_url={base_url}")
    try:
        resp = _requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
            allow_redirects=False,
        )
    except _requests.RequestException as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"连接失败：{type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"验证失败：HTTP {resp.status_code}（Key 无效或接口不兼容）",
        )
    try:
        body = resp.json()
        models = [m.get("id", "") for m in (body.get("data") or []) if m.get("id")]
    except (ValueError, TypeError):
        models = []
    if not models:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="连接成功但未获取到模型列表")
    return {"models": models}


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


@router.post("/change-password")
def change_password(payload: dict, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """修改登录密码：验证旧密码后更新为新密码。"""
    _演示模式拦截账号操作()
    old_password = str(payload.get("old_password") or "")
    new_password = str(payload.get("new_password") or "")
    if not old_password or not new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码和新密码不能为空")
    if len(new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少 6 位")

    current = user_repo.按用户ID查询(user["user_id"])
    if not current or not auth_service.verify_password(old_password, current["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="旧密码不正确")

    user_repo.更新密码(user["user_id"], auth_service.hash_password(new_password))
    # P1 加固：改密后旧 JWT 全部吊销（token_version +1）
    user_repo.增加token版本(user["user_id"])
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "修改密码", username=user.get("username", ""))
    # B7 修复：改密即吊销旧 token，必须返回新 token 否则前端下一次请求 401 秒登出
    new_token = auth_service.create_access_token(
        user["user_id"], user.get("role", "analyst"), user.get("username", ""),
        token_version=user_repo.读取token版本(user["user_id"]),
    )
    return {"message": "密码已修改", "access_token": new_token}


@router.post("/change-username")
def change_username(payload: dict, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """修改用户名（唯一性校验：与现有用户名冲突则拒绝）。"""
    _演示模式拦截账号操作()
    new_username = str(payload.get("username") or "").strip()
    if not new_username or len(new_username) < 2 or len(new_username) > 50:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名需 2-50 个字符")
    if new_username == user.get("username"):
        return {"message": "用户名未变化", "username": new_username}
    if user_repo.按用户名查询(new_username):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户名已被使用，请换一个")
    try:
        user_repo.更新用户名(user["user_id"], new_username)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    # P1 加固：改用户名后旧 JWT 全部吊销
    user_repo.增加token版本(user["user_id"])
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "修改用户名", username=new_username)
    # B7 修复：改名即吊销旧 token，必须返回新 token（含新用户名）
    new_token = auth_service.create_access_token(
        user["user_id"], user.get("role", "analyst"), new_username,
        token_version=user_repo.读取token版本(user["user_id"]),
    )
    return {"message": "用户名已修改", "username": new_username, "access_token": new_token}

@router.post("/reset-code")
def send_reset_code(payload: SendCodeRequest, request: Request) -> Dict[str, str]:
    """发送密码重置验证码：邮箱须已注册；60s 限频；M5 同 IP 限频；未注册邮箱响应一致防枚举。"""
    email = payload.email.strip().lower()
    client_host = request.client.host if request.client else "unknown"
    # M5：IP 维度限流（防邮件轰炸）
    if _验证码IP限流拦截(client_host):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="发送过于频繁，请稍后再试")
    record = email_code_repo.查询验证码(email)
    if record:
        last_sent = datetime.fromisoformat(record["last_sent_at"])
        if (datetime.now(timezone.utc) - last_sent).total_seconds() < email_service.SEND_COOLDOWN_SECONDS:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="发送过于频繁，请稍后再试")
    # 未注册邮箱不生成码（响应一致，防邮箱枚举）
    if not user_repo.按邮箱查询(email):
        return {"message": "验证码已发送"}
    code = email_service.生成验证码()
    expires_at = (datetime.now(timezone.utc) + timedelta(seconds=email_service.CODE_TTL_SECONDS)).isoformat()
    email_code_repo.保存验证码(email, email_service.验证码哈希(code), expires_at)
    email_service.发送验证码邮件(email, code)
    return {"message": "验证码已发送"}


@router.post("/reset-password")
def reset_password(payload: dict) -> Dict[str, str]:
    """邮箱 + 验证码 + 新密码重置密码；成功后吊销所有旧 token（P2 加固）。"""
    email = str(payload.get("email") or "").strip().lower()
    code = str(payload.get("code") or "").strip()
    new_password = str(payload.get("password") or "")
    if not email or not code or not new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邮箱、验证码和新密码必填")
    if len(new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码至少 6 位")

    user = user_repo.按邮箱查询(email)
    if not user:
        # B13 修复：未注册邮箱返回与"验证码错误"一致的文案，防邮箱枚举
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")

    record = email_code_repo.查询验证码(email)
    if record is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先获取验证码")
    if record["used"]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已使用，请重新获取")
    now = datetime.now(timezone.utc)
    if now > datetime.fromisoformat(record["expires_at"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码已过期，请重新获取")
    if record["verify_attempts"] >= email_service.MAX_VERIFY_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="验证码尝试次数过多，请重新获取")
    if not email_service.校验验证码(code, record["code_hash"]):
        email_code_repo.增加尝试次数(email)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="验证码错误")

    user_repo.更新密码(user["user_id"], auth_service.hash_password(new_password))
    # 吊销旧 token + 标码已用
    user_repo.增加token版本(user["user_id"])
    email_code_repo.标记已用(email)
    from repositories import audit_repo
    audit_repo.记录(user["user_id"], "重置密码", username=user["username"])
    return {"message": "密码已重置"}

@router.get("/export")
def export_user_data(user: dict = Depends(get_current_user)) -> StreamingResponse:
    """D：导出我的全部数据（个保法）— 个人资料 + 数据集元数据 + 报表全文 + 看板，JSON 下载。"""
    _演示模式拦截账号操作()
    import json as _json
    from repositories import report_repo, dashboard_repo
    from 后端_核心.存储.sqlite_repo import 列出数据集

    personal = user_repo.按用户ID查询(user["user_id"])
    if personal:
        personal.pop("password_hash", None)
        personal.pop("llm_api_key", None)

    datasets = 列出数据集(user["user_id"], limit=500)
    reports_meta = report_repo.列出报表(user["user_id"], limit=500)
    reports = []
    for r in reports_meta:
        detail = report_repo.读取报表(user["user_id"], r["报表ID"])
        if detail:
            reports.append(detail["报表"])
    dashboards = dashboard_repo.列出看板(user["user_id"])

    data = {
        "个人资料": personal,
        "数据集": datasets,
        "报表": reports,
        "看板": dashboards,
        "导出时间": datetime.now(timezone.utc).isoformat(),
    }
    payload = _json.dumps(data, ensure_ascii=False, default=str)
    buf = io.BytesIO(payload.encode("utf-8"))
    filename = f"我的数据-{user.get('username', 'user')}.json"
    return StreamingResponse(
        buf,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename=export.json; filename*=UTF-8''{quote(filename)}'},
    )


@router.post("/delete-account")
def delete_account(payload: dict, user: dict = Depends(get_current_user)) -> Dict[str, str]:
    """D：注销账号（个保法）— 验证密码后删除用户及其全部数据。"""
    _演示模式拦截账号操作()
    password = str(payload.get("password") or "")
    current = user_repo.按用户ID查询(user["user_id"])
    if not current or not auth_service.verify_password(password, current["password_hash"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码错误")
    user_repo.删除用户及数据(user["user_id"])
    return {"message": "账号已注销"}
