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
            msg = errors[0].get("msg", "参数校验失败")
            message = f"参数错误：{loc} {msg}"
        else:
            message = "参数校验失败"
        return JSONResponse(
            status_code=422,
            content=_error_body(request, "VALIDATION_ERROR", message),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        # 兜底 500：不把异常细节暴露给用户，只记录到日志
        logger.error("Unhandled exception on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content=_error_body(request, "INTERNAL_ERROR", "服务内部错误，请稍后重试"),
        )
