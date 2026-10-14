# -*- coding: utf-8 -*-
"""阶段 63：embedding 配置同源自检（llm_client.检查嵌入配置）。

为什么单独补这一个自检
----------------------
阶段 61 把「换 embedding 模型后旧向量与新查询不同源」做成了硬闸门（第 6 道防线），
但漏掉了**更早、也更常见**的一层：连配置本身都没配对。

E2E 真机实测（scripts/e2e_real_user.py，run=1014-100941）撞见的现场：
    `.env` 只配了 LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4（智谱），
    没配 LLM_EMBEDDING_MODEL → embedding_settings() 的回落链给出
    「OpenAI 的模型名 text-embedding-3-small + 智谱的端点」→ embed_text() HTTP 400
    → 被 llm_client 的非 200 分支静默吞掉 → 而 /healthz.memory 是
    ok=true、指纹一致=true、条数=0，**全绿**。记忆功能从上线到现在一次都没工作过。

也就是说：阶段 61 的两道机制（指纹闸 + /healthz 记忆块）都盖不住这个洞——
指纹闸要等「库建起来」才有指纹可比，全新部署是「未创建」= 放行；
/healthz 的 ok 语义被定死为「库可读」，不是「embedding 调得通」。

本测试钉住三条约定：
  1. 不发网络请求（启动自检和 /healthz 会被高频轮询，不能把探活变成计费调用）；
  2. 「未知」是一等公民（没 Key / 没端点时不该判对错，那属于「记忆未启用」）；
  3. 缺省模型名 + 非 OpenAI 端点 = 不同源（这是唯一能纯靠配置判出来的错配）。
"""

from __future__ import annotations

import inspect

from config.settings import EnvConfig
from 后端_核心.agent import llm_client, memory
from 后端_核心.agent.llm_client import 检查嵌入配置

# ═══════════════════════════════════════════════════════════════
# 一、签名前置约定
# ═══════════════════════════════════════════════════════════════


def test_自检函数不接收任何参数():
    """调用点只有 /healthz 和启动自检两处，都不带参——保持无参最省心。"""
    assert inspect.signature(检查嵌入配置).parameters == {}


def test_返回键集合固定(monkeypatch):
    """/healthz 直接把它摊平进 memory 块，键集合不能随分支变。"""
    基础键 = {"同源", "端点", "模型", "端点来源", "模型来源", "键来源", "说明"}
    for 场景 in (
        # 无 Key / 无端点
        {"LLM_EMBEDDING_BASE_URL": "", "LLM_EMBEDDING_MODEL": "", "LLM_EMBEDDING_API_KEY": "",
         "LLM_BASE_URL": "", "LLM_API_KEY": ""},
        # 缺省模型名 + 第三方端点（假绿灯现场）
        {"LLM_EMBEDDING_BASE_URL": "", "LLM_EMBEDDING_MODEL": "", "LLM_EMBEDDING_API_KEY": "",
         "LLM_BASE_URL": "https://open.bigmodel.cn/api/paas/v4", "LLM_API_KEY": "real-key"},
        # 三项显式
        {"LLM_EMBEDDING_BASE_URL": "https://emb.example.com/v1", "LLM_EMBEDDING_MODEL": "bge-large",
         "LLM_EMBEDDING_API_KEY": "k", "LLM_BASE_URL": "", "LLM_API_KEY": ""},
    ):
        for 键, 值 in 场景.items():
            monkeypatch.setattr(EnvConfig, 键, 值, raising=False)
        assert set(检查嵌入配置()) == 基础键, 场景


# ═══════════════════════════════════════════════════════════════
# 二、配置错配的定性
# ═══════════════════════════════════════════════════════════════


def test_无Key时判未知_不误伤(monkeypatch):
    """没配 Key = 记忆链路整体不读写，这是部署的合法状态，不该被说成「配置错」。

    注意 EnvConfig.LLM_API_KEY 是真实 .env 里读进来的值，测试必须显式清空。
    """
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://open.bigmodel.cn/api/paas/v4", raising=False)
    结果 = 检查嵌入配置()
    assert 结果["同源"] == "未知"
    assert "未配置可用的 embedding Key" in 结果["说明"]


