"""tests/llm_cassette 单元测试：指纹确定性 / 回放命中 / 回放未命中 / 录制落盘安全。

阶段 50：验证自研 VCR cassette 层的四个核心行为。
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_DIR = os.path.join(PROJECT_ROOT, "tests")
for _p in (PROJECT_ROOT, TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 注意：不能用 `from tests.llm_cassette import ...` —— site-packages 存在第三方
# `tests` 正则包，会吞掉命名空间包解析；统一走 tests/backend 的真包 backend.llm_cassette。
from backend import llm_cassette as cassette_mod  # noqa: E402
from backend.llm_cassette import CassetteMiss, FakeResponse, LLMCassette, _请求指纹  # noqa: E402


def _样本payload() -> dict:
    return {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "帮我看看这份数据整体怎么样"}],
        "temperature": 0,
        "max_tokens": 2048,
    }


# ============================================================================
# 1. 指纹：确定性 + 敏感性
# ============================================================================

def test_请求指纹_同一请求稳定():
    url = "https://api.deepseek.com/v1/chat/completions"
    p1 = _样本payload()
    assert _请求指纹(url, p1) == _请求指纹(url, dict(p1))


def test_请求指纹_请求体变化即不同():
    url = "https://api.deepseek.com/v1/chat/completions"
    p2 = _样本payload()
    p2["messages"] = [{"role": "user", "content": "换个问法"}]
    assert _请求指纹(url, _样本payload()) != _请求指纹(url, p2)


def test_请求指纹_不同url不同():
    base = "https://api.deepseek.com/v1/chat/completions"
    other = "https://api.siliconflow.cn/v1/chat/completions"
    assert _请求指纹(base, _样本payload()) != _请求指纹(other, _样本payload())


# ============================================================================
# 2. 回放模式：命中返回存储响应 / 未命中抛 CassetteMiss
# ============================================================================

def test_回放命中返回存储响应(monkeypatch, tmp_path):
    monkeypatch.setattr(cassette_mod, "CASSETTES_ROOT", tmp_path)
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = _样本payload()
    fp = _请求指纹(url, payload)
    entry = {
        "request": {"url": url, "json": payload},
        "status_code": 200,
        "json": {"choices": [{"message": {"content": "{\"图表类型\": \"饼图\"}"}}]},
    }
    (tmp_path / "scenario").mkdir(parents=True)
    (tmp_path / "scenario" / f"{fp}.json").write_text(
        json.dumps(entry, ensure_ascii=False), encoding="utf-8")

    cassette = LLMCassette("scenario")
    wrapped = cassette.wrap(lambda *a, **k: pytest.fail("回放模式不应发起真实请求"))
    resp = wrapped(url, headers={"Authorization": "Bearer sk-secret"}, json=payload)

    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == '{"图表类型": "饼图"}'


def test_回放未命中抛CassetteMiss(monkeypatch, tmp_path):
    monkeypatch.setattr(cassette_mod, "CASSETTES_ROOT", tmp_path)
    cassette = LLMCassette("no_such_scenario")
    wrapped = cassette.wrap(lambda *a, **k: pytest.fail("不应发起真实请求"))
    with pytest.raises(CassetteMiss):
        wrapped("https://api.deepseek.com/v1/chat/completions",
                headers={}, json=_样本payload())


# ============================================================================
# 3. 录制模式：脚本响应落盘，且永不保存 headers（Authorization 零泄露）
# ============================================================================

def test_录制落盘且不含headers(monkeypatch, tmp_path):
    monkeypatch.setattr(cassette_mod, "CASSETTES_ROOT", tmp_path)
    monkeypatch.setenv("LLM_VCR_RECORD", "1")
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = _样本payload()
    scripted_body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    cassette = LLMCassette("scenario", script=lambda u, p, i: scripted_body)
    wrapped = cassette.wrap(lambda *a, **k: pytest.fail("脚本模式下不应走真实网络"))
    resp = wrapped(url, headers={"Authorization": "Bearer sk-super-secret"}, json=payload)

    fp = _请求指纹(url, payload)
    path = tmp_path / "scenario" / f"{fp}.json"
    assert path.exists(), "录制模式应落盘 cassette"
    assert resp.status_code == 200 and resp.json() == scripted_body

    saved = json.loads(path.read_text(encoding="utf-8"))
    raw = path.read_text(encoding="utf-8")
    assert saved["request"]["json"] == payload
    assert saved["status_code"] == 200
    assert saved["json"] == scripted_body
    # 安全断言：headers / Authorization / api key 绝不落盘
    assert "headers" not in raw
    assert "Authorization" not in raw
    assert "sk-super-secret" not in raw


def test_录制模式真实网络也可用(monkeypatch, tmp_path):
    """录制且无脚本时走真实网络（用户本机录制主路径），响应原样返回并落盘。"""
    monkeypatch.setattr(cassette_mod, "CASSETTES_ROOT", tmp_path)
    monkeypatch.setenv("LLM_VCR_RECORD", "1")
    url = "https://api.deepseek.com/v1/chat/completions"
    payload = _样本payload()
    real_body = {"choices": [], "usage": {"total_tokens": 1}}

    def fake_real_post(u, **kw):
        assert u == url
        return FakeResponse(200, real_body)

    cassette = LLMCassette("scenario")
    wrapped = cassette.wrap(fake_real_post)
    resp = wrapped(url, headers={"Authorization": "Bearer sk"},
                   json=payload, timeout=30, allow_redirects=False)

    fp = _请求指纹(url, payload)
    saved = json.loads((tmp_path / "scenario" / f"{fp}.json").read_text(encoding="utf-8"))
    assert resp.json() == real_body
    assert saved["json"] == real_body
    assert "Authorization" not in (tmp_path / "scenario" / f"{fp}.json").read_text(encoding="utf-8")