"""FastAPI 依赖注入：认证、鉴权、会话等。

认证策略（阶段 3 起）
====================
- `AUTH_ENABLED=true` 时：强制 JWT 校验，任意伪造 token 直接 401
- `AUTH_ENABLED=false` 时：仍返回 demo 用户（开发便利），但保留校验逻辑
- `require_admin`：普通用户访问返回 403
"""

# =============================================================================
# 文件总览（面试讲解版）
# =============================================================================
# 【文件层级】项目根目录/api/dependencies.py —— API 层（FastAPI 依赖注入）
# 【负责功能】把"当前登录用户"解析成路由可直接使用的 user dict，分三道关：
#   1. get_current_user：认证依赖——免认证降级 / JWT 验票 / token_version 吊销对账
#   2. require_admin：鉴权依赖——非管理员一律 403
#   3. _demo_user：免认证模式下的固定占位用户
# 【依赖文件】
#   - config/settings.py（EnvConfig）：读取 AUTH_ENABLED 认证开关
#   - services/auth_service.py：verify_access_token 完成签名与过期校验
#   - repositories/user_repo.py：读取用户当前 token 版本号做吊销比对
# 【调用关系】路由声明 user: dict = Depends(get_current_user) 时，FastAPI 在每次
#             请求进入路由函数之前自动执行本文件的解析逻辑；校验失败抛出的
#             HTTPException 会直接转成 401/403 响应，路由函数根本不会执行。
# =============================================================================

from __future__ import annotations

from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from config.settings import EnvConfig
from services import auth_service

# 认证提取器：自动从 "Authorization: Bearer <token>" 头中取出 token 交给依赖。
# auto_error=False 很关键：没带 token 时不自动 401，把判断权留给下方业务逻辑，
# 这样免认证模式下不带 token 也能放行 demo 用户（两种模式共用同一依赖）。
security = HTTPBearer(auto_error=False)


# 【函数】构造免认证模式下的占位用户（AUTH_ENABLED=false 时所有请求都视为此人）。
# 入参：无
# 返回：dict —— 固定身份 {"user_id": "demo", "username": "demo", "roles": ["analyst"]}
# 业务定位：演示/开发模式免登录可用；角色只有 analyst 没有 admin，天然演示不了
#           管理功能，避免给人"免认证 = 管理员权限"的错误印象。
def _demo_user() -> dict:
    """开发模式下的占位用户。"""
    # 固定 user_id="demo"：所有会话共享同一身份，便于本地联调，不落库
    return {"user_id": "demo", "username": "demo", "roles": ["analyst"]}


