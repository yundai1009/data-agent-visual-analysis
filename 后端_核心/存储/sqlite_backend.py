# -*- coding: utf-8 -*-
"""阶段 54 · SQLite 后端：连接管理与路径解析。

从 sqlite_repo.py 搬出，使连接获取成为可替换的后端能力（MySQL 后端见 mysql_backend.py）。
行为与搬迁前逐字等价——本任务验收标准之一就是全量回归数字不变。
"""
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
