"""SQLite 仓储层单元测试：不依赖网络、不依赖 LLM、不依赖真实上传文件。

覆盖目标
========
- ``初始化数据库`` 幂等
- ``保存数据集`` / ``读取数据集`` round-trip：DataFrame 和画像都能完整还原
- ``数据集是否存在`` / ``删除数据集`` 行为正确
- ``列出数据集`` 顺序与限流
- ``数据集仓储`` 类的依赖注入接口
- 重启模拟：保存 → 释放仓储对象 → 新仓储实例 → 仍能读取
- 字段白名单：DataFrame 含中文/日期/缺失值 仍能 round-trip

设计原则
========
- 测试用临时 SQLite 文件（``tmp_path`` fixture），不污染项目 data 目录
- 测试结束后清理临时文件
- 每个测试用例独立 db 文件，避免相互干扰
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.存储 import sqlite_repo


# ============================================================================
# fixture：每次测试都用独立的临时 SQLite 文件
# ============================================================================

@pytest.fixture
def 临时db(tmp_path, monkeypatch):
    """让仓储使用临时目录下的 SQLite 文件，测完自动清理。"""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DAA_SQLITE_PATH", str(db_path))
    # settings.py 在 import 时已读环境变量，需手动刷新 EnvConfig.SQLITE_PATH
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(db_path), raising=False)
    # 阶段 54 Fix 5：把 _PARQUET_DIR 一并隔离到临时目录——否则既有测试（未单独打
    # _PARQUET_DIR 补丁）保存数据集时会把 parquet 写进项目 data/parquet/ 造成残留。
    monkeypatch.setattr(sqlite_repo, "_PARQUET_DIR", tmp_path / "parquet")
    # 初始化 schema
    sqlite_repo.初始化数据库()
    yield db_path
    # tmp_path 由 pytest 自动清理


@pytest.fixture
def 样本df() -> pd.DataFrame:
    return pd.DataFrame({
        "月份": pd.date_range("2026-01-01", periods=4, freq="ME"),
        "地区": ["华东", "华南", "华东", "华北"],
        "销售额": [100, 150, 130, 180],
        "订单数": [10, 15, 12, 20],
    })


@pytest.fixture
def 样本画像() -> Dict[str, Any]:
    return {
        "行数": 4,
        "列数": 4,
        "字段列表": ["月份", "地区", "销售额", "订单数"],
        "字段类型": {"月份": "datetime64[ns]", "地区": "object",
                  "销售额": "int64", "订单数": "int64"},
        "数值字段": ["销售额", "订单数"],
        "日期字段": ["月份"],
        "分类字段": ["地区"],
        "数据质量": {"等级": "良好"},
    }


# ============================================================================
# 1. 初始化与幂等性
# ============================================================================

def test_初始化数据库_幂等(临时db):
    # 重复调用不应抛异常
    sqlite_repo.初始化数据库()
    sqlite_repo.初始化数据库()
    assert 临时db.exists()


# ============================================================================
# 2. 保存 + 读取 round-trip
# ============================================================================

def test_保存并读取数据集_round_trip(临时db, 样本df, 样本画像):
    sqlite_repo.保存数据集(
        user_id="u_test",
        dataset_id="abc123",
        文件名="test.csv",
        存储路径="/tmp/test_abc123.csv",
        df=样本df,
        画像=样本画像,
    )
    out = sqlite_repo.读取数据集("u_test", "abc123")
    assert out is not None
    assert out["数据集ID"] == "abc123"
    assert out["文件名"] == "test.csv"
    assert out["路径"] == "/tmp/test_abc123.csv"
    assert out["行数"] == 4
    assert out["列数"] == 4
    # DataFrame round-trip
    df_back = out["数据"]
    assert list(df_back.columns) == ["月份", "地区", "销售额", "订单数"]
    assert len(df_back) == 4
    assert df_back["地区"].tolist() == ["华东", "华南", "华东", "华北"]
    assert df_back["销售额"].tolist() == [100, 150, 130, 180]
    # 画像 round-trip
    画像_back = out["数据画像"]
    assert 画像_back["字段列表"] == ["月份", "地区", "销售额", "订单数"]
    assert 画像_back["数值字段"] == ["销售额", "订单数"]
    assert 画像_back["数据质量"]["等级"] == "良好"


def test_读取不存在返回_None(临时db):
    assert sqlite_repo.读取数据集("u_test", "不存在的ID") is None


# ============================================================================
# 3. 数据集是否存在
# ============================================================================

def test_数据集是否存在(临时db, 样本df, 样本画像):
    assert sqlite_repo.数据集是否存在("u_test", "xyz789") is False
    sqlite_repo.保存数据集(
        user_id="u_test",
        dataset_id="xyz789", 文件名="x.csv", 存储路径="/tmp/x.csv",
        df=样本df, 画像=样本画像,
    )
    assert sqlite_repo.数据集是否存在("u_test", "xyz789") is True


# ============================================================================
# 4. 删除数据集
# ============================================================================

def test_删除数据集(临时db, 样本df, 样本画像):
    sqlite_repo.保存数据集(
        user_id="u_test",
        dataset_id="del1", 文件名="d.csv", 存储路径="/tmp/d.csv",
        df=样本df, 画像=样本画像,
    )
    assert sqlite_repo.删除数据集("u_test", "del1") is True
    assert sqlite_repo.读取数据集("u_test", "del1") is None
    # 再删一次应返回 False
    assert sqlite_repo.删除数据集("u_test", "del1") is False
    # 删不存在的也应返回 False
    assert sqlite_repo.删除数据集("u_test", "完全不存在的ID") is False


# ============================================================================
# 5. 列出数据集：顺序与限流
# ============================================================================

def test_列出数据集按创建时间倒序(临时db, 样本df, 样本画像):
    # 顺序保存 3 个数据集
    for i in range(3):
        sqlite_repo.保存数据集(
        user_id="u_test",
        dataset_id=f"list_{i}", 文件名=f"f{i}.csv", 存储路径=f"/tmp/f{i}.csv",
            df=样本df, 画像=样本画像,
        )
    items = sqlite_repo.列出数据集("u_test", limit=10)
    assert len(items) == 3
    # 不强求严格顺序（同秒内 created_at 可能相同），但所有 id 都应在
    ids = {item["数据集ID"] for item in items}
    assert ids == {"list_0", "list_1", "list_2"}


def test_列出数据集限流(临时db, 样本df, 样本画像):
    for i in range(5):
        sqlite_repo.保存数据集(
        user_id="u_test",
        dataset_id=f"cap_{i}", 文件名=f"c{i}.csv", 存储路径=f"/tmp/c{i}.csv",
            df=样本df, 画像=样本画像,
        )
    items = sqlite_repo.列出数据集("u_test", limit=3)
    assert len(items) == 3


# ============================================================================
# 6. 数据集仓储类（依赖注入接口）
# ============================================================================

def test_仓储类完整接口(临时db, 样本df, 样本画像):
    repo = sqlite_repo.数据集仓储()
    repo.保存("u_test", "repo1", "r.csv", "/tmp/r.csv", 样本df, 样本画像)
    assert repo.存在("u_test", "repo1") is True
    item = repo.读取("u_test", "repo1")
    assert item is not None
    assert item["文件名"] == "r.csv"
    lst = repo.列表("u_test", limit=10)
    assert any(i["数据集ID"] == "repo1" for i in lst)
    assert repo.删除("u_test", "repo1") is True
    assert repo.存在("u_test", "repo1") is False


# ============================================================================
# 7. 重启模拟：仓储对象释放后新实例仍能读取
# ============================================================================

def test_重启后仍能读取(临时db, 样本df, 样本画像):
    """模拟进程重启：仓储对象释放 → 新仓储实例 → 数据仍在。"""
    # 第一次"进程"
    repo1 = sqlite_repo.数据集仓储()
    repo1.保存("u_test", "persist1", "p.csv", "/tmp/p.csv", 样本df, 样本画像)
    del repo1

    # 第二次"进程"：新仓储实例，不重新创建 schema（IF NOT EXISTS 安全）
    repo2 = sqlite_repo.数据集仓储()
    item = repo2.读取("u_test", "persist1")
    assert item is not None
    assert item["文件名"] == "p.csv"
    df_back = item["数据"]
    assert df_back["地区"].tolist() == ["华东", "华南", "华东", "华北"]


# ============================================================================
# 8. DataFrame 含中文/缺失值/不同 dtype 仍能 round-trip
# ============================================================================

def test_含缺失值和中文_round_trip(临时db):
    df = pd.DataFrame({
        "产品名": ["苹果", "香蕉", None, "梨"],
        "价格": [5.5, 3.2, 4.0, None],
        "库存": [100, 50, 80, 0],
    })
    画像 = {
        "行数": 4, "列数": 3,
        "字段列表": ["产品名", "价格", "库存"],
        "数值字段": ["价格", "库存"],
        "分类字段": ["产品名"],
    }
    sqlite_repo.保存数据集(
        user_id="u_test",
        dataset_id="mixed1", 文件名="m.csv", 存储路径="/tmp/m.csv",
        df=df, 画像=画像,
    )
    out = sqlite_repo.读取数据集("u_test", "mixed1")
    assert out is not None
    df_back = out["数据"]
    # 中文字段保留
    assert "产品名" in df_back.columns
    # 缺失值保留（pandas 会用 NaN 表示 None）
    assert df_back["产品名"].isna().sum() == 1
    assert df_back["价格"].isna().sum() == 1
    # 库存的 0 保留
    assert (df_back["库存"] == 0).sum() == 1


# ============================================================================
# 9. upsert：相同 dataset_id 保存两次应是覆盖而不是报错
# ============================================================================

def test_upsert相同ID覆盖(临时db):
    df1 = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    df2 = pd.DataFrame({"a": [10, 20, 30], "b": ["p", "q", "r"]})
    画像1 = {"行数": 2, "列数": 2, "字段列表": ["a", "b"]}
    画像2 = {"行数": 3, "列数": 2, "字段列表": ["a", "b"]}

    sqlite_repo.保存数据集("u_test", "up1", "f1.csv", "/tmp/f1.csv", df1, 画像1)
    sqlite_repo.保存数据集("u_test", "up1", "f2.csv", "/tmp/f2.csv", df2, 画像2)

    out = sqlite_repo.读取数据集("u_test", "up1")
    assert out is not None
    assert out["文件名"] == "f2.csv"
    assert out["行数"] == 3
    assert out["数据"]["a"].tolist() == [10, 20, 30]


# ============================================================================
# 阶段 54 · 数据本体出库：parquet 替代 df_json
# ============================================================================

def test_保存数据集_写parquet文件而非df_json(临时db, 样本df, 样本画像, monkeypatch, tmp_path):
    import 后端_核心.存储.sqlite_repo as sr
    隔离目录 = tmp_path / "parquet_out"
    monkeypatch.setattr(sr, "_PARQUET_DIR", 隔离目录)

    sr.保存数据集(
        user_id="u_test", dataset_id="pq1", 文件名="t.csv", 存储路径="/tmp/t.csv",
        df=样本df, 画像=样本画像,
    )

    pq = 隔离目录 / "pq1.parquet"
    assert pq.exists(), "应生成 parquet 文件"
    assert pq.stat().st_size > 0
    with sr._get_conn() as conn:
        row = conn.execute("SELECT df_json, data_path FROM datasets WHERE dataset_id = ?",
                           ("pq1",)).fetchone()
    assert row["df_json"] == "", "df_json 应为空串（数据本体已出库）"
    assert row["data_path"] == str(pq)


def test_parquet_保留dtype_日期列不被读成字符串(临时db, 样本df, 样本画像, monkeypatch, tmp_path):
    import 后端_核心.存储.sqlite_repo as sr
    monkeypatch.setattr(sr, "_PARQUET_DIR", tmp_path / "pq")
    sr.保存数据集(user_id="u", dataset_id="pq2", 文件名="t.csv", 存储路径="/tmp/t.csv",
                 df=样本df, 画像=样本画像)
    df_back = sr.读取数据集("u", "pq2")["数据"]
    assert str(df_back["月份"].dtype).startswith("datetime64"), f"日期列 dtype 丢失：{df_back['月份'].dtype}"
    assert df_back["销售额"].dtype == "int64"


def test_读取数据集_优先parquet_回退df_json(临时db, 样本df, 样本画像, monkeypatch, tmp_path):
    import 后端_核心.存储.sqlite_repo as sr
    monkeypatch.setattr(sr, "_PARQUET_DIR", tmp_path / "pq")
    sr.保存数据集(user_id="u", dataset_id="pq3", 文件名="t.csv", 存储路径="/tmp/t.csv",
                 df=样本df, 画像=样本画像)
    out = sr.读取数据集("u", "pq3")
    assert out["数据路径"].endswith("pq3.parquet")
    assert out["数据"].shape == (4, 4)

    # 手工构造一条只有 df_json 的旧数据 → 必须能回退读出
    with sr._get_conn() as conn:
        conn.execute(
            "INSERT INTO datasets (dataset_id, user_id, file_name, stored_path, rows_count,"
            " cols_count, df_json, profile_json, created_at, updated_at, data_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("legacy1", "u", "old.csv", "/tmp/old.csv", 2, 2,
             sr._df_to_json(样本df), "{}", "2026-01-01", "2026-01-01", None),
        )
    old = sr.读取数据集("u", "legacy1")
    assert old["数据"].shape == (4, 4), "旧数据应回退 df_json 读出"
    assert old["数据路径"] == ""


def test_删除数据集_同时清理parquet文件(临时db, 样本df, 样本画像, monkeypatch, tmp_path):
    import 后端_核心.存储.sqlite_repo as sr
    monkeypatch.setattr(sr, "_PARQUET_DIR", tmp_path / "pq")
    sr.保存数据集(user_id="u", dataset_id="pq4", 文件名="t.csv", 存储路径="",
                 df=样本df, 画像=样本画像)
    pq = tmp_path / "pq" / "pq4.parquet"
    assert pq.exists()
    assert sr.删除数据集("u", "pq4") is True
    assert not pq.exists(), "parquet 文件应随数据集一起删除"


# ============================================================================
# 阶段 54 · Fix 修复（审查发现）
# ============================================================================

def test_临时db_fixture_隔离parquet目录(临时db):
    """Fix 5：既有测试未打 _PARQUET_DIR 补丁，单文件跑完会在项目 data/parquet/ 残留。

    要求：把 _PARQUET_DIR 补丁下沉到 临时db fixture，一处修复全部测试。
    """
    import 后端_核心.存储.sqlite_repo as sr
    assert str(sr._PARQUET_DIR).startswith(str(临时db.parent)), (
        f"_PARQUET_DIR 应被 临时db fixture 隔离到临时目录，实际指向 {sr._PARQUET_DIR}"
    )


def test_读取数据集_parquet缺失且df_json空_返回None(临时db, monkeypatch, tmp_path):
    """Fix 1：data_path 指向不存在文件且 df_json 为空 → 返回 None，不抛异常（接口 500）。"""
    import 后端_核心.存储.sqlite_repo as sr
    missing = tmp_path / "不存在.parquet"
    with sr._get_conn() as conn:
        conn.execute(
            "INSERT INTO datasets (dataset_id, user_id, file_name, stored_path, rows_count,"
            " cols_count, df_json, profile_json, created_at, updated_at, data_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("lost1", "u", "lost.csv", "/tmp/lost.csv", 2, 2,
             "", "{}", "2026-01-01", "2026-01-01", str(missing)),
        )
    result = sr.读取数据集("u", "lost1")
    assert result is None, "parquet 缺失且 df_json 为空时应返回 None，不抛异常（接口 500）"


def test_读取数据集_parquet损坏_回退df_json(临时db, 样本df, monkeypatch, tmp_path):
    """Fix 1：parquet 文件存在但损坏（解析异常）→ 回退读 df_json，数据仍可读。"""
    import 后端_核心.存储.sqlite_repo as sr
    pq = tmp_path / "坏.parquet"
    pq.write_bytes(b"not a parquet file")
    with sr._get_conn() as conn:
        conn.execute(
            "INSERT INTO datasets (dataset_id, user_id, file_name, stored_path, rows_count,"
            " cols_count, df_json, profile_json, created_at, updated_at, data_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("corrupt1", "u", "c.csv", "/tmp/c.csv", 4, 4,
             sr._df_to_json(样本df), "{}", "2026-01-01", "2026-01-01", str(pq)),
        )
    out = sr.读取数据集("u", "corrupt1")
    assert out is not None
    assert out["数据"].shape == (4, 4), "parquet 损坏时应回退 df_json 读出"


def test_保存数据集_先写临时文件再原子替换(临时db, 样本df, 样本画像, monkeypatch):
    """Fix 2：保存 parquet 应写临时文件后 os.replace 原子替换，不直接写目标文件。"""
    import 后端_核心.存储.sqlite_repo as sr
    import pandas as pd
    观测: List[Path] = []
    real_to_parquet = pd.DataFrame.to_parquet

    def spy(self, path, **kwargs):
        观测.append(Path(path))
        return real_to_parquet(self, path, **kwargs)

    monkeypatch.setattr(pd.DataFrame, "to_parquet", spy)
    sr.保存数据集(user_id="u", dataset_id="atomic1", 文件名="a.csv", 存储路径="",
                 df=样本df, 画像=样本画像)
    assert 观测, "保存时应调用 to_parquet"
    首写路径 = 观测[0]
    assert 首写路径.name == ".atomic1.parquet.tmp", f"应先写临时文件再原子替换，实际直接写入 {首写路径.name}"
    目标 = sr._parquet路径("atomic1")
    assert 目标.exists(), "最终 parquet 文件应存在"
    assert not 首写路径.exists(), "临时文件应已被 os.replace 替换，不残留"


def test_parquet路径_非法dataset_id_抛ValueError(临时db):
    """Fix 3：_parquet路径 拼路径前必须净化 dataset_id，防路径穿越/任意文件删除。"""
    import 后端_核心.存储.sqlite_repo as sr
    for 坏id in ("../evil", "..", ".", "a/b", "a\\b", "a b", "x.y"):
        with pytest.raises(ValueError):
            sr._parquet路径(坏id)
    # 合法 id 不受影响
    assert sr._parquet路径("pq-1_2").name == "pq-1_2.parquet"
    assert sr._parquet路径("AbC123").name == "AbC123.parquet"


def test_保存数据集_重复列名_降级存df_json(临时db, monkeypatch, tmp_path):
    """Fix 4：pyarrow 不可序列化（重复列名）时保存不硬失败，降级走 df_json 且可读。"""
    import 后端_核心.存储.sqlite_repo as sr
    df = pd.DataFrame([[1, 2], [3, 4]], columns=["a", "a"])  # 重复列名，to_parquet 必抛
    画像 = {"行数": 2, "列数": 2, "字段列表": ["a", "a"]}
    sr.保存数据集(user_id="u", dataset_id="dup1", 文件名="dup.csv", 存储路径="",
                 df=df, 画像=画像)  # 不应抛异常
    with sr._get_conn() as conn:
        row = conn.execute("SELECT df_json, data_path FROM datasets WHERE dataset_id = 'dup1'").fetchone()
    assert row["data_path"] == "", "parquet 无法序列化时应回退 df_json（data_path 置空）"
    assert row["df_json"], "降级后该行应仍存 JSON（可读）"
    out = sr.读取数据集("u", "dup1")
    assert out["数据"].values.tolist() == [[1, 2], [3, 4]], "降级的 JSON 应能读回"


def test_迁移脚本_dry_run_clear_df_json_只报告不清空(临时db, 样本df, monkeypatch, tmp_path, capsys):
    """Fix 6：--dry-run --clear-df-json 应提示将清空多少行，且不真正清空。"""
    import 后端_核心.存储.sqlite_repo as sr
    import scripts.migrate_datasets_to_parquet as mig
    monkeypatch.setattr(sr, "_PARQUET_DIR", tmp_path / "pq")
    with sr._get_conn() as conn:
        conn.execute(
            "INSERT INTO datasets (dataset_id, user_id, file_name, stored_path, rows_count,"
            " cols_count, df_json, profile_json, created_at, updated_at, data_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("mig1", "u", "m.csv", "/tmp/m.csv", 4, 4,
             sr._df_to_json(样本df), "{}", "2026-01-01", "2026-01-01", None),
        )
    monkeypatch.setattr(sys, "argv", ["migrate_datasets_to_parquet.py", "--dry-run", "--clear-df-json"])
    assert mig.main() == 0
    out = capsys.readouterr().out
    assert "将清空" in out, f"dry-run 应提示将清空的行数：{out}"
    assert "1 行" in out, f"dry-run 应报出会清空的行数：{out}"
    with sr._get_conn() as conn:
        row = conn.execute("SELECT df_json FROM datasets WHERE dataset_id='mig1'").fetchone()
    assert row["df_json"] != "", "dry-run 不应真正清空 df_json"


def test_迁移脚本_clear_df_json_全部成功后清空(临时db, 样本df, monkeypatch, tmp_path, capsys):
    """Fix 6：迁移全部成功后 --clear-df-json 把 df_json 置空（释放库空间）。"""
    import 后端_核心.存储.sqlite_repo as sr
    import scripts.migrate_datasets_to_parquet as mig
    monkeypatch.setattr(sr, "_PARQUET_DIR", tmp_path / "pq")
    with sr._get_conn() as conn:
        conn.execute(
            "INSERT INTO datasets (dataset_id, user_id, file_name, stored_path, rows_count,"
            " cols_count, df_json, profile_json, created_at, updated_at, data_path)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("mig1", "u", "m.csv", "/tmp/m.csv", 4, 4,
             sr._df_to_json(样本df), "{}", "2026-01-01", "2026-01-01", None),
        )
    monkeypatch.setattr(sys, "argv", ["migrate_datasets_to_parquet.py", "--clear-df-json"])
    assert mig.main() == 0
    capsys.readouterr()
    with sr._get_conn() as conn:
        row = conn.execute("SELECT df_json, data_path FROM datasets WHERE dataset_id='mig1'").fetchone()
    assert row["data_path"], "迁移后应写入 parquet 路径"
    assert (tmp_path / "pq" / "mig1.parquet").exists(), "迁移应写出 parquet 文件"
    assert row["df_json"] == "", "迁移全部成功后 --clear-df-json 应清空 df_json"
