# -*- coding: utf-8 -*-
"""阶段九十 · 启动失败不静默（R7b）+ 安全响应头（R12）专项测试。

R7b 背景（技术/产品评审团共同指出）：api/main.py 的 初始化数据库 失败原先只
logger.error 一条就继续启动 —— 用户看到的是「页面能打开、每个操作都报错」，
完全不知道是数据库没起。本文件锁住：① 故障被记录并可经 /healthz 读出；
② 未捕获异常在故障态下返回 503 + 可读处置建议（而非笼统 500）。

R12 背景：审计提「无 X-Frame-Options / CSP，存在 clickjacking 风险」。
"""
import tempfile

import pytest
from fastapi.testclient import TestClient

from api import main


@pytest.fixture()
def 客户端(tmp_path, monkeypatch):
    """建一个临时数据目录 + 独立记忆库目录的 TestClient（不污染仓库 data/）。"""
    monkeypatch.setenv("DAA_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setattr(main, "_单实例锁句柄", None)
    monkeypatch.setattr(main, "_启动故障", None)
    with TestClient(main.app) as c:
        yield c
    if main._单实例锁句柄 is not None:
        try:
            main._单实例锁句柄.close()
        except OSError:
            pass
        main._单实例锁句柄 = None


# ═══ R12：安全响应头 ═══

def test_响应带防clickjacking与嗅探头(客户端):
    r = 客户端.get("/healthz")
    assert r.status_code == 200
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert "frame-ancestors 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["Referrer-Policy"] == "same-origin"


def test_安全头覆盖业务错误响应(客户端):
    """404 这类错误响应同样要带安全头——否则被套壳的正是「报错页」。"""
    r = 客户端.get("/不存在的接口路径")
    assert r.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert r.headers.get("X-Content-Type-Options") == "nosniff"


def test_已存在CSP时只追加frame_ancestors(monkeypatch):
    """别处已设 CSP 时不能整段覆盖，否则会把既有策略（如 script-src）抹掉。"""
    from api.middleware import SecurityHeadersMiddleware
    assert "frame-ancestors" in str(SecurityHeadersMiddleware.__doc__) or True
    # 直接验证拼接逻辑：给一个已有 CSP 的响应
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    应用 = FastAPI()

    @应用.get("/x")
    def _x():
        r = JSONResponse({"ok": True})
        r.headers["Content-Security-Policy"] = "default-src 'self'"
        return r

    应用.add_middleware(SecurityHeadersMiddleware)
    with TestClient(应用) as c:
        csp = c.get("/x").headers["Content-Security-Policy"]
        assert csp.startswith("default-src 'self'"), "既有策略必须保留"
        assert "frame-ancestors 'self'" in csp


# ═══ R7b：启动故障不静默 ═══

def test_健康检查暴露启动故障字段(客户端):
    """正常启动时为 None；字段本身必须存在，运维/前端才有稳定契约可读。"""
    assert "启动故障" in 客户端.get("/healthz").json()
    assert 客户端.get("/healthz").json()["启动故障"] is None


def test_启动故障态_未捕获异常返回503与处置建议(monkeypatch):
    """故障态下 500 兜底改 503 + 处置建议：用户能看懂「是数据库的问题」。

    用独立 mini-app 而非往共享 app 动态加路由：共享 app 的 SPA 兜底路由
    /{full_path:path} 注册在前，动态加的 /__test_boom__ 永远轮不到，测试会失真。
    """
    from fastapi import FastAPI
    from api.error_handlers import register_error_handlers

    应用 = FastAPI()
    register_error_handlers(应用)

    @应用.get("/boom")
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(main, "_启动故障", "数据库初始化失败（后端=mysql）：无法连接\n处置建议：切换到内置 SQLite")
    with TestClient(应用, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 503
    body = r.json()
    assert body["code"] == "DB_NOT_READY"
    assert "数据库初始化失败" in body["message"]
    assert "内置 SQLite" in body["message"], "必须给出可执行的处置建议"


def test_无启动故障时仍是500(monkeypatch):
    """没有故障记录时，未知异常仍是 500「服务内部错误」，不误报成数据库问题。

    显式把 _启动故障 置回 None：模块全局会被前序用例（如 503 用例 / lifespan 故障用例）
    置为非空，不重置会让本用例在全量跑时误走 503 分支（单跑通过、全量红）。
    """
    from fastapi import FastAPI
    from api.error_handlers import register_error_handlers

    monkeypatch.setattr(main, "_启动故障", None)

    应用 = FastAPI()
    register_error_handlers(应用)

    @应用.get("/boom")
    def _boom():
        raise RuntimeError("boom")

    with TestClient(应用, raise_server_exceptions=False) as c:
        r = c.get("/boom")
    assert r.status_code == 500
    assert r.json()["code"] == "INTERNAL_ERROR"


def test_初始化数据库失败会写入启动故障(tmp_path, monkeypatch):
    """真正跑一次 lifespan：把 初始化数据库 打成必崩，断言故障被记录。

    注意不断言 /healthz.db_ok：healthz 的 db_ok 是它自己再打一次 SELECT 1 的
    探活，sqlite 会在探活时自动建库从而返回 True——与「初始化失败」是两条独立
    信号。真正的「不静默」载体是新增的 启动故障 字段，这里只锁它。
    """
    from 后端_核心.存储 import 连接
    monkeypatch.setenv("DAA_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setattr(main, "_单实例锁句柄", None)
    monkeypatch.setattr(main, "_启动故障", None)

    def 必崩():
        raise RuntimeError("无法连接 MySQL")

    monkeypatch.setattr(连接, "初始化数据库", 必崩)
    with TestClient(main.app) as c:
        r = c.get("/healthz")
    assert r.json()["启动故障"] is not None
    assert "数据库初始化失败" in r.json()["启动故障"]
