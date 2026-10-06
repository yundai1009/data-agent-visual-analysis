# -*- coding: utf-8 -*-
"""阶段 54 · MySQL 后端：SQLAlchemy 引擎仅作连接池 + 连接保活，SQL 仍走原生。

为什么用 SQLAlchemy 而非裸 pymysql
--------------------------------
- 连接池：借出前 ``pool_pre_ping`` 自动探活，数据库重启/网络抖动导致连接已死时
  自动换一条，用户无感知（裸 pymysql 需自己实现）
- 不引 ORM：127 处业务 SQL 一行不改，只换连接来源与占位符风格

配合 backend.占位符风格/转换SQL：repo 层写 ``?``，本后端执行时转 ``%s``（pymysql 风格）。
（此处仅为说明性引用，本模块**不** import backend——无循环依赖，也无实际使用。）
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator, List, Tuple
from urllib.parse import quote_plus

import pymysql
from sqlalchemy import create_engine

_引擎 = None
_引擎锁 = threading.Lock()


def _连接url() -> str:
    """拼 SQLAlchemy DSN。

    账号/密码经 ``quote_plus`` 做 URL 编码：密码含 ``@`` / ``#`` / ``/`` / ``?`` 这类
    URL 保留字符时，裸拼会破坏 URL 结构（``#`` 之后被当成 fragment、``@`` 截断 userinfo）。
    """
    from config.settings import EnvConfig
    return (
        f"mysql+pymysql://{quote_plus(EnvConfig.MYSQL_USER)}:{quote_plus(EnvConfig.MYSQL_PASSWORD)}"
        f"@{EnvConfig.MYSQL_HOST}:{EnvConfig.MYSQL_PORT}/{EnvConfig.MYSQL_DATABASE}"
        f"?charset=utf8mb4"
    )


def _取引擎():
    """懒加载全局引擎（双检锁），进程内复用连接池。"""
    global _引擎
    if _引擎 is None:
        with _引擎锁:
            if _引擎 is None:
                _引擎 = create_engine(
                    _连接url(),
                    pool_pre_ping=True,     # 借出前探活，连接失效自动换
                    pool_size=10,           # 常驻连接
                    max_overflow=20,        # 峰值额外连接
                    pool_recycle=3600,      # 1h 回收，防 MySQL wait_timeout 断连
                    future=True,
                )
    return _引擎


@contextmanager
def get_conn() -> Iterator:
    """借一条连接（用完归还池）；正常 commit、异常 rollback。

    返回类型标注为 ``Iterator``：经 ``@contextmanager`` 装饰后，调用方拿到的实际是
    ``_GeneratorContextManager``（上下文管理器），注解与被包装的生成器函数一致。

    借出的是 DBAPI 连接（pymysql），调用方用 ``conn.cursor()`` 走原生 cursor。
    """
    conn = _取引擎().raw_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()   # 归还池（SQLAlchemy 的 raw_connection.close 是归还，非断开）


def 建表语句(表名: str, 列定义: List[Tuple[str, str]]) -> str:
    """生成 MySQL 建表 DDL：InnoDB + utf8mb4，列名/表名反引号包裹。

    列定义形如 ``[("id", "INT PRIMARY KEY"), ("名称", "VARCHAR(64)")]``。
    已知限制：**表名与列名均不做反引号（```）转义**——项目纪律禁止此类标识符，本期不处理。
    """
    列清单 = ", ".join(f"`{列名}` {列类型}" for 列名, 列类型 in 列定义)
    return (
        f"CREATE TABLE IF NOT EXISTS `{表名}` ({列清单}) "
        f"ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
    )


# ---------------------------------------------------------------------------
# 阶段 54-8：连接行风格对齐（MySQL 假开关修复的最大坑）
# ---------------------------------------------------------------------------
# 仓储层通行写法是 ``row["列名"]``（sqlite3.Row 语义），而 pymysql 默认 cursor
# 返回 tuple——一旦把连接切到 mysql，``row["列名"]`` 全部 TypeError。
# 这里提供三层包装，把 pymysql 连接对齐成 sqlite3 连接的使用方式：
#   - `_MySQLRow`     ：结果行，既支持 ``row["列名"]`` 也支持 ``row[下标]``（同 sqlite3.Row）
#   - `_MySQL游标`    ：包装 DictCursor，fetchone/fetchall 返回 _MySQLRow，
#                      rowcount/lastrowid/description 透传，支持 for 迭代
#   - `_MySQL连接包装`：conn.execute(sql, params) 直接可用（内部 ? → %s 运行期转换）
# 统一入口 `连接._get_conn()` 在 mysql 分支借出连接时套上 `_MySQL连接包装`。
# ---------------------------------------------------------------------------


class _MySQLRow(dict):
    """对齐 sqlite3.Row 语义的结果行：``row["列名"]`` 与 ``row[下标]`` 都可用。"""

    __slots__ = ("_列序",)

    def __init__(self, 映射: dict, 列序: tuple) -> None:
        super().__init__(映射)
        self._列序 = 列序

    def __getitem__(self, key):
        if isinstance(key, int):
            key = self._列序[key]          # 位置访问 → 列名（对齐 sqlite3.Row）
        return dict.__getitem__(self, key)


class _MySQL游标:
    """包装 pymysql DictCursor：行统一包装为 :class:`_MySQLRow`。"""

    __slots__ = ("_cur", "_列序")

    def __init__(self, cur) -> None:
        self._cur = cur
        self._列序 = tuple(c[0] for c in (cur.description or ()))

    def _包装(self, row):
        return _MySQLRow(row, self._列序) if row is not None else None

    def _关闭(self) -> None:
        try:
            self._cur.close()
        except Exception:
            pass

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            self._关闭()
            return None
        return self._包装(row)

    def fetchall(self):
        rows = [self._包装(r) for r in self._cur.fetchall()]
        self._关闭()
        return rows

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def description(self):
        return self._cur.description

    def __iter__(self):
        return self

    def __next__(self):
        row = self.fetchone()
        if row is None:
            self._关闭()
            raise StopIteration
        return row


class _MySQL连接包装:
    """把 pymysql 连接包装成 sqlite3 风格：``conn.execute(sql, params)`` 直接可用。

    - ``?`` 占位符在**运行期**经 ``backend.转换SQL`` 转成 ``%s``（方言适配生效）；
    - 行风格对齐 sqlite3.Row（见 :class:`_MySQLRow`）；
    - ``conn.cursor()`` 返回 DictCursor（兼容既有直接 cursor 写法）。
    """

    __slots__ = ("_conn",)

    def __init__(self, conn) -> None:
        self._conn = conn

    def execute(self, sql: str, params=None):
        from 后端_核心.存储.backend import 转换SQL
        sql = 转换SQL(sql, "mysql")          # ? → %s（运行期方言适配的唯一收敛点）
        cur = self._conn.cursor(pymysql.cursors.DictCursor)
        try:
            cur.execute(sql, params)
        except Exception:
            try:
                cur.close()
            except Exception:
                pass
            raise
        return _MySQL游标(cur)

    def cursor(self):
        return self._conn.cursor(pymysql.cursors.DictCursor)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False
