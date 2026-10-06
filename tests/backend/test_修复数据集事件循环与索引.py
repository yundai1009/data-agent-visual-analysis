# -*- coding: utf-8 -*-
"""阶段 54-8 · 第二块 Fix A（压测 P0）：datasets 端点 async→def + user_id 索引 + df_json 清理脚本。

走查证据（_stage52_perf/报告.md §四）：
- `api/routes/datasets.py` 的 get_dataset(L229) / get_dataset_rows(L246) /
  list_datasets(L270) 是 async def 但内部同步 SQLite/parquet → 50 并发下
  /healthz 最大 2.7s、export P95 17.8s；datasets 表 user_id 无索引单查 20ms
  （148 行占 64MB——user52a 11 行残留 25MB df_json）。
- 根因：阶段 54-5 只把 generate 改 def，datasets 系列漏了。

本文件覆盖
==========
1. 确定性子断言：datasets 系端点 + 走查扫到的其他「async def 内同步查库/读
   parquet/pandas」端点必须是「非 coroutine 函数」（FastAPI 自动丢线程池，
   事件循环不再被同步阻塞；同 generate 的验证方式）。
2. 索引：初始化数据库后 `PRAGMA index_list('datasets')` 含 user_id 索引
   （sqlite；mysql 版在 test_后端分发.py 的 information_schema 断言已覆盖）。
3. cleanup_df_json.py：dry-run 只列不删；--delete 才置空 df_json（本任务只验证
   脚本行为，不真删数据）。
"""

from __future__ import annotations

import inspect
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd

import 后端_核心.存储.sqlite_repo as sr

# ═══ 1. async def → def（事件循环不再被同步查库阻塞） ═══


def test_datasets读取端点_必须是同步def():
    """压测 P0：get_dataset / get_dataset_rows / list_datasets 改 def（与 generate 一致）。

    红：三个端点现为 async def 且内部同步 SQLite/parquet → 事件循环串行阻塞
    （压测中 /healthz P50 从 2ms 涨到 267ms、最大 2.7s）。
    """
    from api.routes.datasets import get_dataset, get_dataset_rows, list_datasets
    for fn in (get_dataset, get_dataset_rows, list_datasets):
        assert inspect.iscoroutinefunction(fn) is False, (
            f"{fn.__name__} 必须是普通 def（FastAPI 自动线程池），"
            f"否则同步 SQLite/parquet 调用会阻塞整个事件循环"
        )


def test_datasets写端点_同步查库_必须是同步def():
    """走查 sweep：merge（pandas concat）/ delete / rename / upload（parse+画像+DB）同类问题一并修。"""
    from api.routes.datasets import (
        _处理单个上传, delete_dataset, merge_datasets, rename_dataset, upload_dataset,
    )
    for fn in (upload_dataset, _处理单个上传, merge_datasets, delete_dataset, rename_dataset):
        assert inspect.iscoroutinefunction(fn) is False, (
            f"{fn.__name__} 含同步 pandas/SQLite 工作，必须为普通 def（线程池）"
        )


def test_clean_feedback_examples_同步查库_必须是同步def():
    """走查 sweep：clean（pandas 清洗+DB）、feedback（DB）、load-example（文件+pandas+DB）。"""
    from api.routes.clean import clean_dataset
    from api.routes.examples import load_example_dataset
    from api.routes.feedback import get_feedback, submit_feedback
    for fn in (clean_dataset, load_example_dataset, submit_feedback, get_feedback):
        assert inspect.iscoroutinefunction(fn) is False, (
            f"{fn.__name__} 含同步查库工作，必须为普通 def（线程池）"
        )


# ═══ 2. datasets 表 user_id 索引（sqlite） ═══


@pytest.fixture
def 临时库(tmp_path, monkeypatch):
    """临时 SQLite 库（隔离模式：tmp_path + DAA_SQLITE_PATH）。"""
    路径 = tmp_path / "idx.db"
    monkeypatch.setenv("DAA_SQLITE_PATH", str(路径))
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(路径), raising=False)
    sr.初始化数据库()
    return 路径