# 【函数】FastAPI 认证依赖：把每个请求解析成"当前登录用户"字典。
# 入参：credentials —— FastAPI 自动注入的 Bearer 凭据对象（内含 token 字符串），
#       未携带 Authorization 头时为 None
# 返回：dict —— 形如 {"user_id":..., "username":..., "role":..., "roles":[...]}
# 业务定位：所有受保护路由的入口关卡（路由里写 Depends(get_current_user) 即启用）；
#           校验失败抛 HTTPException(401) 直接终止请求，路由函数根本不会执行。
def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> dict:
    """解析当前登录用户。

    - AUTH_ENABLED=false：返回 demo 用户（开发便利）
    - AUTH_ENABLED=true：校验 JWT，失败抛 401
    """
    # ---- 第 1 关：免认证模式直接放行 ----
    # 【关键行】AUTH_ENABLED=false 时跳过一切校验，短路返回 demo 用户。
    # 为什么：演示/开发环境不想搭登录流程，又要让前端所有依赖 user_id 的页面
    #         能跑通；开关由环境变量控制，且生产环境被 main.py 安全自检强制为 true。
    # 删除后果：演示模式全站 401，本地开发与展厅演示直接不可用。
    # 替代方案：给 demo 用户也签发一个真 JWT（更接近生产，但演示部署要多一步
    #           初始化）；当前"开关短路"最直白、零额外状态。
    if not EnvConfig.AUTH_ENABLED:
        return _demo_user()

    # ---- 第 2 关：凭证必须存在 ----
    # 【关键行】没带 Authorization 头或 token 为空 → 直接 401。
    # 为什么：认证模式下"无凭证"与"凭证无效"必须区分——无凭证说明客户端根本没
    #         登录，先拦截可避免无谓的验票计算，也让错误提示更准确。
    # 删除后果：credentials 为 None 时继续往下走，verify_access_token 收到空值
    #         走异常分支，行为不可控、日志难排查。
    # 替代方案：把 HTTPBearer 的 auto_error 设为 True 自动抛 401——但那样免认证
    #           模式也会被拦死，所以必须手动判断（当前写法两模式共用同一依赖）。
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息",
        )

    # ---- 第 3 关：验票（签名 + 过期）----
    # 交给 auth_service 做签名比对与过期检查；返回 None = 伪造/篡改/已过期
    payload = auth_service.verify_access_token(credentials.credentials)
    if payload is None:
        # 【关键行】验票失败 → 401：token 无效或过期，要求重新登录。
        # 为什么：这是认证的"最后一道闸"——签名对不上说明 token 不是本服务器
        #         签发（或被篡改），exp 已过说明会话到期；两者都必须拒绝。
        # 删除后果：伪造 token 也能通过依赖注入，任何人可冒充任意身份调接口。
        # 替代方案：按规范应同时返回 WWW-Authenticate 响应头提示认证方式；
        #           当前 detail 文案已足够前端弹出"请重新登录"。
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌无效或已过期",
        )

    # ---- 第 4 关：吊销对账（P1 加固）----
    # P1 加固：JWT 吊销校验——载荷 token_version 必须等于当前用户版本（改密/改用户名后旧 token 失效）
    # 为什么：JWT 无状态、签发后服务端无法主动作废，只能靠版本号对账实现"改密码/改名后旧 token 全部失效"。
    # 删除后果：改密码后旧 token 依然有效，被泄露的 token 永久可用，会话吊销形同虚设。
    # 替代方案：Redis 黑名单/白名单缓存（性能更好但引入外部依赖）；当前"每请求查库比对"在单机场景够用且零依赖。
    from repositories import user_repo as _repo
    # S4 修复：用户不存在（读取token版本返回 None）时旧 JWT 一律失效——
    # 删号后 ver=0 的旧 token 不得继续通过对账（旧实现 None→0 与 ver=0 相等，
    # 形成"删号后旧 token 仍可认证"的漏洞）。
    _ver = _repo.读取token版本(payload.get("sub", ""))
    if _ver is None or int(payload.get("ver") or 0) != _ver:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证令牌已失效，请重新登录",
        )

    # 组装路由层统一使用的用户字典：roles 用列表形式，便于 require_admin 做成员判断
    return {
        "user_id": payload.get("sub", ""),
        "username": payload.get("username", ""),
        "role": payload.get("role", "analyst"),
        "roles": [payload.get("role", "analyst")],
    }


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """可选登录依赖（阶段 31 · 协作者分享用）：有 token 且有效 → 用户 dict；否则 None。

    与 get_current_user 的区别：不抛 401——"访客可看公开分享、登录用户可看协作者分享"
    的场景需要区分"未登录"与"登录但不是协作者"两种状态。
    """
    if not EnvConfig.AUTH_ENABLED:
        return _demo_user()
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = auth_service.verify_access_token(credentials.credentials)
    except Exception:
        return None
    if payload is None:
        return None
    from repositories import user_repo as _repo
    try:
        # S4 修复：同 get_current_user——用户不存在（None）视为无效 token
        _ver = _repo.读取token版本(payload.get("sub", ""))
        if _ver is None or int(payload.get("ver") or 0) != _ver:
            return None
    except Exception:
        return None
    return {
        "user_id": payload.get("sub", ""),
        "username": payload.get("username", ""),
        "role": payload.get("role", "analyst"),
        "roles": [payload.get("role", "analyst")],
    }


# 【函数】管理员鉴权依赖：只有 roles 含 "admin" 的用户才能通过。
# 入参：user —— 由 get_current_user 先解析出的当前用户（依赖链自动注入，先认证后鉴权）
# 返回：dict —— 鉴权通过后原样返回 user，路由函数继续使用
# 业务定位：挂在管理后台路由上做"门中门"——第 1 道门认证"你是谁"，
#           第 2 道门鉴权"你配不配"；认证失败 401，权限不足 403。
def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """管理员权限依赖：普通用户访问返回 403。"""
    # roles 里没有 admin → 403（已登录但权限不足；401 是"没登录"，语义必须区分）
    roles = user.get("roles") or []
    if "admin" not in roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    # 通过鉴权：原样返回用户信息，路由函数可直接使用
    return user
