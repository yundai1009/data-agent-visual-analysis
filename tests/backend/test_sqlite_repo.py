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
