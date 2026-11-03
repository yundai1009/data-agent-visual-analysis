"""统一错误响应：所有异常统一返回 {code, message, request_id} 结构。

覆盖三类异常：
- HTTPException（业务主动抛出的 4xx/5xx）
- RequestValidationError（Pydantic 参数校验失败）
- 未捕获 Exception（兜底 500）
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# 阶段八十九：Pydantic 校验错误的中文映射。此前超长/过短等校验失败会直接把英文
# 原文（如 "String should have at most 128 characters"）透给用户；这里只翻译常见
# 校验类型，未知类型回落原文，绝不吞掉信息。
_字段中文 = {
    "password": "密码",
    "username": "用户名",
    "email": "邮箱",
    "code": "验证码",
    "q": "搜索词",
    "agent_mode": "智能体模式",
    "limit": "分页大小",
    "offset": "分页偏移",
}


def _中文校验错误(err: dict) -> str:
    typ = err.get("type", "")
    ctx = err.get("ctx") or {}
    field = ".".join(str(x) for x in err.get("loc", []) if x not in ("body", "query"))
    名 = _字段中文.get(field, field or "参数")
    if typ == "string_too_long":
        return f"{名}最多 {ctx.get('max_length', '?')} 个字符"
    if typ == "string_too_short":
        return f"{名}至少 {ctx.get('min_length', '?')} 个字符"
    if typ == "string_pattern_mismatch":
        return f"{名}格式不正确"
    if typ == "missing":
        return f"缺少{名}"
    if typ in ("too_long", "list_too_long"):
        return f"{名}最多 {ctx.get('max_length', '?')} 项"
    if typ in ("too_short", "list_too_short"):
        return f"{名}至少 {ctx.get('min_length', '?')} 项"
    if typ == "greater_than":
        return f"{名}必须大于 {ctx.get('gt', '?')}"
    if typ == "greater_than_equal":
        return f"{名}不能小于 {ctx.get('ge', '?')}"
    if typ == "less_than":
        return f"{名}必须小于 {ctx.get('lt', '?')}"
    if typ == "less_than_equal":
        return f"{名}不能大于 {ctx.get('le', '?')}"
    if typ in ("literal_error", "enum"):
        return f"{名}取值不受支持"
    # 未知类型：回落 Pydantic 原文，保证不丢信息
    return err.get("msg", "参数校验失败")


def _request_id(request: Request) -> str:
    """从 request.state 取 request_id（由中间件写入），取不到则返回空。"""
    return getattr(request.state, "request_id", "")


def _error_body(request: Request, code: str, message: str) -> Dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "request_id": _request_id(request),
    }


def register_error_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册统一错误处理器。"""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 尽量保留业务方传入的 detail；detail 为字符串时直接使用
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code", f"HTTP_{exc.status_code}")
            message = detail.get("message", str(exc.status_code))
        else:
            code = f"HTTP_{exc.status_code}"
            message = str(detail)
        logger.info("HTTP %s %s %s (request_id=%s)", exc.status_code, request.method,
                    request.url.path, _request_id(request))
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, code, message),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # 提取第一个错误位置，生成用户可读的信息
        errors = exc.errors()
        if errors:
            loc = ".".join(str(x) for x in errors[0].get("loc", []) if x != "body")
            校验说明 = _中文校验错误(errors[0])
            message = f"参数错误：{校验说明}"
        else:
            message = "参数校验失败"
        logger.info("VALIDATION_ERROR %s %s (request_id=%s): %s", request.method,
                    request.url.path, _request_id(request), message)
        return JSONResponse(
            status_code=422,
            content=_error_body(request, "VALIDATION_ERROR", message),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # 阶段九十 R7b：数据库初始化失败时，任何落到这里的异常都极可能是"数据库不可用"。
        # 旧行为：返回 500「服务内部错误，请稍后重试」——用户不知道是库没起，
        #   只看到"能打开页面但所有操作都失败"。此时改成 503 + 启动阶段留下的处置建议，
        #   把"不静默"落到用户实际操作的每一步上。
        from api import main as 主模块
        启动故障 = getattr(主模块, "_启动故障", None)
        if 启动故障:
            logger.error("DB-initialization failed; returning 503 on %s %s (request_id=%s): %s",
                         request.method, request.url.path, _request_id(request), exc, exc_info=True)
            return JSONResponse(
                status_code=503,
                content=_error_body(request, "DB_NOT_READY", 启动故障),
            )
        # 兜底 500：不把异常细节暴露给用户，只记录到日志（含 request_id 便于按请求排查）
        logger.error("Unhandled exception on %s %s (request_id=%s): %s",
                     request.method, request.url.path, _request_id(request), exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=_error_body(request, "INTERNAL_ERROR", "服务内部错误，请稍后重试"),
        )
