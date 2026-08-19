"""阶段 30 · 同比环比测试：对比列计算 + 意图识别 + API 透传，不依赖网络与 LLM key。

覆盖目标
========
- ``_生成对比数据``：环比差值/环比率、同比（隔 12 期）、数据不足跳过、非法值跳过
- ``生成报表数据``：日期 X 轴 + 对比 → 报表数据含对比列；非日期 X 轴不加
- 规则意图："按月环比" → 对比=环比
- API：generate 带 对比 → 报表含对比列；replay 保留对比
"""



from __future__ import annotations


# --- _did helper ---

def _did(j):
    """从 upload 响应中提取第一个成功的数据集ID（兼容旧单文件格式+新批量格式）。"""
    if "上传成功" in j:
        return j["上传成功"][0]["数据集ID"]
    return j["数据集ID"]

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from 后端_核心.上传报表生成器 import _生成对比数据, 生成报表数据, _意图驱动配置

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("compare_test")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    初始化数据库()

    from services import email_service

    def _fake_send(email: str, code: str) -> bool:
        _SENT_CODES[email] = code
        return True

    _orig_send = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake_send
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            yield c
    finally:
        email_service.发送验证码邮件 = _orig_send


def _register(client, username) -> str:
    email = f"{username}@test.com"
    assert client.post("/auth/send-code", json={"email": email}).status_code == 200
    code = _SENT_CODES.get(email)
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _upload(client, token) -> str:
    """上传 14 个月的月度销售额数据（同比需至少 13 期）。"""
    lines = ["月份,销售额"]
    for i in range(1, 15):
        lines.append(f"2025-{i:02d},{1000 + i * 100}")
    r = client.post(
        "/datasets/upload",
        files={"file": ("sales.csv", "\n".join(lines).encode(), "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    return _did(r.json())


# ============================================================================
# 1. _生成对比数据
# ============================================================================

class Test生成对比数据:
    def test_环比列(self):
        df = pd.DataFrame({"月份": ["1月", "2月", "3月"], "销售额": [100, 150, 120]})
        out = _生成对比数据(df, "环比", "月份")
        assert "销售额环比" in out.columns
        assert "销售额环比率" in out.columns
        assert out["销售额环比"].tolist()[0] != out["销售额环比"].tolist()[0]  # NaN（shift 首行）
        assert out["销售额环比"].tolist()[1:] == [50, -30]
        assert pd.isna(out["销售额环比率"].iloc[0])
        assert out["销售额环比率"].iloc[1] == 50.0

    def test_同比隔12期(self):
        df = pd.DataFrame({"月份": [f"m{i}" for i in range(14)], "销售额": [100] * 2 + [200] * 12})
        out = _生成对比数据(df, "同比", "月份")
        assert "销售额同比" in out.columns
        # 第 13 期（index 12）与第 1 期比：200 - 100 = 100
        assert out["销售额同比"].iloc[12] == 100
        assert out["销售额同比"].iloc[0] is None or pd.isna(out["销售额同比"].iloc[0])

    def test_数据不足跳过(self):
        df = pd.DataFrame({"月份": ["1月"], "销售额": [100]})
        out = _生成对比数据(df, "环比", "月份")
        assert "销售额环比" not in out.columns

    def test_非法对比值跳过(self):
        df = pd.DataFrame({"月份": ["1月", "2月"], "销售额": [100, 150]})
        out = _生成对比数据(df, "季度", "月份")
        assert "销售额环比" not in out.columns


# ============================================================================
# 2. 生成报表数据 集成
# ============================================================================

class Test生成报表数据对比:
    def test_日期X轴加环比列(self):
        df = pd.DataFrame({
            "月份": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"]),
            "销售额": [100, 150, 120],
        })
        report = 生成报表数据(
            df, "按月统计销售额环比", 图表类型="折线图",
            x轴="月份", y轴=["销售额"], 聚合方式="求和", 对比="环比",
        )
        assert "销售额环比" in report["报表数据"][0]
        assert report["图表配置"]["对比"] == "环比"

    def test_非日期X轴不加对比列(self):
        df = pd.DataFrame({"地区": ["华东", "华南"], "销售额": [100, 200]})
        report = 生成报表数据(
            df, "按地区统计销售额环比", 图表类型="柱状图",
            x轴="地区", y轴=["销售额"], 聚合方式="求和", 对比="环比",
        )
        assert "销售额环比" not in report["报表数据"][0]

    def test_规则意图识别环比(self):
        df = pd.DataFrame({"月份": pd.to_datetime(["2025-01-01", "2025-02-01"]), "销售额": [1, 2]})
        画像 = {"字段列表": ["月份", "销售额"], "分类字段": [], "日期字段": ["月份"]}
        override = _意图驱动配置(画像, "按月环比销售额", df)
        assert override.get("对比") == "环比"


# ============================================================================
# 3. API 透传（generate + replay）
# ============================================================================

class Test对比API:
    def test_generate带对比_报表含对比列(self, client):
        token = _register(client, "cmpuser")
        ds = _upload(client, token)
        r = client.post("/reports/generate", json={
            "数据集ID": ds,
            "分析需求": "按月统计销售额",
            "图表类型": "折线图",
            "x轴": "月份",
            "y轴": ["销售额"],
            "聚合方式": "求和",
            "对比": "环比",
        }, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        body = r.json()
        rows = body["报表数据"]
        assert len(rows) >= 2
        assert "销售额环比" in rows[0]
        # 环比计算正确（第 2 行 = 1200-1100=100）
        assert rows[1]["销售额环比"] == 100

    def test_replay保留对比(self, client):
        token = _register(client, "cmpreplay")
        ds = _upload(client, token)
        r = client.post("/reports/generate", json={
            "数据集ID": ds, "分析需求": "按月统计销售额", "图表类型": "折线图",
            "x轴": "月份", "y轴": ["销售额"], "聚合方式": "求和", "对比": "同比",
        }, headers={"Authorization": f"Bearer {token}"})
        rid = r.json()["报表ID"]
        assert r.json()["图表配置"]["对比"] == "同比"
        # 重放保留同比
        r = client.post(f"/reports/{rid}/replay", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["图表配置"]["对比"] == "同比"
        assert "销售额同比" in r.json()["报表数据"][0]