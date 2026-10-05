# -*- coding: utf-8 -*-
"""阶段 54 · /healthz 探活：后端类型 + 数据库连通性。"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from fastapi.testclient import TestClient

from 后端_核心.存储 import backend


@pytest.fixture
def client():
    from api.main import app
    with TestClient(app) as c:
        yield c


def test_healthz_返回后端类型与连通(monkeypatch, client):
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "sqlite", raising=False)
    r = client.get("/healthz")
    assert r.status_code == 200
    j = r.json()
    assert j["db_backend"] == "sqlite"
    assert j["db_ok"] is True
    assert j["status"] == "ok"


def test_healthz_mysql模式_报告mysql后端(monkeypatch, client):
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["db_backend"] == "mysql"
    # db_ok 只要求是 bool（本机 MySQL 可能连不上/连得上，不依赖外部状态）
    assert isinstance(r.json()["db_ok"], bool)


def test_healthz_库连不上时degraded(monkeypatch, client):
    """把 sqlite 连接指向不可用路径 → db_ok False、status degraded。"""
    import sqlite3
    from 后端_核心.存储 import sqlite_backend

    坏路径 = os.path.join(os.environ.get("TEMP", "/tmp"), "definitely_missing_dir", "x.db")

    def 坏连接():
        # 目录不存在 → sqlite3.connect 抛 OperationalError
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite_backend, "get_conn", 坏连接)
    r = client.get("/healthz")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "degraded"
    assert j["db_ok"] is False