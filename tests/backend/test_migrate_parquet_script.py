# -*- coding: utf-8 -*-
"""阶段 54 · migrate_datasets_to_parquet 脚本：per-row 失败降级与宽松兜底测试。

背景：真实生产库 145 条数据里有 2 条（未删除清洗数据.xlsx）的 df_json 含
object 列（82 个数字 + 2 个全角逗号字符串 '2，4'），pyarrow 严格类型检查
拒绝 object→int64 转换，旧逻辑 to_parquet 抛异常导致整轮迁移中止。

修复目标：
1. object 列先尝试 astype(str) 宽松兜底（脏数据列转字符串可写 parquet）
2. 单行失败不中止整表（记录失败列表继续迁移其余行）
3. 失败列表可读（dataset_id + 原因），供人工修复
"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import pytest

import 后端_核心.存储.sqlite_repo as sr


@pytest.fixture
def 临时库(tmp_path, monkeypatch):
    """建临时 SQLite 库：1 条 normal + 1 条混合 object 列（污染 dtype）。

    手工插入旧形态数据（df_json 有值）——Task 1 后保存走 parquet，这里
    模拟迁移脚本要处理的「存量 df_json 数据」。
    """
    路径 = tmp_path / "mig.db"
    monkeypatch.setenv("DAA_SQLITE_PATH", str(路径))
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(路径), raising=False)
    monkeypatch.setattr(sr, "_PARQUET_DIR", tmp_path / "pq")
    sr.初始化数据库()

    df_normal = pd.DataFrame({"月份": pd.to_datetime(["2026-01-01"]), "销售额": [100]})

    # 混合列：82 个数字 + 2 个全角逗号字符串 → df_json 读回后推断为 object
    df_dirty = pd.DataFrame({
        "问卷序号": list(range(1, 85)),
        "1.9.当您遇到麻烦的时候，您的邻居、社区工作人员能帮上忙吗？": ["1"] * 82 + ["2，4", "2，4"],
    })

    # 旧形态数据：df_json 有值、data_path 为空（用 _df_to_json 构造）
    now = sr._now_iso()
    with sr._write_lock, sr._get_conn() as conn:
        for ds_id, 文件名, df in (("ok1", "normal.csv", df_normal),
                                  ("dirty1", "dirty.xlsx", df_dirty)):
            conn.execute(
                "INSERT INTO datasets (dataset_id, user_id, file_name, stored_path,"
                " rows_count, cols_count, df_json, profile_json, created_at, updated_at, data_path)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (ds_id, "u1", 文件名, "", int(len(df)), int(len(df.columns)),
                 sr._df_to_json(df), "{}", now, now, None),
            )
    return 路径


def test_混合object列_宽松兜底可迁移(临时库, tmp_path):
    """dirty1 应通过 astype(str) 兜底成功迁移，全表成功，失败列表为空。"""
    from scripts import migrate_datasets_to_parquet as m
    结果 = m.迁移()
    assert 结果["迁移"] == 2, 结果
    assert 结果["失败"] == [], f"应有 0 失败，实得 {结果['失败']}"
    out = sr.读取数据集("u1", "dirty1")
    assert out["数据"].shape == (84, 2)
    col = out["数据"].columns[-1]
    assert all(isinstance(v, str) for v in out["数据"][col]), "兜底后应为字符串"
    assert "2，4" in set(out["数据"][col])
    # 正常行：df_json 源头序列化时 datetime 已变 ISO 字符串（df_json 固有 dtype
    # 损失，Task 1 引入 parquet 的动机），迁移后值一致即可，不苛求 datetime dtype
    ok = sr.读取数据集("u1", "ok1")
    assert ok["数据"].shape == (1, 2)
    assert ok["数据"]["销售额"].iloc[0] == 100
    assert str(ok["数据"]["月份"].iloc[0]).startswith("2026-01-01")


def test_单行失败不中止整表_记录失败清单(临时库, tmp_path, monkeypatch):
    """人为让 dirty1 连兜底都失败：应记录失败并继续迁移 ok1，脚本正常结束。"""
    from scripts import migrate_datasets_to_parquet as m

    原始 = sr._df_from_json

    def 只坏dirty行(df_json: str):
        if "2，4" in df_json:
            raise ValueError("人为注入的解析错误")
        return 原始(df_json)

    monkeypatch.setattr(sr, "_df_from_json", 只坏dirty行)

    结果 = m.迁移()
    assert 结果["迁移"] == 1, 结果          # ok1 成功
    assert len(结果["失败"]) == 1, 结果      # dirty1 被记录
    assert 结果["失败"][0]["dataset_id"] == "dirty1"
    assert "人为注入" in 结果["失败"][0]["原因"]
    # ok1 的 parquet 文件存在，dirty1 的没有
    assert (tmp_path / "pq" / "ok1.parquet").exists()
    assert not (tmp_path / "pq" / "dirty1.parquet").exists()