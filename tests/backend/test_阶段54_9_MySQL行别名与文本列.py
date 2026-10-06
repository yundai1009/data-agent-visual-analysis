# -*- coding: utf-8 -*-
"""阶段 54-9 · Fix M1 / M2（MySQL 审查 Minor-2 / Minor-3）。

- M1：`冲突更新SQL` MySQL 分支改用行别名语法（VALUES(col) 在 8.0.20+ 弃用、
  8.4 移除；`VALUES (...) AS new ... UPDATE c = new.c` 需 8.0.19+）。
  纯单测断言 SQL 字符串；有凭据真库实测「插入冲突 → 更新生效」（用后清理，0 行恢复）。
- M2：audit_log.detail / feedback.correction 窄 VARCHAR → TEXT（防截断），
  幂等升级「已是 text 家族不动」；真库跑 初始化数据库 后断言 information_schema 类型。

密码只从环境变量 MYSQL_TEST_PASSWORD 读（同 test_mysql_backend / test_mysql_全链路 约定），
无凭据时真库用例 skip——CI 不假红；纯单测无条件运行。
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from 后端_核心.存储 import backend  # noqa: E402


def _凭据() -> dict:
    from config import settings
    return {
        "host": settings.EnvConfig.MYSQL_HOST,
        "port": int(settings.EnvConfig.MYSQL_PORT),
        "user": settings.EnvConfig.MYSQL_USER,
        "password": os.getenv("MYSQL_TEST_PASSWORD", ""),
        "database": settings.EnvConfig.MYSQL_DATABASE,
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


_需真实库 = pytest.mark.skipif(not _能连上(), reason="无 MySQL 实例或凭据，跳过")


# ---- M1：SQL 字符串（纯单测，无条件运行） -----------------------------------------

def test_M1_冲突更新SQL_mysql_含行别名AS_new():
    sql = backend.冲突更新SQL(
        "mysql", "email_codes",
        "(email, code_hash, expires_at, used, verify_attempts, last_sent_at, created_at)",
        "(?, ?, ?, 0, 0, ?, ?)",
        "email",
        ["code_hash", "expires_at", "used", "verify_attempts", "last_sent_at"],
    )
    assert " AS new ON DUPLICATE KEY UPDATE" in sql
    assert "code_hash = new.code_hash" in sql
    assert "VALUES(" not in sql, "不得再用弃用的 VALUES(col) 语法"
    assert "excluded." not in sql


def test_M1_冲突更新SQL_sqlite_分支不变():
    sql = backend.冲突更新SQL(
        "sqlite", "email_codes", "(email, code_hash)", "(?, ?)", "email", ["code_hash"],
    )
    assert "ON CONFLICT(email) DO UPDATE SET" in sql
    assert "code_hash = excluded.code_hash" in sql
    assert "AS new" not in sql


# ---- M2：DDL 文本（纯单测，无条件运行） ---------------------------------------------

def test_M2_建表DDL_detail与correction为TEXT():
    from 后端_核心.存储 import mysql_repo
    ddl = "\n".join(mysql_repo._建表DDL)
    # 只断言 audit_log.detail / feedback.correction 两列（datasets.stored_path 等
    # 路径列仍是合法的 VARCHAR(512)，不在本修复范围）
    assert "`detail`      TEXT NOT NULL" in ddl, "audit_log.detail 应为 TEXT（防截断）"
    assert "`correction` TEXT NOT NULL" in ddl, "feedback.correction 应为 TEXT（防截断）"


def test_M2_文本列升级目标存在():
    from 后端_核心.存储 import mysql_repo
    assert mysql_repo._文本列改 == {"audit_log": ["detail"], "feedback": ["correction"]}


# ---- M1：真库实测（有凭据才跑） ------------------------------------------------------

@_需真实库
def test_M1_行别名冲突更新_真库插入冲突后更新生效(monkeypatch):
    """真库：`INSERT ... VALUES (...) AS new ON DUPLICATE KEY UPDATE c = new.c`
    无语法错误且冲突时更新生效。复用既有 email_codes 表（daa_app 无 DROP 权限），
    测试行用后 DELETE，恢复 0 行。"""
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)

    from 后端_核心.存储 import mysql_backend
    from 后端_核心.存储.连接 import _get_conn

    _EMAIL = "stage549_m1@test.com"
    with mysql_backend.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM email_codes WHERE email = %s", (_EMAIL,))
    try:
        sql = backend.冲突更新SQL(
            "mysql", "email_codes",
            "(email, code_hash, expires_at, used, verify_attempts, last_sent_at, created_at)",
            "(?, ?, ?, 0, 0, ?, ?)",
            "email",
            ["code_hash", "expires_at", "used", "verify_attempts", "last_sent_at"],
        )
        assert " AS new ON DUPLICATE KEY UPDATE" in sql
        # 值清单 (?, ?, ?, 0, 0, ?, ?) → 5 个占位：email/code_hash/expires_at + last_sent_at/created_at
        with _get_conn() as conn:
            conn.execute(sql, (_EMAIL, "first-hash", "2026-01-02T00:00:00+00:00",
                               "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
        with _get_conn() as conn:
            conn.execute(sql, (_EMAIL, "second-hash", "2026-01-03T00:00:00+00:00",
                               "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
        with mysql_backend.get_conn() as conn, conn.cursor() as cur:
            cur.execute("SELECT code_hash, expires_at FROM email_codes WHERE email = %s", (_EMAIL,))
            row = cur.fetchone()
            assert row is not None and row[0] == "second-hash", "冲突后应更新为 second-hash"
            assert row[1] == "2026-01-03T00:00:00+00:00", "多列更新应生效"
            cur.execute("SELECT COUNT(*) FROM email_codes WHERE email = %s", (_EMAIL,))
            assert cur.fetchone()[0] == 1, "upsert 不应产生第二行"
    finally:
        with mysql_backend.get_conn() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM email_codes WHERE email = %s", (_EMAIL,))


# ---- M2：真库实测（有凭据才跑） ------------------------------------------------------

@_需真实库
def test_M2_初始化后_detail与correction为文本类型():
    """真库：跑 初始化数据库（幂等）后，audit_log.detail / feedback.correction
    必须是 text 家族（text/mediumtext/longtext），不再是窄 VARCHAR。"""
    from 后端_核心.存储 import mysql_backend, mysql_repo

    mysql_repo.初始化数据库()
    with mysql_backend.get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_log' AND COLUMN_NAME = 'detail'"
        )
        detail_type = (cur.fetchone() or [""])[0]
        cur.execute(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'feedback' AND COLUMN_NAME = 'correction'"
        )
        correction_type = (cur.fetchone() or [""])[0]
    assert (detail_type or "").lower() in ("text", "mediumtext", "longtext"), \
        f"audit_log.detail 应为 text 家族，实际 {detail_type}"
    assert (correction_type or "").lower() in ("text", "mediumtext", "longtext"), \
        f"feedback.correction 应为 text 家族，实际 {correction_type}"


@_需真实库
def test_M2_确保文本列_窄VARCHAR升级路径():
    """真库：验证 _确保文本列 的 ALTER 升级路径本身——对空表 audit_log.detail
    先"降级"成窄 VARCHAR(512) 再跑 _确保文本列 升回 TEXT。

    仅当 audit_log 为空（0 行）时执行降级（避免截断真实数据）；finally 必定恢复 TEXT。
    """
    from 后端_核心.存储 import mysql_backend, mysql_repo

    with mysql_backend.get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM audit_log")
        if cur.fetchone()[0] != 0:
            pytest.skip("audit_log 非空，跳过降级-升级路径验证（避免截断真实数据）")
        cur.execute("ALTER TABLE `audit_log` MODIFY COLUMN `detail` VARCHAR(512) NOT NULL")
        cur.execute(
            "SELECT DATA_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_log' AND COLUMN_NAME = 'detail'"
        )
        assert cur.fetchone()[0].lower() == "varchar", "前置降级应成功"
        try:
            mysql_repo._确保文本列(cur, "audit_log", "detail")
            cur.execute(
                "SELECT DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'audit_log' AND COLUMN_NAME = 'detail'"
            )
            assert cur.fetchone()[0].lower() == "text", "窄 VARCHAR 应被 _确保文本列 升为 TEXT"
        finally:
            mysql_repo._确保文本列(cur, "audit_log", "detail")


@_需真实库
def test_M2_长内容往返不截断():
    """真库：超 512/1024 字符的 detail / correction 写入再读回，字节完整（无截断）。"""
    from 后端_核心.存储 import mysql_backend, mysql_repo

    mysql_repo.初始化数据库()
    长detail = "审计明细-" * 300          # ~1500 字符（超原 VARCHAR(512)）
    长correction = "纠错内容-" * 600      # ~3000 字符（超原 VARCHAR(1024)）
    with mysql_backend.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_log WHERE target_id = 'stage549_m2'")
        cur.execute(
            "INSERT INTO audit_log (user_id, username, action, target_type, target_id, detail, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            ("stage549_m2", "stage549", "测试", "test", "stage549_m2", 长detail, "2026-01-01T00:00:00+00:00"),
        )
        cur.execute("DELETE FROM feedback WHERE task_id = 'stage549_m2'")
        cur.execute(
            "INSERT INTO feedback (user_id, task_id, score, correction, sync_kb, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            ("stage549_m2", "stage549_m2", 5, 长correction, 1, "2026-01-01T00:00:00+00:00"),
        )
        cur.execute("SELECT detail FROM audit_log WHERE target_id = 'stage549_m2'")
        assert cur.fetchone()[0] == 长detail, "audit_log.detail 被截断"
        cur.execute("SELECT correction FROM feedback WHERE task_id = 'stage549_m2'")
        assert cur.fetchone()[0] == 长correction, "feedback.correction 被截断"
    # 清理：恢复 0 行
    with mysql_backend.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_log WHERE target_id = 'stage549_m2'")
        cur.execute("DELETE FROM feedback WHERE task_id = 'stage549_m2'")
