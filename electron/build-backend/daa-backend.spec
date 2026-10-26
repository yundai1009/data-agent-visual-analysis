# electron/build-backend/daa-backend.spec
# -*- coding: utf-8 -*-
"""PyInstaller 配置：把 FastAPI 后端打成 onedir 可执行（daa-backend.exe + _internal/）。

隐式导入清单（本项目动态导入的依赖）：
- uvicorn/protocols 与 loops 子模块是动态 import，必须显式收
- chromadb 有大量延迟导入子模块
- pandas/pyarrow 打包体积大但必需（parquet 读写）
- python-multipart（FastAPI 表单上传）
"""
from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_submodules, collect_all, collect_data_files

# 关键：collect_submodules 在 spec 顶部执行，用的是「运行 PyInstaller 的进程」的
# sys.path，而不是 Analysis 的 pathex——若仓库根不在 sys.path，collect_submodules('api')
# 静默返回空列表，项目代码整体漏打包（实测 exe 启动报 No module named 'api'）。
import sys as _sys
仓库根 = Path.cwd().parent  # spec 在 electron/ 下执行 → parent = 仓库根
if str(仓库根) not in _sys.path:
    _sys.path.insert(0, str(仓库根))

# pkg_resources 运行时动态探测依赖（appdirs/jaraco/backports 等），逐个 hiddenimports
# 不可靠——pkg_resources 的 _vendor 虚拟供应商树必须整树收集（setuptools 83 起
# pkg_resources 独立包化，其 extern 机制在 PyInstaller 冻结环境会探测顶层 jaraco.*
# 失败，PYI-14640；collect_all 把 _vendor.* 全收即可让回退链生效）
_pkgres_datas, _pkgres_binaries, _pkgres_hidden = collect_all("pkg_resources")
_setuptools_datas, _setuptools_binaries, _setuptools_hidden = collect_all("setuptools")
# numpy 2.x：内置 hook-numpy 收集不完整（实测产物 _core 只收 2/7 个 .pyd、
# _exceptions.py 纯 Python 模块漏进 PYZ → exe 启动报 No module named 'numpy._core._exceptions'）。
# collect_all 三件套强制收全（全部 .py 模块 + .pyd 扩展 + 数据文件）
_numpy_datas, _numpy_binaries, _numpy_hidden = collect_all("numpy")
# rfc3987_syntax：jsonschema 校验 URI 时经 lark 加载 grammar 数据文件
# （chromadb → jsonschema → rfc3987_syntax），漏收则 FileNotFoundError syntax_rfc3987.lark
_rfc3987_datas = collect_data_files("rfc3987_syntax")

项目根 = Path.cwd()  # 从 electron/ 目录执行：npm run build:backend
if 项目根.name != "electron" or not (项目根 / "build-backend" / "daa-backend.spec").exists():
    raise SystemExit("必须从 electron/ 目录运行 PyInstaller（npm run build:backend），否则仓库根推断错误")
# onedir 顶层目录名由 COLLECT 的 name 决定；把 distpath 指到 electron/ 本级，
# 让 COLLECT(name="dist-backend") 产出 electron/dist-backend/daa-backend.exe +
# electron/dist-backend/_internal/（与 Task1 主进程 spawn 路径 / Task5 extraResources 对齐）
CONF['distpath'] = str(项目根)

# 前端产物（阶段七十七 D4 收尾）：让 dist-backend 自身也自带一份前端，
# 不必只依赖 electron-builder 的 extraResources 第二次拷贝。
# 刻意做成「有就收、没有就跳过」——缺 frontend/dist 时 spec 不该构建失败
# （那种情况下 extraResources 仍会拷；两头都缺才是真问题）。
# 落 _internal/frontend/dist/，与主进程 spawnBackend 的兜底路径
# resources/backend/_internal/frontend/dist 对齐。
_前端产物 = []
_前端dist = 项目根.parent / "frontend" / "dist"
if (_前端dist / "index.html").is_file():
    _前端产物.append((str(_前端dist / "index.html"), str(Path("frontend") / "dist")))
    if (_前端dist / "assets").is_dir():
        _前端产物.append((str(_前端dist / "assets"), str(Path("frontend") / "dist" / "assets")))

# 项目自身代码：uvicorn 通过字符串 "api.main:app" 动态加载，PyInstaller 无法静态追踪，
# 必须显式收集（api/config/repositories/services/后端_核心 全部子模块）
项目包 = []
for _pkg in ("api", "config", "repositories", "services", "后端_核心"):
    项目包 += collect_submodules(_pkg)

a = Analysis(
    [str(项目根 / "build-backend" / "backend_entry.py")],
    pathex=[str(项目根.parent)],  # 项目根（含 api/config/repositories/后端_核心）
    binaries=_pkgres_binaries + _setuptools_binaries + _numpy_binaries + [],
    datas=_pkgres_datas + _setuptools_datas + _numpy_datas + _rfc3987_datas + [
        (str(项目根.parent / "config" / "providers.toml"), "config"),
        # 内置示例数据集（阶段 59）：「导入示例数据」按钮依赖它，漏收则安装包内该接口 404。
        # 落 _internal/data/examples/，运行时由 api/routes/examples.py 复制到可写数据目录。
        (str(项目根.parent / "data" / "examples" / "sales_2024.csv"),
         str(Path("data") / "examples")),
    ] + _前端产物,

    # 前端产物（阶段七十七）：D4 收尾——让 dist-backend 自身也自带一份前端，
    # 不再只依赖 electron-builder 的 extraResources 第二次拷贝。
    # 刻意做成「有就收、没有就跳过」：缺 frontend/dist 时 spec 不该直接构建失败
    # （那时 electron-builder 的 extraResources 仍会拷；两头都缺才是真问题）。
    # 落 _internal/frontend/dist/{index.html, assets/}，与主进程 spawnBackend 的
    # 兜底路径 resources/backend/_internal/frontend/dist 对齐。

    hiddenimports=[
        "uvicorn",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "multipart",
        "pydantic",
        "pydantic_core",
        "chromadb",
        "chromadb.api",
        "chromadb.api.client",
        "chromadb.api.models.Collection",
        "chromadb.config",
        "pyarrow",
        "pyarrow.parquet",
        "openpyxl",
        "xlrd",
        "reportlab",
        "requests",
        "dotenv",
        "jieba",
        "fastapi",
        "starlette",
        "anyio",
        "httpcore",
        "httpx",
        # PyInstaller 冒烟实测补漏：pkg_resources -> jaraco.text -> jaraco.context
        # 依赖 backports（动态导入，静态追踪不到，漏收则 exe 启动即崩 PYI-14640）
        "backports",
        "backports.tarfile",
        "appdirs",
        "jaraco.context",
        "jaraco.text",
        "jaraco.functools",
    ] + 项目包 + _pkgres_hidden + _setuptools_hidden + _numpy_hidden,
    excludes=["tkinter", "PyQt5", "PySide2", "matplotlib", "scipy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="daa-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon=str(项目根.parent / "logo.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="dist-backend",
)

# onedir 布局：dist-backend/daa-backend.exe + dist-backend/_internal/
