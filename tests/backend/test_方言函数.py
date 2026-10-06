# -*- coding: utf-8 -*-
"""阶段 54-8 · 方言函数单测（MySQL 假开关修复）。

钉住 backend.py 方言适配函数在两种后端下产出的 SQL/判定：
- 冲突更新SQL（ON CONFLICT / ON DUPLICATE KEY UPDATE）
- 插入忽略（INSERT OR IGNORE / INSERT IGNORE）
- 表存在SQL（sqlite_master / information_schema）
- 表结构SQL（PRAGMA table_info / information_schema.COLUMNS）
- 创建索引SQL（sqlite 真建 / mysql 返回空串——索引归 mysql_repo 统一管理）
- 唯一冲突（sqlite "UNIQUE constraint failed" / mysql "Duplicate entry" 1062）

纯单测，不连库，CI 无条件运行。
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.存储 import backend


# ---- 冲突更新SQL -------------------------------------------------------------


def test_冲突更新SQL_sqlite_用ON_CONFLICT与excluded():
    sql = backend.冲突更新SQL(
        "sqlite", "email_codes",
        "(email, code_hash, expires_at, used, verify_attempts, last_sent_at, created_at)",
        "(?, ?, ?, 0, 0, ?, ?)",
        "email",
        ["code_hash", "expires_at", "used", "verify_attempts", "last_sent_at"],
    )
    assert "INSERT INTO email_codes" in sql
    assert "ON CONFLICT(email) DO UPDATE SET" in sql
    assert "code_hash = excluded.code_hash" in sql
    assert "last_sent_at = excluded.last_sent_at" in sql


def test_冲突更新SQL_mysql_用ON_DUPLICATE_KEY与VALUES():
    sql = backend.冲突更新SQL(
        "mysql", "email_codes",
        "(email, code_hash, expires_at, used, verify_attempts, last_sent_at, created_at)",
        "(?, ?, ?, 0, 0, ?, ?)",
        "email",
        ["code_hash", "expires_at", "used", "verify_attempts", "last_sent_at"],
    )
    assert "INSERT INTO email_codes" in sql
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert "code_hash = VALUES(code_hash)" in sql
    assert "excluded." not in sql, "mysql 分支不得出现 sqlite 的 excluded 语法"


# ---- 插入忽略 -----------------------------------------------------------------


def test_插入忽略_sqlite与mysql关键字():
    assert backend.插入忽略("sqlite", "event_payment", "(order_id)", "(1,'x')") \
        == "INSERT OR IGNORE INTO event_payment (order_id) VALUES (1,'x')"
    assert backend.插入忽略("mysql", "event_payment", "(order_id)", "(1,'x')") \
        == "INSERT IGNORE INTO event_payment (order_id) VALUES (1,'x')"


# ---- 表存在SQL ----------------------------------------------------------------


def test_表存在SQL_两种后端():
    sql_sqlite = backend.表存在SQL("sqlite")
    assert "sqlite_master" in sql_sqlite and "type='table'" in sql_sqlite
    sql_mysql = backend.表存在SQL("mysql")
    assert "information_schema.TABLES" in sql_mysql
    assert "TABLE_NAME AS name" in sql_mysql, "mysql 行必须有 name 键（对齐 sqlite_master）"
    assert "TABLE_TYPE = 'BASE TABLE'" in sql_mysql


# ---- 表结构SQL ----------------------------------------------------------------


def test_表结构SQL_两种后端():
    sql_sqlite = backend.表结构SQL("sqlite", "users")
    assert sql_sqlite == "PRAGMA table_info(users)"
    sql_mysql = backend.表结构SQL("mysql", "users")
    assert "information_schema.COLUMNS" in sql_mysql
    assert "COLUMN_NAME AS name" in sql_mysql, "mysql 行必须有 name 键（对齐 PRAGMA）"
    assert "TABLE_NAME = 'users'" in sql_mysql


# ---- 创建索引SQL --------------------------------------------------------------


def test_创建索引SQL_sqlite_真建_mysql_空串():
    sql_sqlite = backend.创建索引SQL("sqlite", "idx_users_email", "users", "email", 唯一=True)
    assert sql_sqlite == "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email)"
    sql_sqlite2 = backend.创建索引SQL("sqlite", "idx_reports_user_created_at", "reports", "(user_id, created_at)")
    assert sql_sqlite2 == "CREATE INDEX IF NOT EXISTS idx_reports_user_created_at ON reports (user_id, created_at)"
    # mysql：索引归 mysql_repo.初始化数据库 统一管理，repo 层执行点应跳过（空串）
    assert backend.创建索引SQL("mysql", "idx_users_email", "users", "email", 唯一=True) == ""


# ---- 唯一冲突（sqlite / mysql 错误信息差异） -----------------------------------


def test_唯一冲突_sqlite与mysql识别():
    assert backend.唯一冲突(ValueError("UNIQUE constraint failed: users.username")) is True
    assert backend.唯一冲突(RuntimeError("sqlite3.IntegrityError: UNIQUE constraint failed: idx_users_email")) is True
    # pymysql 1062 / IntegrityError：Duplicate entry（消息里没有 UNIQUE 字样，靠 errno/关键字识别）
    assert backend.唯一冲突(RuntimeError("(1062, \"Duplicate entry 'alice' for key 'users.idx_users_username'\"）")) is True
    # 非唯一性错误不得误判
    assert backend.唯一冲突(RuntimeError("(1054, \"Unknown column 'x'\")")) is False
    assert backend.唯一冲突(RuntimeError("disk I/O error")) is False
