# -*- coding: utf-8 -*-
"""预测数据采集仓储单元测试（event_repo.py）。

覆盖目标
========
- 初始化事件表幂等
- 注册/生成/拦截/支付事件写入正确
- 导出 CSV：中文表头、时间格式 YYYY-MM-DD HH:MM:SS、脱敏 user_id 格式
- event_payment 幂等（重复 order_id 忽略）

设计原则
========
- 临时 SQLite 文件（tmp_path fixture），不污染 data 目录
- conftest 已设 AUTH_ENABLED/JWT_SECRET_KEY/SEED_ADMIN_PASSWORD
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

import pytest

# 项目根目录加 path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.存储.sqlite_repo import _resolve_db_path
import repositories.event_repo as event_repo


# ============================================================================
# fixture：强制使用临时数据库
# ============================================================================

@pytest.fixture(autouse=True)
def _tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """把 SQLite 路径临时指向 tmp_path，防止污染项目数据库。"""
    fake_db = str(tmp_path / "test_events.db")
    monkeypatch.setattr("后端_核心.存储.sqlite_repo._resolve_db_path", lambda: Path(fake_db))
    event_repo.初始化事件表()
    yield
    Path(fake_db).unlink(missing_ok=True)


# ============================================================================
# 1. 初始化幂等
# ============================================================================

def test_初始化幂等():
    """重复调用不应抛异常。"""
    event_repo.初始化事件表()
    event_repo.初始化事件表()


# ============================================================================
# 2. 注册事件
# ============================================================================

def test_记录注册事件():
    event_repo.记录注册事件(
        "u_0000000000000001", channel="应用商店", device_type="苹果", city_tier="1",
    )
    from 后端_核心.存储.sqlite_repo import _get_conn
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM event_register").fetchall()
    assert len(rows) == 1
    assert rows[0]["user_id"] == "u_0000000000000001"
    assert rows[0]["channel"] == "应用商店"
    assert rows[0]["device_type"] == "苹果"


# ============================================================================
# 3. 生成事件
# ============================================================================

def test_记录生成事件():
    event_repo.记录生成事件("u_0000000000000002", image_count=1, analysis_type="折线图")
    from 后端_核心.存储.sqlite_repo import _get_conn
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM event_gen").fetchall()
    assert len(rows) == 1
    assert rows[0]["analysis_type"] == "折线图"


# ============================================================================
# 4. 拦截事件
# ============================================================================

def test_记录拦截事件():
    event_repo.记录拦截事件("u_0000000000000003", action_after="重试", shown_price=29.9)
    from 后端_核心.存储.sqlite_repo import _get_conn
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM event_paywall").fetchall()
    assert len(rows) == 1
    assert rows[0]["action_after"] == "重试"
    assert rows[0]["shown_price"] == 29.9


# ============================================================================
# 5. 支付事件（幂等）
# ============================================================================

def test_记录支付事件幂等():
    event_repo.记录支付事件("o_001", "u_0000000000000004", "月卡", 29.9)
    event_repo.记录支付事件("o_001", "u_0000000000000004", "月卡", 29.9)  # 重复
    from 后端_核心.存储.sqlite_repo import _get_conn
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM event_payment").fetchall()
    assert len(rows) == 1  # 幂等：重复 order_id 不插入


# ============================================================================
# 6. 导出 CSV 格式
# ============================================================================

def test_导出CSV格式(tmp_path: Path):
    event_repo.记录注册事件("u_aabbccdd11223344", channel="搜索引擎", device_type="安卓")
    out_path = event_repo.导出事件CSV("event_register", tmp_path / "export")
    assert out_path.exists()

    with open(out_path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    # 表头为中文（与预测系统 schema 对齐）
    assert header == ["用户编号", "注册时间", "来源渠道", "设备类型", "城市线级", "活动来源"]
    assert len(rows) == 1
    assert rows[0][0] == "u_aabbccdd11223344"  # user_id 格式
    # 时间格式：YYYY-MM-DD HH:MM:SS（不带时区后缀）
    import re
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", rows[0][1])
