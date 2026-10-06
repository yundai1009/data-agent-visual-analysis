# -*- coding: utf-8 -*-
"""阶段 54-8 · 统一连接入口（MySQL 假开关修复的核心收敛点）。

13 个仓储（以及 sqlite_repo 的函数体）原来全部 ``from 后端_核心.存储.sqlite_repo
import _get_conn``——那是纯 sqlite3 连接，与 ``DB_BACKEND`` 无关，导致 mysql 配置下
业务数据仍落 SQLite（healthz 假装 mysql）。

本模块提供：
- :func:`_get_conn`：按 ``backend.当前后端()`` 分发 sqlite_backend / mysql_backend；
  mysql 分支额外做两件事：
    1. ``SET time_zone = '+00:00'``（连接级时区归一化，写入/读回不 +8h）；
    2. 套上 ``mysql_backend._MySQL连接包装``（DictCursor + 行对齐 sqlite3.Row +
       运行期 ``?``→``%s`` 转换）——这是 mysql 分支不崩 ``row["列名"]`` 的关键。
- :func:`初始化数据库`：按后端建齐全部业务表（sqlite→sqlite_repo；mysql→mysql_repo）。

仓储层只改 import 一行（指向本模块），函数体不变。
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from 后端_核心.存储.backend import 当前后端


@contextmanager
def _get_conn() -> Iterator:
    """统一连接入口：按 DB_BACKEND 分发，行风格对齐 sqlite3.Row。"""
    if 当前后端() == "mysql":
        from 后端_核心.存储 import mysql_backend
        with mysql_backend.get_conn() as 内连接:
            # 连接级时区归一化：repo 写的是带 +00:00 的 ISO 串，若不固定会话时区，
            # MySQL 按 SYSTEM（本机 +08）二次换算，读回会静默 +8h。
            with 内连接.cursor() as cur:
                cur.execute("SET time_zone = '+00:00'")
            yield mysql_backend._MySQL连接包装(内连接)
    else:
        from 后端_核心.存储 import sqlite_backend
        with sqlite_backend.get_conn() as conn:
            yield conn


def 初始化数据库() -> None:
    """按后端初始化全部业务表（幂等，重复调用安全）。"""
    if 当前后端() == "mysql":
        from 后端_核心.存储 import mysql_repo
        mysql_repo.初始化数据库()
    else:
        from 后端_核心.存储.sqlite_repo import 初始化数据库 as _sqlite_初始化
        _sqlite_初始化()
