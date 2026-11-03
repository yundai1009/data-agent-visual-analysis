# -*- coding: utf-8 -*-
"""阶段九十 · R15：产品价值漏斗（注册→传数据→出报表→回访）。

「回访」用「同一用户报表出现在不同日期」代理，本测试在隔离库造跨天/同日两组数据，
锁住口径：跨天算回访、同日不算；转化率分母取上一步人数。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture()
def 隔离库(tmp_path, monkeypatch):
    """独立临时 SQLite（照 test_阶段77 的写法），不复用真实 daa 库。"""
    db = str(tmp_path / "t90_funnel.db")
    monkeypatch.setenv("DAA_SQLITE_PATH", db)
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", db)
    monkeypatch.setattr(settings.EnvConfig, "AUTH_ENABLED", True)
    # 先建全量表，否则 user_repo 的 _ensure_status_column 在空库 ALTER 会报 no such table
    from 后端_核心.存储.连接 import 初始化数据库
    初始化数据库()
    return db


def _建用户(前缀: str) -> dict:
    from repositories import user_repo
    return user_repo.创建用户(f"{前缀}_{uuid.uuid4().hex[:6]}", "x" * 32, "analyst")


def _建报表(user_id: str, 标题: str, created_at: str) -> None:
    """直接插 reports 行（要精确控制 created_at，绕开 保存报表 的 now）。"""
    import json
    from 后端_核心.存储.连接 import _get_conn
    from repositories import report_repo
    report_repo.初始化报表表()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO reports (report_id, user_id, dataset_id, title, chart_type, report_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uuid.uuid4().hex, user_id, "ds-x", 标题, "bar",
             json.dumps({}, ensure_ascii=False), created_at),
        )


def _建数据集(user_id: str, 名称: str) -> None:
    """直接插 datasets 行：漏斗只数「有几条记录」，不需要真 parquet/DataFrame。"""
    from 后端_核心.存储.连接 import _get_conn
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO datasets (dataset_id, user_id, file_name, stored_path, rows_count, "
            "cols_count, df_json, profile_json, created_at, updated_at) "
            "VALUES (?, ?, ?, '', 0, 0, '', '{}', ?, ?)",
            (uuid.uuid4().hex, user_id, 名称, now, now),
        )


def test_价值漏斗_跨天报表计回访且转化率正确(隔离库):
    from repositories import admin_repo

    u1 = _建用户("漏斗跨天")
    u2 = _建用户("漏斗同日")
    _建数据集(u1["user_id"], "a.csv")
    _建数据集(u2["user_id"], "b.csv")

    now = datetime.now(timezone.utc)
    # u1：今天 + 昨天 → 跨天 → 回访
    _建报表(u1["user_id"], "今日", now.isoformat())
    _建报表(u1["user_id"], "昨日", (now - timedelta(days=1)).isoformat())
    # u2：只有今天 → 不跨天 → 不算回访
    _建报表(u2["user_id"], "今日2", now.isoformat())

    res = admin_repo.价值漏斗()
    步 = {s["步骤"]: s["人数"] for s in res["漏斗"]}

    assert 步["注册"] >= 2
    assert 步["传数据"] >= 2
    assert 步["出报表"] >= 2
    assert 步["回访（报表跨天）"] >= 1
    # 转化率按上一步人数算（不是按注册）
    assert res["转化率"]["传数据→出报表"] == round(步["出报表"] / 步["传数据"], 4)
    assert res["转化率"]["出报表→回访"] == round(步["回访（报表跨天）"] / 步["出报表"], 4)
    # 首步占注册恒为 1.0
    assert res["漏斗"][0]["占注册"] == 1.0


def test_价值漏斗_同日报表不算回访(隔离库):
    """构造只有一个用户、且该用户报表全在同一天 → 回访必为 0。"""
    from repositories import admin_repo

    u = _建用户("漏斗单日")
    now = datetime.now(timezone.utc)
    _建报表(u["user_id"], "同日A", now.isoformat())
    _建报表(u["user_id"], "同日B", now.isoformat())

    步 = {s["步骤"]: s["人数"] for s in admin_repo.价值漏斗()["漏斗"]}
    assert 步["出报表"] == 1
    assert 步["回访（报表跨天）"] == 0


def test_价值漏斗_空库不除零(隔离库):
    """全员为 0 时转化率必须回 0.0，不能 ZeroDivisionError。"""
    from repositories import admin_repo

    res = admin_repo.价值漏斗()
    for s in res["漏斗"]:
        assert s["人数"] == 0
        assert s["占注册"] == 0.0
    for v in res["转化率"].values():
        assert v == 0.0
    assert "累计去重" in res["口径说明"]
