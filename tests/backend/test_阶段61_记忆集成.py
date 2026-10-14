# -*- coding: utf-8 -*-
"""阶段 61 · Task 3：记忆模块真 chromadb 集成测试（此前零覆盖）。

此前 tests/ 下所有涉及记忆的用例都把记忆链路打了桩
（test_llm_vcr.py:107-114 / test_修复LLM路径筛选丢失.py:92 / test_修复追问上下文劫持.py:72 /
  test_阶段54_9_VCR轮2指纹.py:48 / test_agent_意图.py:400），
所以「同一 collection 混入不同语义空间的向量」这类问题在 CI 上**结构性地发现不了**：
桩掉的 client 不会抛 NotFoundError、不会真的写盘、where 过滤永远是假函数的 if。
本文件用**真 chromadb + 假 embedding** 把这条链路打满。

为什么 embedding 可以打桩、chromadb 不行
=========================================
embedding 是**外部 HTTP 服务**（要网络、要真 Key、还带随机性），打桩是对的；
chromadb 是**本地嵌入式数据库**，它自己的行为（collection 不存在时抛什么、
metadata 写不写得进去、where 过滤是不是真过滤）恰恰是被桩掉之后看不见的部分——
桩只能证明「我们调用了 get_collection」，证明不了「真库调得通」。

覆盖点：存进去取得回 / 按用户隔离 / 同需求累积 / 注销级联 / 容量按用户分层 /
建库写指纹 / 指纹不一致时拒绝且不污染全局。
"""
from __future__ import annotations

import pytest

from config.settings import EnvConfig
from 后端_核心.agent import memory


def 假嵌入(文本: str):
    """确定性假 embedding：共享字符越多向量越接近，用来验证召回顺序。

    必须是**确定性**的：真 embedding 有随机性，同一段文本两次向量化不完全相同，
    用例断言就只能在很大概率上成立——那种测试偶尔红的排障成本远高于它能发现的问题。
    取模 32 是为了让不同汉字大概率落在不同维度上，仍然共享足够多字符的两段文本
    会得到更近的向量，足够验证「召回顺序」这件事。
    """
    向量 = [0.0] * 32
    for 字 in 文本:
        向量[ord(字) % 32] += 1.0
    总和 = sum(向量) or 1.0
    return [v / 总和 for v in 向量]


