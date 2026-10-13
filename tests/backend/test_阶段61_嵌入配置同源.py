# -*- coding: utf-8 -*-
"""阶段 61 · Task 0：embedding 端点/模型/Key 三者同源（解耦请求级 llm_config）。

阶段 27 把 embed_text 对齐成「llm_config 优先」，但只对齐了一半：
  · api_key  ← llm_config.api_key                 （跟用户/请求走）
  · base_url ← llm_config.base_url                （跟用户/请求走）
  · model    ← EnvConfig.LLM_EMBEDDING_MODEL     （永远全局，llm_client.py:416）
于是必然出现两种错配：
  ① 用户 BYOK Key + 服务端 LLM_EMBEDDING_BASE_URL → 401
  ② 用户所选 provider 的地址 + 别人的模型名        → 400
config/providers.toml 里也没有 embedding_model 字段，没有任何 provider→模型映射。
两者都只 logger.warning，用户侧表现为「某些用户的记忆功能从头到尾没工作过」。

决策 D1/D2/D3：
  · D1 三要素同源（端点/模型/Key 全取 LLM_EMBEDDING_*，Key 缺省回落 LLM_API_KEY）
  · D2 embed_text / 保存记忆 / 检索相似记忆 的签名里**不再有** llm_config
  · D3 存储侧只向量化「需求」，与检索侧对称（意图/画像只进 documents 与 metadata）
"""

from __future__ import annotations

import inspect
from unittest import mock

import pytest

from config.settings import EnvConfig
from 后端_核心.agent import llm_client, memory
from 后端_核心.agent.llm_client import embed_text, embedding_settings


# ═══════════════════════════════════════════════════════════════
# 一、embedding_settings()：三要素同源（决策 D1）
# ═══════════════════════════════════════════════════════════════


def test_三者同源_优先独立配置(monkeypatch):
    """三个 LLM_EMBEDDING_* 全配 → 原样返回，不看任何请求级配置。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://emb.example.com/v1", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "text-embedding-v2", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "emb-key", raising=False)
    assert embedding_settings() == ("https://emb.example.com/v1", "text-embedding-v2", "emb-key")


def test_未配置独立项_回落通用配置(monkeypatch):
    """留空 = 用 LLM_BASE_URL + text-embedding-3-small + LLM_API_KEY（保持旧默认行为）。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "https://api.openai.com/v1", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "sk-general", raising=False)
    assert embedding_settings() == ("https://api.openai.com/v1", "text-embedding-3-small", "sk-general")


def test_端点尾部斜杠归一化(monkeypatch):
    """端点归一化尾部斜杠——指纹要拿它做等值比较，带不带 '/' 不能算成两个语义空间。

    写错的后果：运维在 .env 里把 https://x/v1 改成 https://x/v1/，
    指纹立刻不一致 → 服务拒绝启动，而向量其实完全可用。
    """
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://emb.example.com/v1/", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "https://api.openai.com/v1", raising=False)
    assert embedding_settings()[0] == "https://emb.example.com/v1"


def test_embed_text_请求三者来自同一处(monkeypatch):
    """发出的 URL / model / Authorization 必须全部来自 embedding_settings()（决策 D1）。"""
    捕获 = {}

    def 假post(url, headers=None, json=None, timeout=None, allow_redirects=None):
        捕获.update(url=url, headers=headers, payload=json)
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
        return resp

    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://emb.example.com/v1", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "text-embedding-v2", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "emb-key", raising=False)
    monkeypatch.setattr(llm_client.requests, "post", 假post)

    assert embed_text("销售额趋势") == [0.1, 0.2, 0.3]
    assert 捕获["url"] == "https://emb.example.com/v1/embeddings"
    assert 捕获["payload"]["model"] == "text-embedding-v2"
    assert 捕获["headers"]["Authorization"] == "Bearer emb-key"


def test_占位Key_不发请求(monkeypatch):
    """占位符 Key 直接返回 None，不去打网络（沿用 is_llm_configured 的既有约定）。"""

    def 不该调用(*args, **kwargs):
        raise AssertionError("未配置 embedding Key 时不应发起 HTTP 请求")

    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "your_llm_api_key", raising=False)
    monkeypatch.setattr(llm_client.requests, "post", 不该调用)
    assert embed_text("x") is None


