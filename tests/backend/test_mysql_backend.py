# -*- coding: utf-8 -*-
"""阶段 54 · MySQL 后端集成测试。

真实连本机 MySQL（DB_BACKEND=mysql 时启用）。只有**真正连库**的用例在无实例或无凭据时
skip，不 fail——CI 环境没有 MySQL 也不应该假红；纯单测（不连库：URL 构造 / get_conn 事务
语义 / DDL 文本 / 后端开关）无条件运行，CI 也守得住。
密码只从环境变量 MYSQL_TEST_PASSWORD 读，不进代码、不进日志。
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest
from sqlalchemy.engine.url import make_url

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


# 只有真正连库的用例受 MySQL 可用性约束；纯单测无条件运行
_需真实库 = pytest.mark.skipif(not _能连上(), reason="无 MySQL 实例或凭据，跳过")


@_需真实库
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


@_需真实库
def test_mysql_异常时回滚():
    """真实连库：异常路径必须把「出错前已成功写入」的那一行撤销。

    为什么不能断言「id=1 仍是旧值」：老用例第一条 INSERT 就撞主键立即失败（InnoDB 语句级
    失败，事务并未 abort），事务内压根没有任何成功写入——「值没变」既可能是回滚生效，
    也可能压根没回滚，删掉 get_conn 里的 rollback 用例照样绿（假通过）。

    现在的事务里先有一笔**成功**写入，再触发重复主键；断言口径变成「出错后这一行必须不存在」，
    只有真正回滚（或至少未提交）才成立。前置数据由本用例自建（建表 + 清 id=9001），
    不依赖 test_mysql_连接并往返 的执行顺序，单跑 ``pytest -k 回滚`` 也应通过。
    """
    from pymysql.err import IntegrityError
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS t_stage54 (id INT PRIMARY KEY, v VARCHAR(64))")
            cur.execute("DELETE FROM t_stage54 WHERE id = 9001")   # 自清洁：清掉历史残留

    with pytest.raises(IntegrityError):
        with mysql_backend.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("INSERT INTO t_stage54 (id, v) VALUES (%s, %s)", (9001, "first"))  # 成功写入
                cur.execute("INSERT INTO t_stage54 (id, v) VALUES (%s, %s)", (9001, "dup"))    # 重复主键 → 抛错

    # 回滚生效 → 出错前那次成功写入的 9001 必须不存在
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM t_stage54 WHERE id = %s", (9001,))
            assert cur.fetchone()[0] == 0, "异常路径未回滚：id=9001 的成功写入泄漏到事务外"


def test_mysql_get_conn_异常路径必回滚(monkeypatch):
    """纯单测（不连库）：get_conn 异常路径必须 rollback、不 commit、且归还连接。

    真实连库用例只看得到「数据没泄漏」这一结果，而 SQLAlchemy 连接池**归还连接时也会
    rollback**（``reset_on_return`` 默认 rollback），结果口径会掩盖 get_conn 自己有没有回滚。
    这里用假连接替换引擎，绕开连接池，直接钉住 get_conn 的事务语义：
    注释掉 get_conn 里的 ``conn.rollback()``，本用例必红。
    """
    class _假游标:
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False

    class _假连接:
        def __init__(self):
            self.提交数 = 0
            self.回滚数 = 0
            self.关闭数 = 0

        def cursor(self):
            return _假游标()

        def commit(self):
            self.提交数 += 1

        def rollback(self):
            self.回滚数 += 1

        def close(self):
            self.关闭数 += 1

    class _假引擎:
        def __init__(self, conn):
            self._conn = conn

        def raw_connection(self):
            return self._conn

    假连接 = _假连接()
    monkeypatch.setattr(mysql_backend, "_取引擎", lambda: _假引擎(假连接))

    with pytest.raises(RuntimeError, match="模拟业务异常"):
        with mysql_backend.get_conn() as conn:
            assert conn is 假连接
            raise RuntimeError("模拟业务异常")

    assert 假连接.回滚数 == 1, "异常路径必须调用 rollback"
    assert 假连接.提交数 == 0, "异常路径不得调用 commit"
    assert 假连接.关闭数 == 1, "连接必须归还"


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


def test_连接url_特殊字符经URL编码(monkeypatch):
    """纯单测（不连库）：账号/密码含 URL 保留字符时，DSN 仍能被正确解析回原值。

    密码若含 ``@`` / ``#`` / ``/`` / ``?``，裸拼会破坏 URL 结构——
    ``#`` 直接把后半段当成 fragment、``@`` 会截断 userinfo。
    """
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "MYSQL_USER", "daa@user")
    monkeypatch.setattr(settings.EnvConfig, "MYSQL_PASSWORD", "p@ss#w/rd?x")
    解析 = make_url(mysql_backend._连接url())
    assert 解析.username == "daa@user"
    assert 解析.password == "p@ss#w/rd?x"
    assert 解析.host == settings.EnvConfig.MYSQL_HOST
    assert 解析.port == settings.EnvConfig.MYSQL_PORT
    assert 解析.database == settings.EnvConfig.MYSQL_DATABASE
