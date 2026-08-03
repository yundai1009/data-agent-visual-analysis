from __future__ import annotations
import os
import sys

# 【必须放在所有import最开头】优先注入项目根目录
# __file__ = api/main.py，dirname一次=api文件夹，再dirname=项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from contextlib import asynccontextmanager
from datetime import datetime
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from api.contracts import HealthResponse
from api.error_handlers import register_error_handlers
from api.middleware import RequestIDMiddleware
from api.routes import datasets, reports, clean, examples, auth, admin
from config.settings import EnvConfig

logger = logging.getLogger(__name__)

# 前端静态产物目录：启动器通过 FRONTEND_DIST 环境变量选择
# - 正式构建 frontend/dist（AUTH_REQUIRED=true）
# - 演示构建 frontend/dist-demo（AUTH_REQUIRED=false + 自动加载示例数据）
FRONTEND_DIST = os.getenv("FRONTEND_DIST", str(Path(project_root) / "frontend" / "dist"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 阶段十三：启动时幂等创建种子管理员（密码来自 EnvConfig，生产务必覆盖默认值）
    try:
        from repositories import user_repo
        from services import auth_service
        user_repo.确保管理员存在(
            EnvConfig.SEED_ADMIN_USERNAME,
            auth_service.hash_password(EnvConfig.SEED_ADMIN_PASSWORD),
        )
        if EnvConfig.SEED_ADMIN_PASSWORD == "admin123":
            logger.warning(
                "种子管理员 %s 正在使用默认密码 admin123，生产环境请通过 "
                "SEED_ADMIN_PASSWORD 环境变量修改！", EnvConfig.SEED_ADMIN_USERNAME)
        if EnvConfig.JWT_SECRET_KEY in ("change-me-in-production", ""):
            logger.error(
                "JWT_SECRET_KEY 为默认值，token 可被伪造！生产环境必须通过 "
                "JWT_SECRET_KEY 环境变量配置强随机密钥！")
    except Exception as exc:
        logger.error("创建种子管理员失败：%s", exc)
    yield
    # TODO: 关闭时清理连接


app = FastAPI(
    title="自助式数据分析 Agent 平台",
    description="基于 FastAPI 的文件上传数据分析与可视化报表平台",
    version=EnvConfig.API_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# request_id 中间件：放在最外层，保证所有请求都有 request_id
app.add_middleware(RequestIDMiddleware)

# 统一错误响应：注册异常处理器
register_error_handlers(app)


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=EnvConfig.API_VERSION,
        timestamp=datetime.now(),
    )

app.include_router(datasets.router)
app.include_router(reports.router)
app.include_router(clean.router)
app.include_router(examples.router)
app.include_router(auth.router)
app.include_router(admin.router)


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
async def spa_fallback(full_path: str, request: Request):
    """托管前端构建产物 + SPA 路由回退。

    放在所有 API 路由之后注册，因此 /health、/auth、/datasets、/reports 等
    具体路由优先匹配；其余 GET 路径（/data、/analysis、/report/xxx 等）返回
    前端 index.html，由 React Router 接管。非 GET 方法且未命中任何路由时
    返回 404（与无 catch-all 时的行为一致）。这样只需要一个后端进程即可
    完整运行，零基础用户无需安装 Node。
    """
    if request.method != "GET":
        raise HTTPException(status_code=404, detail="Not Found")
    dist = Path(FRONTEND_DIST).resolve()
    if not dist.is_dir():
        raise HTTPException(status_code=404, detail="前端构建产物不存在，请先运行构建")
    if full_path:
        target = (dist / full_path).resolve()
        # 路径穿越防护：只允许读取 dist 目录内的文件
        if target.is_file() and str(target).startswith(str(dist)):
            # hash 文件名内容指纹：可安全长缓存（浏览器内容变了 hash 自动变）
            if full_path.startswith("assets/") or "/assets/" in "/" + full_path:
                return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})
            return FileResponse(target)
    index = dist / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="前端构建产物不存在，请先运行构建")
    # HTML 永远不启发式缓存：每次请求都回源校验，保证拿到最新构建（引用新 hash 资源）
    return HTMLResponse(
        index.read_text(encoding="utf-8"),
        media_type="text/html",
        headers={"Cache-Control": "no-cache"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=EnvConfig.HOST,
        port=EnvConfig.PORT,
    )
