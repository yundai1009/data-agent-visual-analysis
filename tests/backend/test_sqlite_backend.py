# -*- coding: utf-8 -*-
"""阶段 54 · SQLite 后端：连接入口等价性与写锁统一测试。"""

from __future__ import annotations

import os
import sys
import threading

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from 后端_核心.存储 import backend, sqlite_backend, sqlite_repo


def test_连接可执行查询并提交(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(tmp_path / "t.db"), raising=False)
    with sqlite_backend.get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, v TEXT)")
        conn.execute("INSERT INTO t (id, v) VALUES (?, ?)", (1, "a"))
    with sqlite_backend.get_conn() as conn:
        row = conn.execute("SELECT v FROM t WHERE id = ?", (1,)).fetchone()
    assert row["v"] == "a"


def test_异常时回滚不残留(tmp_path, monkeypatch):
    """异常时写入回滚，不留残留数据。

    注：``CREATE TABLE``（DDL）在 sqlite3 ``isolation_level=DEFERRED`` 下走
    autocommit、不参与回滚（搬迁前原实现同样如此，属既有语义，本任务不改）；
    回滚保证的是「异常路径下已写入的数据不残留」——故断言 INSERT 的行数为 0。
    """
    from config import settings
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(tmp_path / "t.db"), raising=False)
    with pytest.raises(RuntimeError):
        with sqlite_backend.get_conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO t (id) VALUES (1)")
            raise RuntimeError("boom")
    with sqlite_backend.get_conn() as conn:
        rows = conn.execute("SELECT * FROM t WHERE id = 1").fetchall()
    assert len(rows) == 0  # 异常路径：INSERT 已回滚，无残留数据


def test_行工厂支持按列名访问(tmp_path, monkeypatch):
    from config import settings
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(tmp_path / "t.db"), raising=False)
    with sqlite_backend.get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, 名称 TEXT)")
        conn.execute("INSERT INTO t (id, 名称) VALUES (?, ?)", (1, "中文列名"))
    with sqlite_backend.get_conn() as conn:
        row = conn.execute("SELECT 名称 FROM t WHERE id = ?", (1,)).fetchone()
    assert row["名称"] == "中文列名"


def test_写锁与backend是同一对象():
    """阶段 54 · 统一写锁：sqlite_repo._write_lock 必须就是 backend.写锁。"""
    assert sqlite_repo._write_lock is backend.写锁, "写锁分裂会导致临界区不排他"


def test_解析db路径_环境变量优先(tmp_path, monkeypatch):
    from config import settings
    目标 = tmp_path / "env.db"
    monkeypatch.setenv("DAA_SQLITE_PATH", str(目标))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(tmp_path / "cfg.db"), raising=False)
    assert sqlite_backend.解析db路径() == 目标


def test_解析db路径_回退配置(tmp_path, monkeypatch):
    from config import settings
    配置路径 = tmp_path / "cfg.db"
    monkeypatch.delenv("DAA_SQLITE_PATH", raising=False)
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(配置路径), raising=False)
    assert sqlite_backend.解析db路径() == 配置路径
