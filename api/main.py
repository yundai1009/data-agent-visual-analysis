from __future__ import annotations
import os
import sys

# 【必须放在所有import最开头】优先注入项目根目录
# __file__ = api/main.py，dirname一次=api文件夹，再dirname=项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.contracts import HealthResponse
from api.error_handlers import register_error_handlers
from api.middleware import RequestIDMiddleware
from api.routes import datasets, reports, clean, examples, auth
from config.settings import EnvConfig


@asynccontextmanager
async def lifespan(app: FastAPI):
    # TODO: 启动时加载配置、初始化 DB/Redis/Chroma 连接
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
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=EnvConfig.HOST,
        port=EnvConfig.PORT,
    )
