# -*- coding: utf-8 -*-
"""阶段 54-6 · Fix 3：散点图按 X 分组求和失真修复（数值 X 走明细路径）。

走查证据
========
- tips.csv（244 行）→ 散点图 x=total_bill y=tip → 报表数据 229 行：
  unique(total_bill)=229，groupby(total_bill).sum(tip) 也是 229——
  pandas 按 X 精确分组求和覆盖了 y，用户观察相关性/分布时点数被静默压缩。

本文件覆盖
==========
1. 单元级：_生成散点图数据 数值 X → 原始明细点（重复 X 不聚合）
2. API 级：上传含重复 X 的 CSV → 生成散点图 → 报表数据行数 = 原始行数
3. 回归保护：分类 X（如 地区,销售额）的散点图仍走聚合，行为不变
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

from 后端_核心 import report_generator as generator

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """TestClient + 临时 SQLite + 验证码捕获（与 test_修复导出注入 同模式）。"""
    tmp_dir = tmp_path_factory.mktemp("fix_scatter")
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
# 1. 单元级：_生成散点图数据
# ============================================================================

class Test生成散点图数据:
    def test_数值X_保留原始点不聚合(self):
        """x=[1,1,2,2] y=[1,2,3,4] → 4 行原始点（修复前 _聚合数据 按 X 求和 → 2 行）。"""
        df = pd.DataFrame({"x": [1, 1, 2, 2], "y": [1, 2, 3, 4]})
        result = generator._生成散点图数据(df, "x", ["y"])
        assert len(result) == 4, f"应为 4 行原始点，实际 {len(result)} 行:\n{result}"
        # 每个原始点都保留（重复 X=1 的两个 y 值 1 和 2 都在）
        assert list(result["x"]) == [1, 1, 2, 2]
        assert list(result["y"]) == [1, 2, 3, 4]

    def test_数值X_含缺失行被剔除(self):
        """明细路径 dropna：任一列为 NaN 的行剔除，其余原始点保留。"""
        df = pd.DataFrame({"x": [1, 1, float("nan"), 2], "y": [1, 2, 3, 4]})
        result = generator._生成散点图数据(df, "x", ["y"])
        assert len(result) == 3, f"NaN 行应被剔除，剩 3 行，实际 {len(result)}:\n{result}"

    def test_分类X_保持聚合(self):
        """回归保护：分类 X（地区,销售额）仍走 _聚合数据（求和聚合），行为不变。"""
        df = pd.DataFrame({"地区": ["华东", "华东", "华南"], "销售额": [100, 200, 300]})
        result = generator._生成散点图数据(df, "地区", ["销售额"])
        # 聚合后 2 行（华东=300、华南=300），而非 3 行原始明细
        assert len(result) == 2, f"分类 X 应聚合为 2 行，实际 {len(result)}:\n{result}"
        assert "销售额" in result.columns

    def test_无有效数值y_回退分类计数(self):
        """y 轴无有效数值列 → 回退 _聚合数据 原逻辑（按 x轴 分类计数）。"""
        df = pd.DataFrame({"地区": ["华东", "华东", "华南"], "标签": ["a", "b", "c"]})
        result = generator._生成散点图数据(df, "地区", ["标签"])
        assert len(result) == 2, f"应回退分类计数（华东/华南 2 行），实际 {len(result)}:\n{result}"
        assert "记录数" in result.columns

    def test_数值X_含分组字段_分组列保留(self):
        """M1（审查）：数值 X 明细路径需保留有效分组字段——分组字段用于前端
        chart_config['颜色'] 着色，缺失会导致该列引用失效。"""
        df = pd.DataFrame({
            "x": [1, 1, 2, 2],
            "y": [1, 2, 3, 4],
            "地区": ["华东", "华南", "华东", "华南"],
        })
        result = generator._生成散点图数据(df, "x", ["y"], 分组字段="地区")
        # 明细 4 行保留
        assert len(result) == 4, f"明细应 4 行，实际 {len(result)}:\n{result}"
        # 分组字段列必须存在（前端颜色着色依赖）
        assert "地区" in result.columns, f"分组字段列丢失:\n{result.columns.tolist()}"
        assert list(result["地区"]) == ["华东", "华南", "华东", "华南"]

    def test_最大点数截断(self):
        """明细路径按 最大点数 截断（高基数防超大数据集）。"""
        df = pd.DataFrame({"x": range(50), "y": range(50)})
        result = generator._生成散点图数据(df, "x", ["y"], 最大点数=10)
        assert len(result) == 10, f"应截断为 10 行，实际 {len(result)}"


# ============================================================================
# 2. API 级：重复 X 的散点图报表数据 = 原始行数（明细未聚合）
# ============================================================================

class Test散点图API明细:
    def test_重复X散点图_报表数据行数等于原始行数(self, client):
        token = _注册(client, "scatter1")
        h = {"Authorization": f"Bearer {token}"}
        # tips.csv 同构：total_bill 重复（1 出现 2 次），tip 为原始 y 值
        csv = "total_bill,tip\n1,1\n1,2\n2,3\n2,4\n"
        r = client.post(
            "/datasets/upload",
            files={"file": ("tips.csv", csv.encode("utf-8"), "text/csv")},
            headers=h,
        )
        assert r.status_code == 200, r.text
        ds_id = r.json()["上传成功"][0]["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": ds_id,
            "分析需求": "",
            "图表类型": "散点图",
            "x轴": "total_bill",
            "y轴": ["tip"],
            "分组字段": None,
            "聚合方式": "求和",
            "agent_mode": "single",
        }, headers=h)
        assert r.status_code == 200, r.text
        data = r.json()["报表数据"]
        assert len(data) == 4, f"散点图应保留 4 个原始点，实际 {len(data)}:\n{data}"


# ============================================================================
# 3. API 级：分类 X 的散点图仍聚合（回归保护）
# ============================================================================

class Test散点图分类X聚合:
    def test_分类X散点图_报表数据仍为聚合行(self, client):
        token = _注册(client, "scatter2")
        h = {"Authorization": f"Bearer {token}"}
        csv = "地区,销售额\n华东,100\n华东,200\n华南,300\n"
        r = client.post(
            "/datasets/upload",
            files={"file": ("reg.csv", csv.encode("utf-8"), "text/csv")},
            headers=h,
        )
        assert r.status_code == 200, r.text
        ds_id = r.json()["上传成功"][0]["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": ds_id,
            "分析需求": "",
            "图表类型": "散点图",
            "x轴": "地区",
            "y轴": ["销售额"],
            "分组字段": None,
            "聚合方式": "求和",
            "agent_mode": "single",
        }, headers=h)
        assert r.status_code == 200, r.text
        data = r.json()["报表数据"]
        assert len(data) == 2, f"分类 X 散点图应聚合为 2 行，实际 {len(data)}:\n{data}"
