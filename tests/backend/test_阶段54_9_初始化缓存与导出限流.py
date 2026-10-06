# -*- coding: utf-8 -*-
"""阶段 54-9 · Fix 已知限制清零（第一块 E1+E2）：

E1（压测 P1-4）· 认证 DDL 开销缓存：`初始化用户表`/`初始化报表表` 由
「每次调用都跑完整 DDL 检查」改为「进程级一次性 + 按 DB 路径分键缓存」。
- 单测：同进程第二次调用不再执行 DDL（patch 内部函数断言只调 1 次）；
- 不同 DAA_SQLITE_PATH 各自初始化 1 次（隔离测试同进程建库必须各自首次初始化）；
- 失败回退：异常不缓存，下次调用重试（启动时表故障不被永久掩盖）。

E2（压测 P1-5）· 导出并发上限：export/export-all 增设独立信号量，
占满后立即 503（业务文案「系统繁忙，请稍后重试」），释放后可恢复。
"""

from __future__ import annotations

import os
import sys
import threading

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ---- E1：初始化 DDL 缓存（仓库层，隔离库 tmp_path） -----------------------


def test_初始化用户表_同进程第二次跳过DDL(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """E1 红→绿：patch 内部全量函数，同路径下第二次调用不再执行 DDL。"""
    from repositories import user_repo

    调用次数: list = []
    _真实 = user_repo._初始化用户表全量

    def _计数():
        调用次数.append(1)
        _真实()

    monkeypatch.setattr(user_repo, "_初始化用户表全量", _计数)
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "a.db"))
    # 对齐生产流：lifespan 先 初始化数据库() 建 users 表，首次 初始化用户表 只做迁移
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    初始化数据库()
    user_repo.初始化用户表()
    user_repo.初始化用户表()
    user_repo.初始化用户表()
    assert len(调用次数) == 1, "同进程同路径第二次调用必须跳过 DDL（否则每请求 ~10ms 地板不消除）"


def test_初始化用户表_不同DB路径各自初始化(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """E1 最大坑：缓存键必须绑 DB 路径——隔离测试每个 tmp_path 各自首次初始化。"""
    from repositories import user_repo

    调用次数: list = []
    _真实 = user_repo._初始化用户表全量

    def _计数():
        调用次数.append(1)
        _真实()

    monkeypatch.setattr(user_repo, "_初始化用户表全量", _计数)
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "a.db"))
    初始化数据库()
    user_repo.初始化用户表()
    user_repo.初始化用户表()
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "b.db"))
    初始化数据库()
    user_repo.初始化用户表()
    assert len(调用次数) == 2, "不同 DB 路径必须各自首次初始化（同进程隔离测试建新库）"


def test_初始化用户表_失败回退下次重试(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """E1 失败回退：首次异常不缓存，第二次调用重试成功。"""
    from repositories import user_repo

    调用次数: list = []
    _真实 = user_repo._初始化用户表全量

    def _先失败后成功():
        调用次数.append(len(调用次数) + 1)  # 第 1 次=1、第 2 次=2（记录调用次序）
        if 调用次数[-1] == 1:
            raise RuntimeError("模拟首次建表故障")
        _真实()

    monkeypatch.setattr(user_repo, "_初始化用户表全量", _先失败后成功)
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "c.db"))
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    初始化数据库()
    with pytest.raises(RuntimeError):
        user_repo.初始化用户表()  # 首次失败：异常向上抛、不缓存
    user_repo.初始化用户表()  # 第二次重试成功
    user_repo.初始化用户表()  # 第三次跳过
    assert 调用次数 == [1, 2], "失败不缓存、下次重试；成功后不再执行"