def test_未配置端点_不发请求(monkeypatch):
    """Key 配了但端点没配 → 同样早退，不发 HTTP。

    为什么补这条（审查点名的零覆盖分支）：`embed_text` 的两道早退（Key 未配置 /
    端点未配置）以前只测了前一道。端点缺失时如果没早退，url 会变成
    `"/embeddings"`，`requests.post` 抛 MissingSchema —— 而它在 try 外面，
    直接把异常抛给 调用方（保存记忆），表现为「记忆功能随机报错」。
    """
    不该调用_calls = []

    def 不该调用(*a, **k):
        不该调用_calls.append((a, k))
        raise AssertionError("未配置 embedding 端点时不应发起 HTTP 请求")

    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "emb-key", raising=False)
    monkeypatch.setattr(llm_client.requests, "post", 不该调用)

    assert embed_text("x") is None
    assert 不该调用_calls == []


def test_embed_text_非200不抛(monkeypatch):
    """端点/模型错配（400）必须收敛成 None，由调用方降级，而不是把 5xx 抛到主流程。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://emb.example.com/v1", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "emb-key", raising=False)
    resp = mock.Mock(status_code=400)
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: resp)
    assert embed_text("x") is None


# ═══════════════════════════════════════════════════════════════
# 二、记忆链路彻底去掉请求级 llm_config（决策 D2）
# ═══════════════════════════════════════════════════════════════


def test_记忆链路签名不再接受请求级配置():
    """防回退：签名里一旦重新出现 llm_config，就有人会顺手把 provider 再传进来。"""
    for 函数 in (embed_text, memory.保存记忆, memory.检索相似记忆):
        assert "llm_config" not in inspect.signature(函数).parameters


# ═══════════════════════════════════════════════════════════════
# 三、存储侧与检索侧对称：只向量化「需求」（决策 D3）
# ═══════════════════════════════════════════════════════════════


class _假集合:
    """只实现 保存记忆 走到的接口，记录 add 的入参。"""

    def __init__(self):
        self.added = None

    def add(self, **kwargs):
        self.added = kwargs


def test_保存记忆_只向量化需求(monkeypatch):
    """意图/画像不再拼进向量化文本——检索侧查的也只有需求。

    为什么：存「需求+意图+画像」而查「需求」是非对称相似度，
    长文档侧的额外内容会稀释分数，top-3 排名失真 → 「记忆好像没起作用」。
    删除后果：召回质量下降但不报错，属于最难自查的一类劣化。
    """
    捕获 = {}
    假集合 = _假集合()

    def 假embed(文本):
        捕获["文本"] = 文本
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(memory, "embed_text", 假embed)
    monkeypatch.setattr(memory, "_get_collection", lambda: 假集合)

    assert memory.保存记忆("u1", "看销售额趋势", {"图表类型": "折线图", "x轴": "月"}, "100行/5列") is True
    assert 捕获["文本"] == "看销售额趋势"
    # documents 仍存全量文本（人工排查 / 将来做关键词兜底要用）
    assert "折线图" in 假集合.added["documents"][0]
    # metadata 里的意图/画像字段一个都不能少（few-shot 靠它们拼 prompt）
    meta = 假集合.added["metadatas"][0]
    assert meta["图表类型"] == "折线图"
    assert meta["x轴"] == "月"
    assert meta["画像摘要"] == "100行/5列"


def test_保存记忆_embedding失败_返回False(monkeypatch):
    monkeypatch.setattr(memory, "embed_text", lambda 文本: None)
    monkeypatch.setattr(memory, "_get_collection", lambda: _假集合())
    assert memory.保存记忆("u1", "需求", {}, "画像") is False


def test_保存记忆_无user_id_不落库(monkeypatch):
    """跨用户泄漏是 P0：无主记忆会被他人检索到，必须在入口就挡。"""

    def 不该调用(*a, **k):
        raise AssertionError("无 user_id 时不应调用 embed_text")

    monkeypatch.setattr(memory, "embed_text", 不该调用)
    assert memory.保存记忆("", "需求", {}, "画像") is False


def test_检索相似记忆_查询向量就是需求(monkeypatch):
    """检索侧向量化文本必须与存储侧完全一致（决策 D3 的另一半）。"""
    捕获 = {}

    class _假结果集合(_假集合):
        def query(self, **kwargs):
            捕获["query"] = kwargs
            return {"metadatas": [[{"需求": "看销售额趋势", "图表类型": "折线图", "x轴": "月", "聚合方式": "sum"}]], "distances": [[0.12]]}

    def 假embed(文本):
        捕获["文本"] = 文本
        return [0.1, 0.2, 0.3]

    monkeypatch.setattr(memory, "embed_text", 假embed)
    monkeypatch.setattr(memory, "_get_collection", lambda: _假结果集合())

    结果 = memory.检索相似记忆("u1", "看销售额趋势")
    assert 捕获["文本"] == "看销售额趋势"
    # user_id 仍是硬隔离条件，不能因为去参而丢掉
    assert 捕获["query"]["where"] == {"user_id": "u1"}
    assert 结果[0]["图表类型"] == "折线图"