def test_初始化数据库_datasets含user_id索引(临时库):
    """压测 P0：`WHERE user_id=?` 单查 20ms（全表 b-tree 扫描）→ 建索引后 <1ms。

    红：初始化数据库未给 datasets.user_id 建索引，PRAGMA 里查不到。
    """
    import sqlite3
    conn = sqlite3.connect(str(临时库))
    try:
        indexes = {r[1] for r in conn.execute("PRAGMA index_list('datasets')").fetchall()}
    finally:
        conn.close()
    assert "idx_datasets_user_created" in indexes, (
        f"datasets 缺 user_id 索引，INDEX 列表：{sorted(indexes)}"
    )


def test_初始化数据库_幂等_重复建索引不报错(临时库):
    """回归：初始化数据库幂等——重复执行 CREATE INDEX IF NOT EXISTS 安全。"""
    sr.初始化数据库()
    sr.初始化数据库()


# ═══ 3. cleanup_df_json.py：dry-run 只列不删，--delete 才置空 ═══


@pytest.fixture
def 带残留库(tmp_path, monkeypatch):
    """数据形态：A 有 parquet（data_path 存在）+ 残留 df_json；B 有 parquet 但 df_json 为空；C 无 parquet。"""
    路径 = tmp_path / "cleanup.db"
    monkeypatch.setenv("DAA_SQLITE_PATH", str(路径))
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(路径), raising=False)
    帕 = tmp_path / "pq"
    帕.mkdir()
    monkeypatch.setattr(sr, "_PARQUET_DIR", 帕)
    sr.初始化数据库()

    df = pd.DataFrame({"地区": ["华东", "华南"], "销售额": [100, 200]})
    now = sr._now_iso()
    (帕 / "a.parquet").write_bytes(b"not-a-real-parquet")  # 只看存在性，内容无关
    with sr._write_lock, sr._get_conn() as conn:
        for ds_id, df_json, data_path in (
            ("a", sr._df_to_json(df), str(帕 / "a.parquet")),   # 残留 df_json + parquet 存在 → 候选
            ("b", "", str(帕 / "a.parquet")),                   # df_json 为空 → 非候选
            ("c", sr._df_to_json(df), ""),                      # 无 parquet → 非候选
        ):
            conn.execute(
                "INSERT INTO datasets (dataset_id, user_id, file_name, stored_path,"
                " rows_count, cols_count, df_json, profile_json, created_at, updated_at, data_path)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ds_id, "u1", f"{ds_id}.csv", "", 2, 2, df_json, "{}", now, now, data_path),
            )
    return 路径


def test_cleanup_df_json_dryrun_只列不删(带残留库):
    """dry-run：只报告 df_json 非空且 data_path 存在 parquet 的数据集（a），不修改数据。"""
    from scripts import cleanup_df_json as cj
    结果 = cj.扫描()
    ids = [r["dataset_id"] for r in 结果]
    assert ids == ["a"], f"候选应只有 a（df_json 残留 + parquet 存在），实际 {ids}"
    # dry-run 默认不删：库里 df_json 原样保留（records JSON 以 [ 开头）
    with sr._get_conn() as conn:
        df_json = conn.execute(
            "SELECT df_json FROM datasets WHERE dataset_id = ?", ("a",)
        ).fetchone()[0]
    assert df_json and "地区" in df_json, "dry-run 不得置空 df_json"


def test_cleanup_df_json_delete_置空df_json不动parquet(带残留库):
    """--delete：仅把候选行的 df_json 置空，data_path/parquet 不动（数据本体仍可读）。"""
    from scripts import cleanup_df_json as cj
    删除数 = cj.删除("a")
    assert 删除数 == 1
    with sr._get_conn() as conn:
        row = conn.execute(
            "SELECT df_json, data_path FROM datasets WHERE dataset_id = ?", ("a",)
        ).fetchone()
    assert row["df_json"] == "", "delete 后 df_json 应为空"
    assert row["data_path"], "delete 不得清空 data_path（parquet 本体保留）"