def test_初始化报表表_同进程第二次跳过DDL(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """E1 报表侧同理：patch 内部全量函数，同路径下第二次调用不再执行 DDL。"""
    from repositories import report_repo

    调用次数: list = []
    _真实 = report_repo._初始化报表表全量

    def _计数():
        调用次数.append(1)
        _真实()

    monkeypatch.setattr(report_repo, "_初始化报表表全量", _计数)
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "r.db"))
    report_repo.初始化报表表()
    report_repo.初始化报表表()
    assert len(调用次数) == 1, "报表表初始化同路径第二次必须跳过 DDL"


def test_初始化报表表_不同DB路径各自初始化(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """E1 报表侧：不同 DB 路径各自初始化。"""
    from repositories import report_repo

    调用次数: list = []
    _真实 = report_repo._初始化报表表全量

    def _计数():
        调用次数.append(1)
        _真实()

    monkeypatch.setattr(report_repo, "_初始化报表表全量", _计数)
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "r1.db"))
    report_repo.初始化报表表()
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "r2.db"))
    report_repo.初始化报表表()
    assert len(调用次数) == 2, "报表表不同 DB 路径各自初始化"


# ---- E2：导出并发上限（API 级，隔离库） ------------------------------------

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix549_e2_export")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True

    from services import email_service

    def _fake_send(email: str, code: str) -> bool:
        _SENT_CODES[email] = code
        return True

    _orig_send = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake_send
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            yield c
    finally:
        email_service.发送验证码邮件 = _orig_send


def _register(client, username):
    email = f"{username}@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _make_report(client, token) -> str:
    """上传 CSV → 生成报表（规则兜底，无 LLM key 也可），返回 report_id。"""
    r = client.post(
        "/datasets/upload",
        files={"file": ("t.csv", "地区,销售额\n华东,100\n华南,200\n华东,300\n", "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    ds_id = r.json()["上传成功"][0]["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": ds_id,
        "分析需求": "按地区统计销售额Top 1",
        "图表类型": "自动推荐",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["报表ID"]


def test_导出信号量_占满后503_释放可恢复(client):
    """E2 红→绿：export 独立信号量——占满立即 503（业务文案），释放后可恢复 200。"""
    from api.routes import reports as _routes
    token = _register(client, "exp_user1")
    rid = _make_report(client, token)
    headers = {"Authorization": f"Bearer {token}"}

    _原信号量 = _routes._EXPORT_SEMAPHORE
    _routes._EXPORT_SEMAPHORE = threading.BoundedSemaphore(1)
    try:
        assert _routes._EXPORT_SEMAPHORE.acquire(blocking=False), "应能占满 1 个导出名额"
        r = client.get(f"/reports/{rid}/export", params={"format": "csv"}, headers=headers)
        assert r.status_code == 503, r.text
        assert "系统繁忙" in r.json()["message"], "503 文案对齐 generate：系统繁忙，请稍后重试"
        _routes._EXPORT_SEMAPHORE.release()
        r = client.get(f"/reports/{rid}/export", params={"format": "csv"}, headers=headers)
        assert r.status_code == 200, r.text
    finally:
        _routes._EXPORT_SEMAPHORE = _原信号量


def test_批量导出_占满后503(client):
    """E2：export-all 同一信号量——占满立即 503。"""
    from api.routes import reports as _routes
    token = _register(client, "exp_user2")
    _make_report(client, token)
    headers = {"Authorization": f"Bearer {token}"}

    _原信号量 = _routes._EXPORT_SEMAPHORE
    _routes._EXPORT_SEMAPHORE = threading.BoundedSemaphore(1)
    try:
        assert _routes._EXPORT_SEMAPHORE.acquire(blocking=False)
        r = client.get("/reports/export-all", params={"format": "csv"}, headers=headers)
        assert r.status_code == 503, r.text
        assert "系统繁忙" in r.json()["message"], r.text
        _routes._EXPORT_SEMAPHORE.release()
        r = client.get("/reports/export-all", params={"format": "csv"}, headers=headers)
        assert r.status_code == 200, r.text
    finally:
        _routes._EXPORT_SEMAPHORE = _原信号量
