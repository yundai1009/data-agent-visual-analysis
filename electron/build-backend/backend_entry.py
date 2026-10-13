# -*- coding: utf-8 -*-
# 桌面版后端 exe 的启动入口：把 PyInstaller 产物拉起 uvicorn，跑真正的 FastAPI 应用（api.main:app）。
# 做了什么：main() 先把「项目根」插到 sys.path 最前（让 api/、config/、后端_核心/ 可导入），
#   再从环境变量读 HOST、API_PORT（回落 PORT、再回落 8000）、LOG_LEVEL，最后 uvicorn.run(..., workers=1)。
# 为什么 workers 固定为 1：SQLite 是单文件库，写锁是进程内的 threading.Lock，多 worker 各持一把锁会直接写坏或锁死；
#   桌面版是单人单机场景，单进程 uvicorn 的异步并发足够，为了吞吐换多 worker 在本地是纯亏。
# 为什么用字符串 "api.main:app" 而不是把 app 对象传进来：只有字符串形式才会让 uvicorn 负责导入与信号处理，
#   Electron 侧 kill 进程时才能走正常关闭流程；传对象等于自己接管生命周期，退出时容易留下半截写。
# 为什么 host / 端口一律来自 env：Electron 主进程的 electron/核心/后端配置.js 是唯一配置来源，
#   用户改端口、改数据库都体现为 spawn 时的环境变量，所以这个入口零配置、完全不读 settings.json。
# 坑：frozen 分支取 Path(sys.executable).parent —— 依赖 onedir 布局（exe 与 _internal 同级，见 daa-backend.spec）；
#   改成 onefile 打包时项目根会算错，import api.main 直接失败。
# 坑：开发模式下项目根 = build-backend 的上上级（仓库根），因此必须从仓库根启动这个脚本，换个 cwd 会导入不到。
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
