"""request_id 中间件：为每个请求生成唯一标识，贯穿日志与响应。

行为：
- 读取请求头 X-Request-ID；有则沿用（便于外部追踪），无则生成新的
- 写入 response header X-Request-ID
- 写入 request.state.request_id，供错误处理器和日志使用
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# P0 加固：全局请求体上限（与上传 50MB 限制一致；超限直接 413，防超大 body 撑爆内存 DoS）
MAX_BODY_BYTES = 50 * 1024 * 1024


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """拒绝 Content-Length 超上限的请求（chunked 请求不在此列，由各端点自限）。"""

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl:
            try:
                if int(cl) > MAX_BODY_BYTES:
                    from starlette.responses import JSONResponse
                    return JSONResponse(
                        status_code=413,
                        content={"code": "PAYLOAD_TOO_LARGE", "message": "请求体过大（上限 50MB）", "request_id": ""},
                    )
            except ValueError:
                pass
        return await call_next(request)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求注入 request_id。"""

    async def dispatch(self, request: Request, call_next):
        # 优先沿用外部传入的 request_id；无则生成。限制长度与字符集（字母数字与-_），防日志注入
        request_id = (request.headers.get("X-Request-ID") or "").strip()
        if not request_id or len(request_id) > 64 or not all(c.isalnum() or c in "-_" for c in request_id):
            request_id = f"req_{uuid.uuid4().hex[:12]}"
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
