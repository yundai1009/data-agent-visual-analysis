# -*- coding: utf-8 -*-
"""阶段 54 · MySQL 后端集成测试。

真实连本机 MySQL（DB_BACKEND=mysql 时启用）。无实例或无凭据时全部 skip，
不 fail——CI 环境没有 MySQL 也不应该假红。
密码只从环境变量 MYSQL_TEST_PASSWORD 读，不进代码、不进日志。
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from 后端_核心.存储 import backend, mysql_backend


def _凭据() -> dict:
    return {
        "host": os.getenv("MYSQL_TEST_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_TEST_PORT", "3306")),
        "user": os.getenv("MYSQL_TEST_USER", "daa_app"),
        "password": os.getenv("MYSQL_TEST_PASSWORD", ""),
        "database": os.getenv("MYSQL_TEST_DATABASE", "daa"),
    }


def _能连上() -> bool:
    if not _凭据()["password"]:
        return False
    try:
        import pymysql
        c = _凭据()
        conn = pymysql.connect(host=c["host"], port=c["port"], user=c["user"],
                               password=c["password"], database=c["database"],
                               connect_timeout=3, charset="utf8mb4")
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _能连上(), reason="无 MySQL 实例或凭据，跳过")


def test_mysql_连接并往返():
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS t_stage54 (id INT PRIMARY KEY, v VARCHAR(64))")
            cur.execute("DELETE FROM t_stage54 WHERE id = 1")
            cur.execute("INSERT INTO t_stage54 (id, v) VALUES (%s, %s)", (1, "hello"))
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT v FROM t_stage54 WHERE id = %s", (1,))
            assert cur.fetchone()[0] == "hello"


def test_mysql_异常时回滚():
    from pymysql.err import IntegrityError
    with pytest.raises(IntegrityError):
        with mysql_backend.get_conn() as conn:
            with conn.cursor() as cur:
                # 插入重复主键 → IntegrityError，且事务应被回滚（不污染后续）
                cur.execute("INSERT INTO t_stage54 (id, v) VALUES (%s, %s)", (1, "dup"))
                cur.execute("INSERT INTO t_stage54 (id, v) VALUES (%s, %s)", (1, "dup2"))
    # 回滚后 id=1 仍存在且为第一次的值
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT v FROM t_stage54 WHERE id = %s", (1,))
            assert cur.fetchone()[0] == "hello"


def test_建表语句_含InnoDB与utf8mb4():
    sql = mysql_backend.建表语句("t_demo", [("id", "INT PRIMARY KEY"), ("名称", "VARCHAR(64)")])
    assert "CREATE TABLE IF NOT EXISTS `t_demo`" in sql
    assert "InnoDB" in sql
    assert "utf8mb4" in sql
    assert "`名称`" in sql, "中文列名应加反引号"


def test_DB_BACKEND开关_能切到mysql(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)
    assert backend.当前后端() == "mysql"
