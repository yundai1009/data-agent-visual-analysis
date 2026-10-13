# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】SQLite 后端的连接工厂：决定 db 文件路径、按次开连接、配好 row_factory/WAL/外键，并管事务提交时机。
# ============================================================
# 【做了什么】
#   1. 解析db路径()：优先级为 DAA_SQLITE_PATH 环境变量 > EnvConfig.SQLITE_PATH > 默认 data/daa.db（_默认db路径）；父目录由 get_conn 用 mkdir(parents=True, exist_ok=True) 兜底。
#   2. get_conn() 上下文管理器：每次调用新建连接（isolation_level="DEFERRED" 显式事务、timeout=30），设 row_factory=sqlite3.Row 与 PRAGMA busy_timeout=30000 / foreign_keys=ON / journal_mode=WAL。
#   3. 事务边界用 try/except/else/finally 四段：异常分支 rollback() 后 raise；else 分支才 commit()（commit 自身失败再 rollback 并抛出）；finally 只做 conn.close()。
# 【为什么这么做】
#   - 每请求新建连接而不是全局复用一个：sqlite3 连接对象默认 check_same_thread=True，跨线程复用会直接抛异常；WAL + busy_timeout 让"每请求一连"的开销可以接受。
#   - isolation_level="DEFERRED" 而不是默认 autocommit(None)：autocommit 下 with conn: 不会真正开事务，多表删除（如注销清理）不原子、rollback 失效。
#   - commit 只放正常路径（else）而不是 finally：旧实现异常分支 rollback 后又被 finally commit 一次，锁竞争等极端场景会掩盖真实错误语义。
#   - 连接获取从 sqlite_repo.py 搬成独立后端模块：让"连接从哪来"成为可替换能力（MySQL 见 mysql_backend.py），搬移要求行为逐字等价、全量回归数字不变。
# 【关键约定与坑】
#   - 本模块给的是原生 sqlite3 连接：没有 ?→%s 转换、没有行包装；跨库通用 SQL 必须继续走 backend 的方言函数。
#   - 提交与回滚由本上下文管理器负责，仓储里不要再自己 conn.commit()，否则会提前提交、破坏原子性。
#   - EnvConfig 可能还没有 SQLITE_PATH 字段，解析db路径 用 AttributeError 兜底；加配置项前先确认这里。
#   - journal_mode=WAL 会在 db 同目录留下 -wal / -shm 文件，备份脚本不能只拷 daa.db。
# ============================================================
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

# 默认 SQLite 文件路径：项目根目录下的 ``data/daa.db``
# 路径优先级：``DAA_SQLITE_PATH`` 环境变量 > ``EnvConfig.SQLITE_PATH`` > 默认值
_默认db路径 = Path("data/daa.db")


def 解析db路径() -> Path:
    """解析 SQLite 文件路径。优先级：环境变量 > 默认值。"""
    from config.settings import EnvConfig
    configured = ""
    try:
        configured = (EnvConfig.SQLITE_PATH or "").strip()
    except AttributeError:
        # 防御性：EnvConfig 可能还没加 SQLITE_PATH 字段
        configured = ""
    env_path = os.getenv("DAA_SQLITE_PATH", "").strip()
    chosen = env_path or configured or str(_默认db路径)
    return Path(chosen)


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """获取 SQLite 连接，用完即关。

    - 每次请求新建连接（SQLite 推荐用法，避免跨线程问题）
    - ``row_factory`` 设为 ``sqlite3.Row`` 让结果以列名访问
    - ``PRAGMA foreign_keys = ON`` 打开外键约束
    - ``PRAGMA journal_mode = WAL`` 提升并发读性能
    """
    db_path = 解析db路径()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # S9 修复：isolation_level="DEFERRED"（显式事务）替代 None（autocommit）——
    # 之前 with conn: 在 autocommit 下不开启事务，多表删除非原子、rollback 无效。
    # timeout=30 + busy_timeout 让写锁竞争时等待而非立即报 database is locked。
    conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED", timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
    except Exception:
        # 【Bug25 修复】异常路径：回滚后由 else/finally 结构保证不再误 commit
        conn.rollback()
        raise
    else:
        # 【Bug25 修复】仅正常路径才 commit：旧实现把 commit 放 finally，
        # 异常分支已 rollback 后 finally 又执行一次 commit（SQLite 中为无害空
        # 操作，但在 rollback 失败/锁竞争的极端场景会掩盖真实错误语义）。
        try:
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
