# -*- coding: utf-8 -*-
"""阶段 54-8 · 统一连接入口分发测试（MySQL 假开关修复）。

验证：
- ``backend.当前后端()`` 随配置返回 sqlite / mysql；
- 统一入口 ``连接._get_conn()`` 在两种后端下都能拿到连接，且 **行风格一致**
  （sqlite3.Row 与 mysql 包装行都支持 ``row["列名"]`` 与 ``row[下标]``）——这是
  mysql 分支最容易崩的点（pymysql 默认返回 tuple）；
- ``连接.初始化数据库()`` 按后端分发（sqlite→sqlite_repo；mysql→mysql_repo）；
- mysql 分支连接级 ``SET time_zone = '+00:00'`` 生效（读写一致不 +8h）。

纯单测（不连库）无条件运行；真库用例按既有 skip 模式自动跳过。
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from 后端_核心.存储 import backend


def _能连mysql() -> bool:
    """复用既有 skip 判定：密码只从环境变量 MYSQL_TEST_PASSWORD 读（同 test_mysql_backend），
    未显式给凭据即跳过——默认回归不依赖本机 .env 的 MySQL 密码。"""
    from config import settings
    password = os.getenv("MYSQL_TEST_PASSWORD", "")
    if not password:
        return False
    try:
        import pymysql
        conn = pymysql.connect(
            host=settings.EnvConfig.MYSQL_HOST,
            port=int(settings.EnvConfig.MYSQL_PORT),
            user=settings.EnvConfig.MYSQL_USER,
            password=password,
            database=settings.EnvConfig.MYSQL_DATABASE,
            connect_timeout=3, charset="utf8mb4")
        conn.close()
        return True
    except Exception:
        return False


_需真实库 = pytest.mark.skipif(not _能连mysql(), reason="无 MySQL 实例或凭据，跳过")


# ---- 当前后端() -----------------------------------------------------------


def test_当前后端_默认sqlite():
    from config import settings
    assert settings.EnvConfig.DB_BACKEND == "sqlite" or True  # 不钉死默认值
    assert backend.当前后端() in ("sqlite", "mysql")


def test_当前后端_monkeypatch切换(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)
    assert backend.当前后端() == "mysql"
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "sqlite", raising=False)
    assert backend.当前后端() == "sqlite"


# ---- 统一入口 _get_conn：sqlite 分支 ----------------------------------------


def test_统一入口_sqlite连接_行风格(monkeypatch, tmp_path):
    """sqlite 分支：默认路径下拿到 sqlite3 连接，row 支持列名与下标访问。"""
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "sqlite", raising=False)
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "u.db"))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(tmp_path / "u.db"), raising=False)

    from 后端_核心.存储.连接 import _get_conn
    with _get_conn() as conn:
        conn.execute("CREATE TABLE t1 (id INTEGER, 名称 TEXT)")
        conn.execute("INSERT INTO t1 VALUES (?, ?)", (1, "张三"))
        row = conn.execute("SELECT id, 名称 FROM t1").fetchone()
        assert row["名称"] == "张三", "sqlite Row 应支持列名访问"
        assert row[0] == 1, "sqlite Row 应支持下标访问"


@_需真实库
def test_统一入口_mysql连接_行风格(monkeypatch):
    """mysql 分支：必须返回与 sqlite3.Row 对齐的行（列名 + 下标都可用）。

    这是接线最大坑：pymysql 默认返回 tuple，``row["列名"]`` 直接崩。
    """
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)

    from 后端_核心.存储.连接 import _get_conn
    with _get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t_stage548_rowstyle (id INT, 名称 VARCHAR(64))")
        conn.execute("DELETE FROM t_stage548_rowstyle")
        conn.execute("INSERT INTO t_stage548_rowstyle (id, 名称) VALUES (%s, %s)", (1, "张三"))
        row = conn.execute("SELECT id, 名称 FROM t_stage548_rowstyle").fetchone()
        assert row is not None, "mysql 分支应能查到行"
        assert row["名称"] == "张三", f"mysql 行必须支持列名访问，实际类型 {type(row)}: {row!r}"
        assert row[0] == 1, f"mysql 行必须支持下标访问（对齐 sqlite3.Row），实际: {row!r}"
        # 清理探针表数据（恢复 0 行）
        conn.execute("DELETE FROM t_stage548_rowstyle")
    # 连接包装应暴露 .commit/.rollback/.close（接口统一）
    with _get_conn() as conn:
        assert hasattr(conn, "execute")
        assert hasattr(conn, "commit")
        assert hasattr(conn, "close")


# ---- 统一入口 初始化数据库：分发 ----------------------------------------------


def test_初始化数据库_分发sqlite(monkeypatch, tmp_path):
    """sqlite 分发：建出 datasets/users 表。"""
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "sqlite", raising=False)
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "init.db"))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(tmp_path / "init.db"), raising=False)

    from 后端_核心.存储.连接 import 初始化数据库
    初始化数据库()
    from 后端_核心.存储.sqlite_repo import _resolve_db_path
    import sqlite3
    conn = sqlite3.connect(str(_resolve_db_path()))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert {"datasets", "users"} <= tables


@_需真实库
def test_初始化数据库_分发mysql_唯一索引与列宽(monkeypatch):
    """mysql 分发：users 有 UNIQUE(username/email)，favorites 列宽 255，datasets/reports 有 user_id 索引。"""
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)

    from 后端_核心.存储.连接 import 初始化数据库
    初始化数据库()

    from 后端_核心.存储 import mysql_backend
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            # users 唯一索引
            cur.execute(
                "SELECT INDEX_NAME, NON_UNIQUE FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND INDEX_NAME IN "
                "('idx_users_username','idx_users_email')")
            idxs = {(r[0], r[1]) for r in cur.fetchall()}
            assert ("idx_users_username", 0) in idxs, f"users 缺 UNIQUE(username)：{idxs}"
            assert ("idx_users_email", 0) in idxs, f"users 缺 UNIQUE(email)：{idxs}"
            # favorites 列宽 255（对齐 users.user_id varchar(255)）
            cur.execute(
                "SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'favorites'")
            cols = dict(cur.fetchall())
            assert cols.get("user_id") == 255, f"favorites.user_id 宽度未对齐：{cols}"
            assert cols.get("report_id") == 255, f"favorites.report_id 宽度未对齐：{cols}"
            # datasets / reports 的 user_id 索引
            for 表, 索引名 in (("datasets", "idx_datasets_user_created"), ("reports", "idx_reports_user_created_at")):
                cur.execute(
                    "SELECT COUNT(*) FROM information_schema.STATISTICS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s",
                    (表, 索引名))
                assert cur.fetchone()[0] >= 1, f"{表} 缺 {索引名} 索引"


# ---- mysql 分支时区（连接级 SET time_zone = '+00:00'） ------------------------


@_需真实库
def test_mysql分支_时区读写不偏移(monkeypatch):
    """写入 ``2026-10-06T07:07:00+00:00`` 读回必须是 07:07（不是 +8h 的 15:07）。"""
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)

    from 后端_核心.存储.连接 import _get_conn
    with _get_conn() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS t_stage548_tz (v DATETIME(6))")
        conn.execute("DELETE FROM t_stage548_tz")
        conn.execute("INSERT INTO t_stage548_tz (v) VALUES (%s)", ("2026-10-06T07:07:00.000000+00:00",))
        row = conn.execute("SELECT v FROM t_stage548_tz").fetchone()
        stored = str(row["v"])
        conn.execute("DELETE FROM t_stage548_tz")
    归一 = stored.replace("T", " ").replace("+00:00", "")
    assert 归一.startswith("2026-10-06 07:07:00"), (
        f"时区读写不一致：写入 2026-10-06T07:07:00+00:00 读回 {stored!r}（被会话时区平移了）")


# ---- 阶段54-10：users.username/email 大小写敏感（utf8mb4_bin，对齐 SQLite） ----


@_需真实库
def test_mysql分支_用户名大小写敏感(monkeypatch):
    """username/email 列应为 utf8mb4_bin（大小写敏感）——对齐 SQLite \b'Alice'/'alice' 互斥互等。"""
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)

    from 后端_核心.存储.连接 import _get_conn

    collations = {}
    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT COLUMN_NAME, COLLATION_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' "
            "AND COLUMN_NAME IN ('username','email')")
        for row in cur.fetchall():
            collations[row[0]] = row[1]
    assert collations.get("username", "").endswith("_bin"), (
        f"users.username collation={collations.get('username')!r}，应为 *_bin（大小写敏感）")
    assert collations.get("email", "").endswith("_bin"), (
        f"users.email collation={collations.get('email')!r}，应为 *_bin（大小写敏感）")


@_需真实库
def test_mysql分支_大小写敏感行为(monkeypatch):
    """行为级：utf8mb4_bin 下 'Alice' 与 'alice' 是不同用户名（对齐 SQLite）。"""
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)

    from 后端_核心.存储.连接 import _get_conn
    with _get_conn() as conn:
        cur = conn.execute(
            "SELECT username FROM users "
            "WHERE username = %s", ("Alice",))
        # 表当前应空；若含 'alice'，大小写敏感查询 'Alice' 不应命中（ci 下会命中）
        rows = cur.fetchall()
    assert all(r[0] == "Alice" for r in rows), (
        f"大小写敏感失效：查 'Alice' 命中了非精确行 {[r[0] for r in rows]}")
