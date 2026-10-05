# -*- coding: utf-8 -*-
"""阶段 54 · SQLite→MySQL 迁移脚本测试。

用临时 SQLite 库（tmp_path）+ 真实 MySQL 做端到端迁移。无 MySQL 凭据时 skip。
绝不碰生产 data/daa.db。

目标库口径
----------
实际写入目标来自 ``.env`` 的 ``MYSQL_*``（脚本走 ``mysql_backend.get_conn()``，
与 Task 5 的 test_mysql_backend 同一口径）；``MYSQL_TEST_*`` 环境变量只用于
「有没有 MySQL/凭据」的可用性探测与 skip 判定。

为何测试表名用 ``t_stage54_mig_*`` 前缀
--------------------------------------
- daa_app 无 CREATE DATABASE / DROP 权限，无法建独立测试库、测试后也删不掉表；
- 若直接用 ``users``/``reports`` 业务名，测试会把窄 schema 的表留在生产目标库
  ``daa`` 里，将来正式迁移（--清空目标 后灌入生产 16 张表）会因列不一致报错；
- 用带 ``t_stage54_mig_`` 前缀的专属表名，生产业务表永不触碰，残留也一眼可辨。
"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from 后端_核心.存储 import mysql_backend, sqlite_backend


def _能连mysql() -> bool:
    if not os.getenv("MYSQL_TEST_PASSWORD"):
        return False
    try:
        import pymysql
        conn = pymysql.connect(
            host=os.getenv("MYSQL_TEST_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_TEST_PORT", "3306")),
            user=os.getenv("MYSQL_TEST_USER", "daa_app"),
            password=os.environ["MYSQL_TEST_PASSWORD"],
            database=os.getenv("MYSQL_TEST_DATABASE", "daa"),
            connect_timeout=3, charset="utf8mb4")
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture
def 源sqlite库(tmp_path, monkeypatch):
    """建一个含几张代表性业务表的临时 SQLite 库（测试专用表名，绝不碰生产表）。"""
    from config import settings
    路径 = tmp_path / "src.db"
    monkeypatch.setenv("DAA_SQLITE_PATH", str(路径))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(路径), raising=False)
    with sqlite_backend.get_conn() as conn:
        # TEXT 主键表：验证 TEXT PRIMARY KEY → VARCHAR(255) PRIMARY KEY
        conn.execute(
            "CREATE TABLE t_stage54_mig_users ("
            "user_id TEXT PRIMARY KEY, 用户名 TEXT NOT NULL, 创建时间 TEXT)")
        conn.execute(
            "INSERT INTO t_stage54_mig_users VALUES (?,?,?)",
            ("u1", "张三", "2026-01-01T10:00:00"))
        conn.execute(
            "INSERT INTO t_stage54_mig_users VALUES (?,?,?)",
            ("u2", "李四", "2026-01-02T11:30:00"))
        # INTEGER 主键表：验证 INTEGER PRIMARY KEY → INT AUTO_INCREMENT PRIMARY KEY
        conn.execute(
            "CREATE TABLE t_stage54_mig_reports ("
            "report_id INTEGER PRIMARY KEY AUTOINCREMENT, 标题 TEXT, 创建时间 TEXT)")
        conn.execute(
            "INSERT INTO t_stage54_mig_reports (标题, 创建时间) VALUES (?,?)",
            ("报表A", "2026-02-01T09:00:00"))
    return 路径


@ pytest.mark.skipif(not _能连mysql(), reason="无 MySQL 实例或凭据，跳过")
def test_迁移_表与行数一致(源sqlite库):
    from scripts import migrate_sqlite_to_mysql as m
    报告 = m.迁移(源sqlite库, 清空目标=True)
    assert 报告["t_stage54_mig_users"]["迁入"] == 2
    assert 报告["t_stage54_mig_reports"]["迁入"] == 1
    # MySQL 侧核对（与迁移同一连接口径：mysql_backend）
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM t_stage54_mig_users")
            assert cur.fetchone()[0] >= 2
            cur.execute("SELECT 用户名 FROM t_stage54_mig_users WHERE user_id = %s", ("u1",))
            assert cur.fetchone()[0] == "张三"
            # 列类型映射契约：TEXT 主键 → varchar(255)（MySQL 的 TEXT 不能做主键）、
            # 时间列 → datetime、INTEGER 主键 → 自增主键。
            # 只断言值不够——值可能靠 MySQL 隐式转换蒙混过关；真正把 TEXT 当主键的
            # 建表语句会在 CREATE TABLE 阶段就报错，断言列类型才钉得住映射规则。
            cur.execute(
                "SELECT COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", ("t_stage54_mig_users",))
            列类型 = {r[0]: r[1] for r in cur.fetchall()}
            assert 列类型["user_id"] == "varchar(255)", 列类型
            assert 列类型["创建时间"].startswith("datetime"), 列类型
            cur.execute(
                "SELECT COLUMN_TYPE, COLUMN_KEY, EXTRA FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
                ("t_stage54_mig_reports", "report_id"))
            主键列类型, 主键键, 主键额外 = cur.fetchone()
            assert 主键列类型.startswith("int") and 主键键 == "PRI" and "auto_increment" in 主键额外, \
                f"INTEGER 主键未转成自增主键：{主键列类型}/{主键键}/{主键额外}"


@ pytest.mark.skipif(not _能连mysql(), reason="无 MySQL 实例或凭据，跳过")
def test_迁移_时间列转DATETIME(源sqlite库):
    from scripts import migrate_sqlite_to_mysql as m
    m.迁移(源sqlite库, 清空目标=True)
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 创建时间 FROM t_stage54_mig_users WHERE user_id = %s", ("u1",))
            v = cur.fetchone()[0]
    assert hasattr(v, "year"), f"应转成 MySQL DATETIME 类型，实得 {type(v)}"
    assert v.year == 2026 and v.month == 1


@pytest.fixture
def 源sqlite库_含非法时间(tmp_path, monkeypatch):
    """建一个含一条非法时间值记录的临时 SQLite 库（TEXT 主键表）。

    用于验证 I-1：非法 ISO 时间串在 MySQL 严格模式下插不进 DATETIME 列，
    落库置 NULL 的同时必须把「表/列/行标识/原始串/原因」记进迁移结果，
    使数据事后可恢复（源库原值永不被破坏）。
    """
    from config import settings
    路径 = tmp_path / "src_bad_time.db"
    monkeypatch.setenv("DAA_SQLITE_PATH", str(路径))
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(路径), raising=False)
    with sqlite_backend.get_conn() as conn:
        conn.execute(
            "CREATE TABLE t_stage54_mig_users ("
            "user_id TEXT PRIMARY KEY, 用户名 TEXT NOT NULL, 创建时间 TEXT)")
        conn.execute(
            "INSERT INTO t_stage54_mig_users VALUES (?,?,?)",
            ("u1", "张三", "2026-01-01T10:00:00"))
        conn.execute(
            "INSERT INTO t_stage54_mig_users VALUES (?,?,?)",
            ("u2", "李四", "not-a-date"))  # 非法 ISO 时间串
    return 路径


@ pytest.mark.skipif(not _能连mysql(), reason="无 MySQL 实例或凭据，跳过")
def test_迁移_非法时间置NULL但失败可恢复(源sqlite库_含非法时间):
    """I-1：非法时间值 → MySQL 侧 NULL + 源库原值保留 + 完整失败记录可恢复。"""
    import sqlite3
    from scripts import migrate_sqlite_to_mysql as m

    报告 = m.迁移(源sqlite库_含非法时间, 清空目标=True)

    # 1) 源库原值仍在（迁移脚本全程 mode=ro，且失败不影响后续行）
    with sqlite3.connect(源sqlite库_含非法时间) as conn:
        源值 = conn.execute(
            "SELECT 创建时间 FROM t_stage54_mig_users WHERE user_id = 'u2'").fetchone()[0]
    assert 源值 == "not-a-date", f"源库原始值不能被破坏：{源值!r}"

    # 2) MySQL 严格模式下非法串插不进 DATETIME 列 → 该值落库为 NULL
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 创建时间 FROM t_stage54_mig_users WHERE user_id = %s", ("u2",))
            v = cur.fetchone()[0]
    assert v is None, f"非法时间值应落库为 NULL，实得 {v!r}"
    # 合法行的时间值不受影响
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 创建时间 FROM t_stage54_mig_users WHERE user_id = %s", ("u1",))
            v1 = cur.fetchone()[0]
    assert v1 is not None and v1.year == 2026, f"合法行时间被破坏：{v1!r}"

    # 3) 结构化失败记录：表/列/行标识(主键值)/原始串/原因 一个不少
    失败 = 报告["时间转换失败"]
    assert len(失败) == 1, f"应恰好 1 条失败记录，实得 {失败}"
    记录 = 失败[0]
    assert 记录["表名"] == "t_stage54_mig_users", 记录
    assert 记录["列名"] == "创建时间", 记录
    assert 记录["行标识"] == {"user_id": "u2"}, 记录["行标识"]
    assert 记录["原始串"] == "not-a-date", 记录["原始串"]
    assert "不是合法 ISO" in 记录["原因"], 记录["原因"]

    # 4) as_dict 序列化（--报告 JSON 文件写入的就是它）同样携带失败记录
    序列化 = 报告.as_dict()
    assert 序列化["时间转换失败"][0]["原始串"] == "not-a-date", 序列化["时间转换失败"]


@ pytest.mark.skipif(not _能连mysql(), reason="无 MySQL 实例或凭据，跳过")
def test_迁移_幂等_重复运行不重复(源sqlite库):
    from scripts import migrate_sqlite_to_mysql as m
    m.迁移(源sqlite库, 清空目标=True)
    m.迁移(源sqlite库, 清空目标=False)  # 不清空，重复迁
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM t_stage54_mig_users")
            assert cur.fetchone()[0] == 2, "幂等：重复迁移不应产生重复行"


@ pytest.mark.skipif(not _能连mysql(), reason="无 MySQL 实例或凭据，跳过")
def test_dry_run_不写库(源sqlite库):
    from scripts import migrate_sqlite_to_mysql as m
    # dry-run 不建表：先按源库 schema 预建目标表，再清空，然后 dry-run 应零写入
    m.建目标表(源sqlite库)
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM t_stage54_mig_users")
            cur.execute("DELETE FROM t_stage54_mig_reports")
    m.迁移(源sqlite库, 清空目标=True, dry_run=True)
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            # 清空目标后 dry_run 不应写入任何行
            cur.execute("SELECT COUNT(*) FROM t_stage54_mig_users")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM t_stage54_mig_reports")
            assert cur.fetchone()[0] == 0
