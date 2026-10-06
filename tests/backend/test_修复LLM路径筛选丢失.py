# -*- coding: utf-8 -*-
"""阶段 54-8 · 第二块 Fix B（LLM P1-1）：编排器 LLM 路径「筛选条件/TopN/对比」不再被丢弃。

走查证据（_stage52_llm_vcr/报告.md P1-1，复现 6a3）：
- `后端_核心/agent/orchestrator.py` 规则路径 return（L153-162）有
  `筛选条件/TopN/对比` 三键，但 **L410-421（LLM 编排路径 return dict）缺这三键**；
  `_从消息提取意图`（L683-693）已正确解析出（含白名单校验），return 时被丢
  → 省略式追问「那华南呢？」（筛选条件=华南）生成全地区报表
  （复现 6a3：意图来源=LLM，筛选条件=[]，华南行=1/非华南行=1）。

修复：LLM 编排路径 return dict 补 `筛选条件/TopN/对比` 三键，值来自
`_从消息提取意图`（valid_filters / top_n / compare），对齐规则路径形状。

本文件覆盖
==========
1. 单元（编排器级）：LLM 工具调用含 筛选条件 → 编排 return dict 含该筛选；
   不含 → 默认 []/None/None。
2. API 级（全链路，脚本化 chat_completion，零网络）：含筛选参数 → 生成报表
   数据被过滤（只华南）；无筛选 → 全量。
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from unittest import mock

import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"

from 后端_核心.agent.orchestrator import 编排Agent  # noqa: E402
from config.settings import LLMRequestConfig  # noqa: E402

_SENT_CODES: dict = {}


def 样本画像() -> dict:
    return {
        "行数": 6,
        "列数": 4,
        "字段列表": ["月份", "地区", "销售额", "订单数"],
        "数值字段": ["销售额", "订单数"],
        "日期字段": ["月份"],
        "分类字段": ["地区"],
        "文本字段": [],
    }


def 样本df() -> pd.DataFrame:
    return pd.DataFrame({
        "月份": ["2026-01", "2026-01", "2026-02", "2026-02", "2026-03", "2026-03"],
        "地区": ["华东", "华南", "华东", "华南", "华东", "华南"],
        "销售额": [100, 80, 120, 90, 110, 95],
        "订单数": [10, 8, 12, 9, 11, 9],
    })


def _工具响应(tool_name: str, arguments: dict, call_id: str) -> dict:
    return {
        "id": f"chatcmpl-{call_id}",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-chat",
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": call_id,
                    "type": "function",
                    "function": {"name": tool_name, "arguments": json.dumps(arguments, ensure_ascii=False)},
                }],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@contextmanager
def 记忆桩():
    from 后端_核心.agent import memory as 记忆模块
    from 后端_核心.agent import orchestrator as 编排器模块
    with (
        mock.patch.object(编排器模块, "检索相似记忆", return_value=[]),
        mock.patch.object(编排器模块, "保存记忆", return_value=None),
        mock.patch.object(编排器模块, "生成_few_shot_prompt", return_value=""),
        mock.patch.object(记忆模块, "清理记忆", return_value=0),
    ):
        yield


def 脚本_含筛选():
    """三轮响应：画像 → 聚合（含 筛选条件/TopN） → 推荐图表。"""
    return [
        _工具响应("获取数据画像", {}, "call_1"),
        _工具响应(
            "聚合分析",
            {"X轴": "地区", "Y轴": ["销售额"], "聚合方式": "求和",
             "筛选条件": [{"字段": "地区", "操作": "等于", "值": "华南"}],
             "TopN": 5},
            "call_2",
        ),
        _工具响应("推荐图表", {"图表类型": "饼图", "理由": "地区构成适合饼图"}, "call_3"),
    ]


def 脚本_无筛选():
    return [
        _工具响应("获取数据画像", {}, "call_1"),
        _工具响应("聚合分析", {"X轴": "地区", "Y轴": ["销售额"], "聚合方式": "求和"}, "call_2"),
        _工具响应("推荐图表", {"图表类型": "柱状图", "理由": "地区对比适合柱状图"}, "call_3"),
    ]


def 测试llm配置() -> LLMRequestConfig:
    return LLMRequestConfig(provider="deepseek", base_url="https://api.deepseek.com/v1",
                            model="deepseek-chat", api_key="sk-test-not-placeholder")


# ═══ 1. 单元：编排 return dict 补三键 ═══


def test_编排Agent_LLM路径_透传筛选条件TopN对比():
    """红：LLM 编排路径 return dict 缺 筛选条件/TopN/对比——意图解析出但返回被丢。"""
    with 记忆桩(), mock.patch(
        "后端_核心.agent.orchestrator.chat_completion", side_effect=脚本_含筛选()
    ):
        result = 编排Agent(样本画像(), "那华南呢？", df=样本df(), enable_llm=True,
                           llm_config=测试llm配置(), user_id="u1")
    assert result is not None
    assert result["意图来源"] == "LLM"
    assert result["筛选条件"] == [{"字段": "地区", "操作": "等于", "值": "华南"}], (
        f"LLM 路径应透传 筛选条件，实际 {result.get('筛选条件')}"
    )
    assert result["TopN"] == 5, f"TopN 应透传，实际 {result.get('TopN')}"
    assert result["对比"] is None


def test_编排Agent_LLM路径_无筛选默认空():
    """不含筛选参数 → 默认 []/None/None（形状对齐规则路径 L153-162）。"""
    with 记忆桩(), mock.patch(
        "后端_核心.agent.orchestrator.chat_completion", side_effect=脚本_无筛选()
    ):
        result = 编排Agent(样本画像(), "帮我看看数据", df=样本df(), enable_llm=True,
                           llm_config=测试llm配置(), user_id="u1")
    assert result is not None
    assert result["筛选条件"] == []
    assert result["TopN"] is None
    assert result["对比"] is None


# ═══ 2. API 级：生成报表数据被过滤（只华南） ═══


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix_llm_filter")
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
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _上传(client, token):
    csv = "地区,销售额\n华东,100\n华南,80\n华东,120\n华南,90\n"
    r = client.post("/datasets/upload", headers={"Authorization": f"Bearer {token}"},
                    files={"file": ("sales.csv", csv.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["上传成功"][0]["数据集ID"]


def _生成(client, token, did, 需求, script):
    with 记忆桩(), mock.patch(
        "后端_核心.agent.orchestrator.chat_completion", side_effect=script()
    ):
        r = client.post(
            "/reports/generate",
            json={"数据集ID": did, "分析需求": 需求, "图表类型": "自动推荐"},
            headers={"Authorization": f"Bearer {token}", "x-llm-api-key": "sk-test-not-placeholder"},
        )
    return r


def test_API级_LLM含筛选参数_报表只含华南(client):
    """复现 6a3：筛选条件=华南 此前被丢 → 全地区 2 行；修复后只华南。"""
    token = _注册(client, "flt1")
    did = _上传(client, token)
    r = _生成(client, token, did, "那华南呢？", 脚本_含筛选)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["意图来源"] == "LLM", f"意图来源={body.get('意图来源')}"
    数据 = body["报表数据"]
    assert 数据, "筛选后应有聚合结果"
    for row in 数据:
        assert row.get("地区") == "华南", f"报表数据应只含华南：{数据}"
    配置 = body["图表配置"]
    assert 配置.get("筛选条件") == [{"字段": "地区", "操作": "等于", "值": "华南"}], (
        f"图表配置应回显筛选条件：{配置.get('筛选条件')}"
    )


def test_API级_LLM无筛选_报表全量(client):
    """对照：无筛选参数 → 全地区（华东+华南 各聚合一行）。"""
    token = _注册(client, "flt2")
    did = _上传(client, token)
    r = _生成(client, token, did, "帮我看看数据", 脚本_无筛选)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["意图来源"] == "LLM"
    地区集 = {row.get("地区") for row in body["报表数据"]}
    assert 地区集 == {"华东", "华南"}, f"无筛选应全量：{body['报表数据']}"