@pytest.fixture
def 记忆库(monkeypatch, tmp_path):
    """真 chromadb + 临时目录 + 假 embedding + 清掉进程内单例。

    为什么每个用例都要重置单例：`_client` / `_collection` 是**模块级**缓存，
    跨用例复用就等于「A 用例建的库被 B 用例当成自己的」——而 A 的 tmp_path 早就被删了，
    表现是 B 莫名其妙地读写失败。所以这里既要在开跑前清，还要在收尾时清。
    """
    monkeypatch.setattr(memory, "_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(memory, "_client", None, raising=False)
    monkeypatch.setattr(memory, "_collection", None, raising=False)
    monkeypatch.setattr(memory, "_清理水位", 0, raising=False)
    monkeypatch.setattr(memory, "_记忆状态", {"最近错误": ""}, raising=False)
    monkeypatch.setattr(memory, "embed_text", 假嵌入)
    monkeypatch.setattr(EnvConfig, "MEMORY_PER_USER_LIMIT", 2, raising=False)
    yield
    memory._client = None
    memory._collection = None


def _存(用户, 需求):
    return memory.保存记忆(
        用户, 需求, {"图表类型": "柱状图", "x轴": "区域", "聚合方式": "求和"}, "100行/5列"
    )


def test_存进去取得回(记忆库):
    """存进去再取回来——最基础的一环。

    断言 metadata 字段（图表类型/x轴）能从真库回读：桩掉的集合返回什么都是自己写的，
    只有真库才会在 metadata 往返中真的丢字段（比如值不是合法 metadata 类型时被 chroma 拒绝）。
    """
    assert _存("u1", "各区域销售额") is True
    结果 = memory.检索相似记忆("u1", "各区域销售额")
    assert [r["需求"] for r in 结果] == ["各区域销售额"]
    assert 结果[0]["图表类型"] == "柱状图"
    assert 结果[0]["x轴"] == "区域"


def test_按用户隔离(记忆库):
    """where={"user_id": ...} 在**真库**上真的过滤了——这是 P0 隔离，漏了就是跨用户泄漏。

    这是本文件里最不能打桩的一条：桩库可以随手返回一个固定列表，桩测试永远绿；
    真库才会在 `where` 过滤写错时把别人的记忆原样端出来。
    """
    _存("u1", "各区域销售额")
    _存("u2", "各区域利润")
    assert [r["需求"] for r in memory.检索相似记忆("u1", "各区域销售额")] == ["各区域销售额"]
    assert [r["需求"] for r in memory.检索相似记忆("u2", "各区域利润")] == ["各区域利润"]


def test_同需求反复分析会累积(记忆库):
    """同一个需求跑多次要积累多条经验，而不是互相覆盖。

    id 用的是 uuid4().hex——如果哪天有人「顺手」改成按需求去重，
    这里会立刻从 2 掉到 1，把「记住每次分析」变成「只留最后一次」。
    """
    _存("u1", "各区域销售额")
    _存("u1", "各区域销售额")
    assert memory.记忆条数() == 2


def test_注销清空该用户且不动他人(记忆库):
    """注销是删**该用户**的全部记忆，不是清空整库——否则一个人注销全站记忆蒸发。"""
    _存("u1", "各区域销售额")
    _存("u1", "各区域利润")
    _存("u2", "各部门预算")
    assert memory.删除用户记忆("u1") == 2
    assert memory.检索相似记忆("u1", "各区域销售额") == []
    assert [r["需求"] for r in memory.检索相似记忆("u2", "各部门预算")] == ["各部门预算"]


def test_容量按用户分层(记忆库):
    """MEMORY_PER_USER_LIMIT=2：u1 存 3 条裁到 2，u2 的 1 条不动。

    跨用户不互相挤兑是这一版的全部意义——旧实现只有一把全局尺子，
    重用户会把早期用户的历史全删光，而这条断言（u2 还在）是唯一能钉住它的东西。
    """
    for 需求 in ("销售额趋势", "利润趋势", "成本趋势"):
        _存("u1", 需求)
    _存("u2", "各部门预算")
    assert memory.清理记忆() == 1
    assert memory.检索相似记忆("u2", "各部门预算") != []


def test_建库时写入embedding指纹(记忆库):
    """建库那一刻就把当前指纹写进 collection metadata——之后换模型才检得出。

    漏写出来的库是「老库」，而 老库在校验指纹 里是**缺字段按未知放行**的：
    于是它既没数据可丢、也没闸门管，是最坏的一种状态。
    """
    _存("u1", "各区域销售额")
    记录 = memory._get_collection().metadata
    assert 记录["embedding模型"] == (EnvConfig.LLM_EMBEDDING_MODEL or "text-embedding-3-small")


def test_指纹不一致时拒绝且不污染全局(记忆库, monkeypatch):
    """阶段 61 修复 B1 的回归锁（真库版本；桩版见 test_阶段61_记忆库一致性.py）。

    原缺陷（旧写法：先 `_collection = client.get_collection(...)`，**之后**才校验指纹）：
    校验抛错时全局已经被污染成「不一致的 collection」，函数开头的 fast-path 在第二次调用时
    直接返回它——**硬闸只响一次就被绕过**，此后同进程所有读写都落在不一致的语义空间里，
    而且 保存记忆/检索相似记忆 的 except 会把那次 RuntimeError 吞成 warning，调用方毫无感知。

    三条断言缺一不可：抛错（闸门仍响）／全局仍是 None（没被污染）／
    第二次调用仍然抛（没被 fast-path 绕过）。
    """
    # 先用当前配置把库建出来（真库，metadata 里是真写入的指纹）
    assert _存("u1", "各区域销售额") is True
    col = memory._get_collection()
    # 模拟「运维换了 embedding 模型」：把库内指纹改成错的模型
    col.modify(metadata={**col.metadata, "embedding模型": "wrong-model"})

    # 清掉进程内单例，逼它走真校验（fast-path 不再返回那个已知不一致的库）
    monkeypatch.setattr(memory, "_collection", None)

    with pytest.raises(RuntimeError) as 抓:
        memory._get_collection()
    assert "不在同一语义空间" in str(抓.value)

    # 【关键断言】全局没被污染
    assert memory._collection is None, (
        "指纹校验失败后全局 _collection 必须保持 None——"
        "被污染会让 fast-path 绕过硬闸（B1）"
    )
    # 第二次调用必须**再抛一次**：证明 fast-path 真的没被用上
    with pytest.raises(RuntimeError, match="不在同一语义空间"):
        memory._get_collection()
    assert memory._collection is None