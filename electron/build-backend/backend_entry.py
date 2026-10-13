# electron/build-backend/backend_entry.py
# -*- coding: utf-8 -*-
"""桌面版后端入口：从 env 读端口/数据路径，启动 FastAPI 应用。

打包后由 Electron 主进程 spawn 调用；除 uvicorn 标准参数外，
host/port 全部来自环境变量（AUTH_ENABLED / HOST / API_PORT / DAA_SQLITE_PATH）。
"""
import os
import sys
from pathlib import Path


def _项目根() -> Path:
    """打包后项目根 = exe 同级的 _internal 目录的上级（onedir 布局）。"""
    if getattr(sys, "frozen", False):
        # dist-backend/daa-backend.exe → 项目根即 exe 所在目录
        return Path(sys.executable).resolve().parent
    # 开发模式：electron/build-backend/backend_entry.py → 项目根
    return Path(__file__).resolve().parent.parent.parent


def main() -> None:
    # 让 api/config/repositories/后端_核心 可导入
    根 = _项目根()
    if str(根) not in sys.path:
        sys.path.insert(0, str(根))

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT") or os.getenv("PORT") or "8000")

    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=host,
        port=port,
        log_level=os.getenv("LOG_LEVEL", "warning"),
        # SQLite 单文件库：写锁是进程内 threading.Lock，必须单 worker
        workers=1,
    )


if __name__ == "__main__":
    main()
