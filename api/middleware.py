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
from starlette.responses import JSONResponse

# Fix 4：两层体量职责分离——中间件按「整个 multipart 请求体」Content-Length
# 拦截（含 boundary 头开销），上限给 1MB 余量（50MB+1MB）：总量防 DoS；
# 单文件 50MB 业务限制由接口层 _MAX_UPLOAD_BYTES 执行（恰好 50MB 文件能穿透
# 到这里，由接口层 413/解析处理；此前中间件 50MB 按整包拦截导致接口层分支死代码）
MAX_BODY_BYTES = 51 * 1024 * 1024
# 中间件 413 文案对齐实际常量（防 DoS 总量 51MB；单文件 50MB 限制由接口层文案给出）


class RequestBodyLimitMiddleware(BaseHTTPMiddleware):
    """拒绝请求体超上限的请求。

    - Content-Length 请求：直接校验头值，秒级拦截（最轻量路径）
    - chunked / 无 Content-Length 请求：包装 request._receive 做流式计数，
      累计 body 字节数超过上限时中断消费，防止恶意超大 body 拖垮内存/磁盘。
    """

    async def dispatch(self, request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl:
            try:
                if int(cl) > MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"code": "PAYLOAD_TOO_LARGE", "message": "请求体过大（上限 51MB，防 DoS 总量）", "request_id": ""},
                    )
            except ValueError:
                pass
        else:
            # P0 修复（Bug24）：chunked 请求绕过 Content-Length 检查——通过包装
            # request._receive 逐块累计 body 字节数，超限后抛 ValueError 由外层
            # 捕获返回 413，阻止 Starlette 将整个超大 body 缓冲到临时文件。
            _orig_receive = request._receive
            _received = 0

            async def _counted_receive():
                nonlocal _received
                msg = await _orig_receive()
                if msg["type"] == "http.request":
                    _received += len(msg.get("body", b""))
                    if _received > MAX_BODY_BYTES:
                        raise ValueError("body exceeds 51MB limit (chunked)")
                return msg

            request._receive = _counted_receive

        try:
            return await call_next(request)
        except ValueError as e:
            if "51MB" in str(e) or "chunked" in str(e):
                return JSONResponse(
                    status_code=413,
                    content={"code": "PAYLOAD_TOO_LARGE", "message": "请求体过大（上限 51MB，防 DoS 总量）", "request_id": ""},
                )
            raise


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """阶段九十 R12：给每个响应补安全响应头（防 clickjacking / MIME 嗅探 / 敏感 API 泄 referrer）。

    技术评审团：审计只提了 CSP 与 clickjacking「待补」。这里不重造完整 CSP——
    完整策略容易把 ECharts 内联脚本、内联样式或 data: 图片拦掉，反而把正常页面
    搞坏；只补**零功能风险**的三条：frame-ancestors（防被第三方 iframe 套壳点击）、
    nosniff（防 MIME 嗅探）、Referrer-Policy（防跳外链时把内部路径带出去）。
    注：仅设 frame-ancestors 的 CSP 头是合法且只约束嵌套，不影响页内任何资源。
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        # 与已有 CSP 头共存：若别处已设 CSP，只补 frame-ancestors，避免整段覆盖。
        existing_csp = response.headers.get("Content-Security-Policy", "")
        if "frame-ancestors" not in existing_csp:
            response.headers["Content-Security-Policy"] = f"{existing_csp}; frame-ancestors 'self'".strip("; ")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response


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
