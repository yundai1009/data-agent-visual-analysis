# -*- coding: utf-8 -*-
"""阶段 54-9 · Fix L3 / L2 验收：API 级 VCR 轮 2 指纹命中（react_multi_round API 级回放）。

走查证据（_stage52_llm_vcr/报告.md P2-1，复现 1x）：
- API 级轮 1 请求与 react_multi_round 录制逐字节一致 → 指纹命中；
- 轮 2 因运行时画像摘要不同（`_可读画像摘要` 质量评级文案「A-优秀」+ 日期 datetime 化
  vs 录制「良好-完整无缺失」+「2026-01」）→ 指纹 miss → 静默降级。

Fix L3 后 `_可读画像摘要` 输出规范化（稳定评级枚举 + YYYY-MM-DD 日期），
API 级 cassette（tests/cassettes/react_llm_api_ok / react_llm_api_midmiss）
按真实「上传 → 画像 → 生成」路径离线录制，本用例回放验证：
- OK 场景：全 3 轮命中——意图来源=LLM、无 LLM 失败原因、trace 3 轮 LLM 成功
  （轮 2 指纹不再 miss，这是关键验收）；
- midmiss 场景：轮 2 缺失 → 报表仍 200，trace 保留「轮 1 成功 + 轮 2 失败」
  证据（L2 中段异常可审计，与纯规则模板 trace 可区分）。
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(PROJECT_ROOT, "tests")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
if TESTS_DIR not in sys.path:
    sys.path.insert(0, TESTS_DIR)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"

from backend.llm_cassette import LLMCassette  # noqa: E402

_SENT_CODES: dict = {}

_CSV = ("月份,地区,销售额,订单数\n"
        "2026-01,华东,100,10\n2026-01,华南,80,8\n2026-02,华东,120,12\n"
        "2026-02,华南,90,9\n2026-03,华东,110,11\n2026-03,华南,95,9\n")


def _记忆桩():
    from 后端_核心.agent import memory as 记忆模块
    from 后端_核心.agent import orchestrator as 编排器模块
    patches = (
        mock.patch.object(编排器模块, "检索相似记忆", return_value=[]),
        mock.patch.object(编排器模块, "保存记忆", return_value=None),
        mock.patch.object(编排器模块, "生成_few_shot_prompt", return_value=""),
        mock.patch.object(记忆模块, "清理记忆", return_value=0),
    )
    for p in patches:
        p.start()
    return patches


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """TestClient + 临时 SQLite + parquet 隔离 + 验证码捕获（与 test_api_integration 同款）。"""
    tmp_dir = tmp_path_factory.mktemp("vcr_api_test")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True
    from 后端_核心.存储 import sqlite_repo
    sqlite_repo._PARQUET_DIR = tmp_dir / "parquet"  # 隔离：不写项目 data/parquet

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


@pytest.fixture(scope="module")
def 数据集(client):
    """注册用户 + 上传与 golden 样本一致的 CSV，返回 {token, did}。"""
    email = "vcr549@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    r = client.post("/auth/register", json={
        "username": "vcr549", "email": email,
        "code": _SENT_CODES[email], "password": "secret123",
    })
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    r = client.post("/datasets/upload",
                    files={"file": ("stage549.csv", _CSV.encode("utf-8"), "text/csv")},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    did = r.json()["上传成功"][0]["数据集ID"]
    return {"token": token, "did": did}


@pytest.fixture
def llm_vcr(monkeypatch, request):
    """拦 requests.post → LLMCassette（scenario 由 indirect 参数化，回放模式）。"""
    import requests as requests_mod
    scenario = getattr(request, "param", "react_llm_api_ok")
    cassette = LLMCassette(scenario=scenario)
    monkeypatch.setattr(requests_mod, "post", cassette.wrap(requests_mod.post))
    return cassette


def _生成(client, 数据集, llm_vcr, 需求="帮我看看这份数据整体怎么样"):
    """在 VCR 回放下走一次真实 /reports/generate。"""
    # 隔离：LLM失败原因是 llm_client 的「模块级最近一次失败」全局，本套件此前
    # 的真库/全链路用例可能写入（如 HTTP 402），会把无关失败漏进本请求断言——
    # 清空后只有本次请求内真实发生的失败才会出现在 LLM失败原因里。
    from 后端_核心.agent import llm_client as _llm客户端
    _llm客户端._last_llm_fail.clear()
    import requests as requests_mod
    patches = _记忆桩()
    try:
        return client.post("/reports/generate", json={
            "数据集ID": 数据集["did"], "分析需求": 需求, "图表类型": "自动推荐",
            "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {数据集['token']}", "X-LLM-API-Key": "sk-replay"})
    finally:
        for p in patches:
            p.stop()


# ---- L3 验收：全 3 轮回放命中（轮 2 指纹不再 miss）--------------------------------

@pytest.mark.parametrize("llm_vcr", ["react_llm_api_ok"], indirect=True)
def test_L3_API级_全3轮回放命中_轮2指纹不再miss(client, 数据集, llm_vcr):
    """关键验收：API 级回放 react_llm_api_ok，轮 1/2/3 全部指纹命中。"""
    r = _生成(client, 数据集, llm_vcr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["意图来源"] == "LLM", f"某轮 CassetteMiss 静默降级：{body.get('LLM失败原因')}"
    assert not body.get("LLM失败原因"), f"不应有 LLM 失败原因：{body.get('LLM失败原因')}"
    assert body["图表类型"] == "饼图"
    assert body["图表配置"]["X轴"] == "地区"

    trace = body.get("Agent Trace") or []
    llm_ok = [t for t in trace if t.get("步骤") == "LLM推理" and t.get("状态") == "成功"]
    轮次 = sorted(t.get("轮次") for t in llm_ok)
    assert 轮次 == [1, 2, 3], f"三轮都应 LLM 成功：{trace}"
    assert not [t for t in trace if t.get("步骤") == "LLM推理" and t.get("状态") == "失败"], f"不应有失败轮：{trace}"


@pytest.mark.parametrize("llm_vcr", ["react_llm_api_ok"], indirect=True)
def test_L3_API级_同一场景跑两次_轮2指纹均命中(client, 数据集, llm_vcr):
    """同一 cassette 场景跑两次 API 级走查：两次轮 2 都命中（不再是偶发 miss）。"""
    for _ in range(2):
        r = _生成(client, 数据集, llm_vcr)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["意图来源"] == "LLM", "两次回放都应 LLM（轮 2 指纹稳定命中）"
        assert not body.get("LLM失败原因")


# ---- L2 验收：中段异常（轮 2 缺失）→ 200 + trace 保留失败证据 ---------------------

@pytest.mark.parametrize("llm_vcr", ["react_llm_api_midmiss"], indirect=True)
def test_L2_API级_轮2缺失_报表200且trace含轮1成功轮2失败(client, 数据集, llm_vcr):
    """轮 2 CassetteMiss 不再穿透：报表 200；trace 保留轮 1 命中证据 + 轮 2 失败原因。"""
    r = _生成(client, 数据集, llm_vcr)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["意图来源"] == "规则", f"轮 2 失败应降级规则：{body.get('意图来源')}"
    assert body.get("LLM失败原因"), "应透传 LLM 失败原因"

    trace = body.get("Agent Trace") or []
    llm_记录 = [t for t in trace if t.get("步骤") == "LLM推理"]
    assert any(t.get("轮次") == 1 and t.get("状态") == "成功" for t in llm_记录), \
        f"轮 1 命中证据必须保留：{trace}"
    assert any(t.get("轮次") == 2 and t.get("状态") == "失败" for t in llm_记录), \
        f"轮 2 失败证据必须记录：{trace}"
    轮2失败 = next(t for t in llm_记录 if t.get("轮次") == 2)
    assert "cassette 缺失" in 轮2失败["理由"], f"失败理由应可审计：{轮2失败}"
    # 与纯规则模板 trace（轮次=None）可区分
    assert all(t.get("轮次") in (1, 2) for t in llm_记录 if t.get("步骤") == "LLM推理")