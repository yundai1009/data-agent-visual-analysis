# -*- coding: utf-8 -*-
"""阶段 54-6 · Fix 5：缺失值以 null 桶进入图表修复（NaN 桶替换为「（缺失）」）。

走查证据
========
- 中央公园松鼠普查（缺失率 13%，3023 行）→ 柱状图 x=Primary Fur Color 计数
  → 报表含 {"Primary Fur Color": null, "记录数": 55} 一行；ECharts 渲染无名柱条。
- 根因：_聚合数据 用 dropna=False 分组，NaN 组保留为 null 桶。

本文件覆盖
==========
1. 单元级：_聚合数据 三个分组返回路径（计数/无有效y兜底/正常聚合）NaN 桶 →「（缺失）」
2. API 级：上传含缺失 x 轴的 CSV → 柱状图 → 报表数据无 None/null 键
3. 回归：不含缺失时结果不变（无「（缺失）」行）
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"

from 后端_核心.report_generator import _聚合数据

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """TestClient + 临时 SQLite + 验证码捕获（与 test_修复导出注入 同模式）。"""
    tmp_dir = tmp_path_factory.mktemp("fix_missing_bucket")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True

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


def _注册(client, username):
    email = f"{username}@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code, f"未捕获到 {email} 的验证码"
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ============================================================================
# 1. 单元级：_聚合数据 三个分组返回路径
# ============================================================================

class Test聚合数据缺失桶:
    def test_计数路径_NaN桶标为缺失(self):
        """dropna=False 计数：x轴 为 NaN 的分组桶 →「（缺失）」而非 NaN/None。"""
        df = pd.DataFrame({"颜色": ["红", "蓝", None, "红"], "数量": [1, 2, 3, 4]})
        result = _聚合数据(df, "颜色", [], None, "计数")
        assert len(result) == 3, f"应有 红/蓝/（缺失）3 桶，实际 {len(result)}:\n{result}"
        assert "（缺失）" in set(result["颜色"]), result["颜色"].tolist()
        assert not result["颜色"].isna().any(), result["颜色"].tolist()
        # 缺失桶计数正确（NaN 行 1 条）
        缺失行 = result[result["颜色"] == "（缺失）"]
        assert len(缺失行) == 1 and int(缺失行["记录数"].iloc[0]) == 1, result

    def test_无有效y兜底路径_NaN桶标为缺失(self):
        """空 y（无有效数值列）兜底计数路径：NaN 桶同样标「（缺失）」。"""
        df = pd.DataFrame({"地区": ["华东", None, "华东"], "标签": ["a", "b", "c"]})
        result = _聚合数据(df, "地区", ["标签"], None, "求和")
        assert "（缺失）" in set(result["地区"]), result["地区"].tolist()
        assert not result["地区"].isna().any(), result["地区"].tolist()

    def test_正常聚合路径_NaN桶标为缺失(self):
        """求和聚合路径（含分组字段）：x轴/分组字段 的 NaN 桶均标「（缺失）」。"""
        df = pd.DataFrame({
            "地区": ["华东", None, "华东", "华南"],
            "渠道": ["线上", "线下", None, "线上"],
            "销售额": [100, 200, 300, 400],
        })
        result = _聚合数据(df, "地区", ["销售额"], "渠道", "求和")
        assert not result["地区"].isna().any(), result["地区"].tolist()
        assert not result["渠道"].isna().any(), result["渠道"].tolist()
        assert "（缺失）" in set(result["地区"]) or "（缺失）" in set(result["渠道"]), result

    def test_回归_不含缺失结果不变(self):
        """无缺失数据：聚合结果不含「（缺失）」行，数值/标签保持原样。"""
        df = pd.DataFrame({"地区": ["华东", "华南", "华东"], "销售额": [100, 200, 300]})
        result = _聚合数据(df, "地区", ["销售额"], None, "求和")
        assert "（缺失）" not in set(result["地区"]), result["地区"].tolist()
        assert not result["地区"].isna().any()
        # 行为与原实现一致：华东=400、华南=200，两行
        assert len(result) == 2
        华东 = result[result["地区"] == "华东"]
        assert int(华东["销售额"].iloc[0]) == 400, result


# ============================================================================
# 2. API 级：柱状图报表数据无 None/null 键
# ============================================================================

class Test缺失桶API:
    def test_柱状图_缺失x轴桶不出现null键(self, client):
        token = _注册(client, "miss1")
        h = {"Authorization": f"Bearer {token}"}
        # 松鼠普查同构：Primary Fur Color 含缺失（空单元格 → NaN）
        csv = "Primary Fur Color,记录数\nGray,55\nCinnamon,12\n,55\nBlack,3\n"
        r = client.post(
            "/datasets/upload",
            files={"file": ("squirrel.csv", csv.encode("utf-8"), "text/csv")},
            headers=h,
        )
        assert r.status_code == 200, r.text
        ds_id = r.json()["上传成功"][0]["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": ds_id,
            "分析需求": "统计各毛色计数",
            "图表类型": "柱状图",
            "x轴": "Primary Fur Color",
            "y轴": ["记录数"],
            "分组字段": None,
            "聚合方式": "计数",
            "agent_mode": "single",
        }, headers=h)
        assert r.status_code == 200, r.text
        data = r.json()["报表数据"]
        assert data, "柱状图应有数据"
        # 无任何键值为 None/null；缺失桶以「（缺失）」标签呈现
        for row in data:
            for k, v in row.items():
                assert v is not None, f"报表数据出现 null 键 {k!r}: {data}"
        assert any("（缺失）" in str(row) for row in data), f"应有（缺失）桶: {data}"

    def test_回归_无缺失数据无缺失桶行(self, client):
        token = _注册(client, "miss2")
        h = {"Authorization": f"Bearer {token}"}
        csv = "地区,销售额\n华东,100\n华南,200\n华东,300\n"
        r = client.post(
            "/datasets/upload",
            files={"file": ("clean.csv", csv.encode("utf-8"), "text/csv")},
            headers=h,
        )
        assert r.status_code == 200, r.text
        ds_id = r.json()["上传成功"][0]["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": ds_id,
            "分析需求": "",
            "图表类型": "柱状图",
            "x轴": "地区",
            "y轴": ["销售额"],
            "分组字段": None,
            "聚合方式": "求和",
            "agent_mode": "single",
        }, headers=h)
        assert r.status_code == 200, r.text
        data = r.json()["报表数据"]
        assert not any("（缺失）" in str(row) for row in data), f"不应有（缺失）桶: {data}"
        assert all(v is not None for row in data for v in row.values()), data
