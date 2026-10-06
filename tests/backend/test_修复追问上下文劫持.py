# -*- coding: utf-8 -*-
"""阶段 54-8 · 第二块 Fix C（LLM P1-2）：追问上下文的历史图表名不再劫持显式声明。

走查证据（_stage52_llm_vcr/报告.md P1-2，复现 6a 对照 6a2）：
- `api/routes/reports.py` `_注入追问上下文`（L312-316）必写「图表 {上轮图表类型}」
  → `后端_核心/field_selector.py` `_显式图表声明`（L336-338）`if name in 文本`
  对任意图表名**子串**命中 → 上一轮是饼图时，任何含「饼图」的追问短路成
  规则-受控语句，LLM 零执行（A/B 实证：同一「那华南呢？」带上下文→规则；
  不带→LLM 3 轮）。

修复（最小且不破坏 Fix4 显式图表优先）：
1. `_注入追问上下文`：上下文行「图表 {上轮图表类型}」→「{上轮图表类型} 报表」——
   保持信息但图表名后紧跟汉字（不再独立成词触发声明识别）；
2. `_显式图表声明`：图表名需**独立成词**——后随 空白/标点/结尾 才命中，
   紧贴其他汉字（如「饼图 报表」）视为陈述历史而非用户新声明。

本文件覆盖
==========
1. 单元：`_显式图表声明` 的边界行为（模板语法仍优先；「生成饼图」仍命中；
   注入上下文行「饼图 报表」不再触发；追问「换成散点图」显式命中）。
2. API 级：生成饼图报表 → 追问「那华南呢？」→ 意图来源应为 LLM（不再被劫持
   到规则-受控语句），且筛选条件生效；追问「换成散点图」→ 显式声明生效为散点图。
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import contextmanager
from unittest import mock

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"

from 后端_核心.field_selector import _受控语句配置, _显式图表声明  # noqa: E402

_SENT_CODES: dict = {}


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


def 画像():
    return {
        "行数": 5,
        "列数": 2,
        "字段列表": ["地区", "销售额"],
        "数值字段": ["销售额"],
        "日期字段": [],
        "分类字段": ["地区"],
        "文本字段": [],
    }


# ═══ 1. 单元：_显式图表声明 边界行为 ═══


def test_显式图表声明_模板语法仍优先():
    """Fix 4 回归：图表类型:饼图 模板语法仍直接命中。"""
    assert _显式图表声明("图表类型:饼图 请分析数据中各个类别的分布情况") == "饼图"


def test_显式图表声明_裸图表名结尾仍命中():
    """Fix 4 回归：用户显式说「生成饼图」「换成散点图」→ 命中（独立成词）。"""
    assert _显式图表声明("生成饼图") == "饼图"
    assert _显式图表声明("换成散点图") == "散点图"


def test_显式图表声明_注入上下文行不再触发():
    """红：上下文行「图表 饼图（X 轴：…）」子串命中 → 追问被劫持成规则。

    修复后上下文行改为「饼图报表（X 轴：…）」——饼图后紧跟汉字「报」，
    不再是独立成词 → 不触发声明识别。
    """
    新上下文行 = "第 1 轮「按地区统计销售额」：饼图报表（X 轴：地区，Y 轴：销售额，分组：-）"
    assert _显式图表声明(新上下文行) is None, "追问上下文的历史图表名不得触发显式声明"


def test_显式图表声明_上下文与追问合并文本_只认用户声明():
    """完整注入文本（上下文含「饼图报表」）+ 用户追问「换成散点图」→ 只命中用户声明。"""
    完整文本 = (
        "【上一轮分析上下文】（本次是针对上一轮的追问，可参考但不能照抄）\n"
        "- 第 1 轮「按地区统计销售额」：饼图报表（X 轴：地区，Y 轴：销售额，分组：-）\n"
        "\n用户追问：换成散点图"
    )
    assert _显式图表声明(完整文本) == "散点图"


def test_显式图表声明_旧措辞对比_独立成词仍算声明():
    """行为对比：`图表 饼图` / `上一报表 饼图` 中图表名处于结尾（独立成词），
    按边界规则仍算显式声明（无害：用户真写了图表名就该是它）；真正的问题是
    注入上下文里图表名后紧跟汉字/括号的陈述形式（见 test_注入上下文行不再触发）。"""
    assert _显式图表声明("图表 饼图") == "饼图"
    assert _显式图表声明("上一报表 饼图") == "饼图"


def test_受控语句配置_注入上下文文本不短路为规则():
    """追问全文本（上下文含 饼图报表 + 用户「那华南呢？」）→ 受控语句应落空，
    交给 LLM（修复前 _受控语句配置 因上下文「饼图」子串命中返回饼图配置）。"""
    追问文本 = (
        "【上一轮分析上下文】（本次是针对上一轮的追问，可参考但不能照抄）\n"
        "- 第 1 轮「按地区统计销售额」：饼图报表（X 轴：地区，Y 轴：销售额，分组：-）\n"
        "\n用户追问：那华南呢？"
    )
    assert _受控语句配置(画像(), 追问文本) == {}, (
        f"追问上下文不得劫持为规则-受控语句，实际 {_受控语句配置(画像(), 追问文本)}"
    )


# ═══ 2. API 级：追问链回到 LLM + 显式声明仍生效 ═══


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix_followup_hijack")
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


def _生成饼图报表(client, token, did):
    """规则路径（无 LLM key）生成饼图报表，供追问链作上一轮。"""
    r = client.post(
        "/reports/generate",
        json={"数据集ID": did, "分析需求": "图表类型:饼图 按地区统计销售额占比", "图表类型": "自动推荐"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["图表类型"] == "饼图", body
    return body["报表ID"]


def test_API级_饼图追问那华南呢_意图来源LLM且被过滤(client):
    """复现 6a/6a2：修复前追问带上下文（含饼图）→ 规则-受控语句、筛选丢失；
    修复后 → LLM 全链路执行，筛选条件=华南 生效（只华南）。"""
    token = _注册(client, "fup1")
    did = _上传(client, token)
    pie_id = _生成饼图报表(client, token, did)

    脚本 = [
        _工具响应("获取数据画像", {}, "call_1"),
        _工具响应("聚合分析",
                   {"X轴": "地区", "Y轴": ["销售额"], "聚合方式": "求和",
                    "筛选条件": [{"字段": "地区", "操作": "等于", "值": "华南"}]},
                   "call_2"),
        _工具响应("推荐图表", {"图表类型": "饼图", "理由": "华南构成适合饼图"}, "call_3"),
    ]
    with 记忆桩(), mock.patch(
        "后端_核心.agent.orchestrator.chat_completion", side_effect=脚本
    ):
        r = client.post(
            "/reports/generate",
            json={"数据集ID": did, "分析需求": "那华南呢？", "图表类型": "自动推荐",
                  "上一报表ID": pie_id},
            headers={"Authorization": f"Bearer {token}", "x-llm-api-key": "sk-test-not-placeholder"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["意图来源"] == "LLM", (
        f"追问不得被上下文图表名劫持到规则-受控语句，实际来源 {body.get('意图来源')}"
    )
    数据 = body["报表数据"]
    assert 数据, "筛选后应有聚合结果"
    for row in 数据:
        assert row.get("地区") == "华南", f"报表数据应只含华南：{数据}"
    assert body["图表配置"].get("筛选条件") == [{"字段": "地区", "操作": "等于", "值": "华南"}]


def test_API级_追问换成散点图_显式声明生效(client):
    """上一轮是饼图时追问「换成散点图」→ 必须命中用户显式声明（修复前被
    上下文里的「饼图」优先级抢先 → 仍是饼图）。"""
    token = _注册(client, "fup2")
    did = _上传(client, token)
    pie_id = _生成饼图报表(client, token, did)

    r = client.post(
        "/reports/generate",
        json={"数据集ID": did, "分析需求": "换成散点图", "图表类型": "自动推荐",
              "上一报表ID": pie_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["图表类型"] == "散点图", f"显式声明应生效为散点图：{body.get('图表类型')}"
    # 无 LLM key 时规则兜底统一标「规则」（编排器降级路径的既有契约）；
    # 有 LLM key 时受控语句命中标「规则-受控语句」。核心契约是图表类型=散点图。
    assert body["意图来源"] in ("规则", "规则-受控语句"), body.get("意图来源")