# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】MySQL 的连接来源与"SQLite 行风格"适配层：只负责借连接、提交回滚，把 pymysql 变成仓储层熟悉的 conn。
# ============================================================
# 【做了什么】
#   1. _取引擎()：双检锁懒加载全局 SQLAlchemy Engine（pool_pre_ping 探活、pool_size=10、max_overflow=20、pool_recycle=3600 防 MySQL wait_timeout 断连）；_连接url() 用 quote_plus 编码账号密码并固定 charset=utf8mb4。
#   2. get_conn()：借 raw_connection()（DBAPI/pymysql），正常 commit、异常 rollback、finally 里 close() 归还连接池（SQLAlchemy 中 close 是归还而非断开）。
#   3. 行风格三层包装：_MySQLRow（row["列名"] 与 row[下标] 双可用，等价 sqlite3.Row）、_MySQL游标（包 DictCursor，fetchone/fetchall 包装成 _MySQLRow 并关游标，透传 rowcount/lastrowid/description、支持 for 迭代）、_MySQL连接包装（conn.execute(sql, params) 直接可用，内部 调 backend.转换SQL 做 ?→%s）。
#   4. 建表语句(表名, 列定义)：拼 InnoDB + utf8mb4 + utf8mb4_unicode_ci 的 CREATE TABLE IF NOT EXISTS。
# 【为什么这么做】
#   - 只借 SQLAlchemy 的连接池、不引 ORM：仓储层上百处业务 SQL 一行不改，只换连接来源与占位符风格；上 ORM 则迁移成本与"SQL 能被单测直接断言"的可测性一起丢掉。
#   - 自己写行包装而不是改十几个仓储：仓储层的通行写法就是 row["列名"]，改仓库等于全量返工；在连接层对齐 sqlite3.Row 语义，一次改动覆盖所有调用点。
#   - 占位符在运行期而不是 import 期转换：sqlite 分支的 SQL 保持原样，只有真正执行 mysql 语句前才转，方言差异集中在这一个点。
# 【关键约定与坑】
#   - get_conn() yield 出去的是裸 DBAPI 连接（无 ?→%s、无行包装）；要 sqlite3 风格必须走 连接._get_conn 的 mysql 分支套 _MySQL连接包装。
#   - _MySQL游标.fetchone/fetchall 取完即关游标，第二次取会报错；conn.cursor() 返回的是裸 DictCursor，不带 _MySQLRow 包装。
#   - 建表语句 明确不做表名/列名的反引号转义，标识符只能来自代码常量。
#   - 引擎本身不设置会话时区，SET time_zone 由 连接._get_conn 在借出后逐连接设置。
# ============================================================
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