def test_占位Key同样算未配置(monkeypatch):
    """"your_llm_api_key" 这种占位串不能算「配了 Key」。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "your_llm_api_key", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)
    assert 检查嵌入配置()["同源"] == "未知"


def test_有Key无端点判不同源(monkeypatch):
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "real-key", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "", raising=False)
    结果 = 检查嵌入配置()
    assert 结果["同源"] is False
    assert "未配置 embedding 端点" in 结果["说明"]


def test_缺省模型名打非OpenAI端点判不同源(monkeypatch):
    """本测试要钉住的核心场景：E2E 实测撞见的那个假绿灯。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "real-key", raising=False)

    结果 = 检查嵌入配置()

    assert 结果["同源"] is False
    assert 结果["模型"] == "text-embedding-3-small"
    assert 结果["模型来源"] == "缺省值 text-embedding-3-small"
    assert 结果["端点来源"] == "LLM_BASE_URL（回落）"
    assert 结果["键来源"] == "LLM_API_KEY（回落）"
    # 说明里必须同时给出「错在哪」和「怎么改」，否则运维看不懂
    assert "LLM_EMBEDDING_MODEL" in 结果["说明"]
    assert "open.bigmodel.cn" in 结果["说明"]


def test_缺省模型名打OpenAI官方端点判同源(monkeypatch):
    """没配 LLM_EMBEDDING_MODEL 但端点就是 OpenAI → 缺省模型名有效，不该报警。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://api.openai.com/v1", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "sk-real", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)
    结果 = 检查嵌入配置()
    assert 结果["同源"] is True
    assert "OpenAI 官方" in 结果["说明"]


def test_AzureOpenAI端点也算官方(monkeypatch):
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://x.openai.azure.com/openai", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "sk-real", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)
    assert 检查嵌入配置()["同源"] is True


def test_三项显式配置齐备判同源(monkeypatch):
    """模型名显式配了就不做域名猜测——自建网关也可能有这个模型。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://emb.example.com/v1", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "bge-large-zh", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "emb-key", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)
    结果 = 检查嵌入配置()
    assert 结果["同源"] is True
    assert 结果["模型来源"] == "LLM_EMBEDDING_MODEL"
    # 同源 ≠ 真能调通，必须在说明里把这句话说出来，别让运维误读成「已验证」
    assert "需一次真实调用验证" in 结果["说明"]


def test_端点尾部斜杠归一后仍同源(monkeypatch):
    """embedding_settings 已做 rstrip("/")，指纹与自检都靠等值比较，别被一个斜杠带偏。"""
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "https://api.openai.com/v1/", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "sk-real", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)
    结果 = 检查嵌入配置()
    assert 结果["端点"] == "https://api.openai.com/v1"
    assert 结果["同源"] is True


# ═══════════════════════════════════════════════════════════════
# 三、绝不触网（这条如果破了，探活会变成计费调用）
# ═══════════════════════════════════════════════════════════════


def test_自检全程不发网络请求(monkeypatch):
    """monkeypatch requests.post 为炸弹：只要自检碰了网络就立刻炸。"""
    import requests

    def 炸弹(*args, **kwargs):  # pragma: no cover - 只在实现走错时触发
        raise AssertionError("检查嵌入配置 不允许发网络请求")

    monkeypatch.setattr(requests, "post", 炸弹)
    monkeypatch.setattr(llm_client.requests, "post", 炸弹)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "sk-real", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "", raising=False)
    assert 检查嵌入配置()["同源"] is False


# ═══════════════════════════════════════════════════════════════
# 四、/healthz.memory 暴露（这才是自检能被看见的地方）
# ═══════════════════════════════════════════════════════════════


def test_记忆状态带出嵌入配置结论(monkeypatch):
    """/healthz 的 memory 块必须同时报「库健康」和「配置同源」两件事。

    钉住这条是因为阶段 61 已经栽过一次：「ok=true 只代表库可读」这件事在 docstring
    里写清了，但 /healthz 的字段里没有任何一个能让人看出 embedding 调不通——
    于是真机实测里监控全绿、记忆零工作。
    """
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_BASE_URL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_MODEL", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_EMBEDDING_API_KEY", "", raising=False)
    monkeypatch.setattr(EnvConfig, "LLM_API_KEY", "real-key", raising=False)

    状态 = memory.记忆状态()

    assert 状态["嵌入配置同源"] is False
    assert 状态["嵌入配置说明"]
    # 【关键行】ok 的语义不许被改：它仍然是「库可读」，配置问题走独立键。
    # 改 ok 的后果：库好好的但配置错了会和磁盘坏了在告警里混成同一条。
    assert 状态["ok"] in (True, False)
    assert "库可读" in memory.记忆状态.__doc__


def test_记忆状态自检失败不抛(monkeypatch):
    """配置自检本身炸了不能让 /healthz 挂——探活挂掉会误导成「服务整体不可用」。"""
    def 炸弹():
        raise RuntimeError("配置自检内部故障")

    monkeypatch.setattr(llm_client, "检查嵌入配置", 炸弹)
    # memory.记忆状态 里是**函数内** import（避免模块级循环依赖），
    # 所以补丁打在 llm_client 上就够——调用时才解析这个属性。
    状态 = memory.记忆状态()
    assert 状态["嵌入配置同源"] == "未知"
    assert "配置自检失败" in 状态["嵌入配置说明"]