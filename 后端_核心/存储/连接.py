# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】仓储层唯一的连接入口：_get_conn 按 DB_BACKEND 分发 sqlite / mysql，并把两边都包装成 row["列名"] 可用的同一套用法。
# ============================================================
# 【做了什么】
#   1. _get_conn() 上下文管理器：当前后端()=="mysql" 时用 mysql_backend.get_conn()，先执行 SET time_zone = '+00:00' 再 yield _MySQL连接包装(内连接)；否则用 sqlite_backend.get_conn() 原样 yield。
#   2. 初始化数据库()：mysql → mysql_repo.初始化数据库()，sqlite → sqlite_repo.初始化数据库()，两边都幂等、重复调用安全。
#   3. 13 个仓储（repositories/*.py）连同 sqlite_repo 自身统一 from 后端_核心.存储.连接 import _get_conn，仓储函数体一行未改。
# 【为什么这么做】
#   - 收敛到这一个文件，而不是让每个仓储自己判断后端：13 个仓储原本都从 sqlite_repo import _get_conn，而那其实是纯 sqlite3 连接、与 DB_BACKEND 无关，于是 mysql 配置下业务数据仍落 SQLite（healthz 显示 mysql 的"假开关"）；把分发点提到 backend 层是最省事的修法。
#   - mysql 分支额外执行 SET time_zone='+00:00'：repo 写的是带 +00:00 的 ISO 串，不固定会话时区的话 MySQL 按 SYSTEM（本机 +08）二次换算，读回会静默 +8h。
#   - 用 _MySQL连接包装 统一行风格而不是改 13 个仓储的 row["列名"]：包装层一次解决 DictCursor 返回 tuple 的问题，仓储零改动。
#   - 两个后端都在函数体内延迟 import：sqlite 部署不必装 pymysql/sqlalchemy，mysql 部署也不必为 sqlite 分支付 import 成本。
# 【关键约定与坑】
#   - 只有经本模块拿到的 mysql 连接才有行包装与 ?→%s；直接用 mysql_backend.get_conn() 得到的是裸 DBAPI 连接，row["列名"] 会 TypeError。
#   - 提交/回滚/归还池由 mysql_backend.get_conn 或 sqlite_backend.get_conn 负责，调用方不要再手动 close 或 commit。
#   - 会话时区是逐连接设置的：新写任何 mysql 直连路径都要自己补 SET time_zone，否则时间列会差 8 小时。
#   - 初始化数据库 依赖当前后端值：测试里切换 DB_BACKEND 后必须重新调用，才会建对应后端的表。
# ============================================================
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
