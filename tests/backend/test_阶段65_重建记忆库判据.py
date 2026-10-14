# -*- coding: utf-8 -*-
"""阶段 65：`scripts/重建记忆库.py` 的判据必须是**指纹**，不是条数（缺陷 F5/F6）。

这两个缺陷都是拿真机自检（`scripts/自检记忆库.py`）跑出来的，不是代码走查想出来的。
现场是同一条死链：

    阶段 63 撞出 F1：`.env` 三项 `LLM_EMBEDDING_*` 都没配，`embed_text()` 回落成
    「OpenAI 的缺省模型名 + 智谱的端点」→ HTTP 400/code 1211 → 被 llm_client 静默吞掉
    → 记忆库永远是 0 条，但 metadata 里已经盖上了那个**假的缺省指纹**。

    F5：阶段 65 把模型配成 `embedding-3` 之后，真库当场变成「0 条 + 指纹不一致」：
        `校验记忆库一致性()` 按指纹抛 RuntimeError → 启动硬闸报错让人跑本脚本 →
        本脚本按 `条数 == 0` 回一句「[OK] 记忆库为空，无需重建。」→ 闸门照旧拒启动。
        **闸门与工具互相指着对方**，运维解不开。
        死局根因不在闸门，在工具的判据：判据必须是指纹，空库不等于指纹一致。

    F6：collection 压根不存在时（全新装机），`--yes` 走到无条件 `client.delete_collection()`
        → chromadb 抛 `NotFoundError: Collection [agent_memories] does not exist`
        → 脚本带 traceback 退出。也就是说 F5 的修复把「0 条」这条路径显式引向了 `--yes`，
        不修 F6 就等于**修完 F5 反而给新装机的用户造了一个崩溃点**。

本测试钉住四类：判据（三种库状态的分支）、F6（库不存在时不删）、保护条款
（`--dry-run` 不动库、没开关直接报错、Key 是占位符时什么都不删就退出 2）、
以及文案准确性（0 条的两种成因必须分开说）。
"""

from __future__ import annotations

import sys

import pytest

import scripts.重建记忆库 as 脚本
from 后端_核心.agent import memory

当前端点 = "https://example.invalid/v1"
当前模型 = "embedding-3"
旧模型名 = "text-embedding-3-small"

# 哨兵：库内指纹得在**打桩之后**算，否则拿到的是真 `.env` 那一份配置，
# 与脚本看到的世界不是同一个——那样测的就不是判据，而是桩子对不齐了。
库内一致 = object()
库内旧模型 = object()


# ═══════════════════════════════════════════════════════════════
# 一、假 chroma 客户端：只实现本脚本真正调到的三个方法
# ═══════════════════════════════════════════════════════════════
class 假Collection:
    def __init__(self, metadata=None, 条数=0):
        self.metadata = dict(metadata) if metadata else {}
        self._条数 = 条数
        self.改过 = []

    def count(self) -> int:
        return self._条数

    def modify(self, metadata=None):
        self.metadata = dict(metadata or {})
        self.改过.append(self.metadata)


class 假客户端:
    """记录删/建两个动作，测试据此断言「到底动没动用户的记忆」。

    ``元数据为 None`` 表示 **collection 不存在**（全新装机）：get_collection 抛异常，
    这是 chromadb 的真实行为（NotFoundError），不是我们编出来的特例。
    """

    def __init__(self, 元数据=None, 条数=0):
        self.元数据 = 元数据
        self.条数 = 条数
        self.删过 = []
        self.建过 = []

    def get_collection(self, 名字):
        if self.元数据 is None:
            raise RuntimeError("Collection [agent_memories] does not exist")
        return 假Collection(self.元数据, self.条数)

    def delete_collection(self, 名字):
        self.删过.append(名字)
        self.元数据 = None

    def create_collection(self, 名字, metadata=None):
        self.建过.append((名字, dict(metadata or {})))
        self.元数据 = dict(metadata or {})
        return 假Collection(self.元数据, 0)


@pytest.fixture()
def 假库(monkeypatch):
    """装好假的 client / embedding 配置，跑完把 memory 的进程内单例还原。

    ``memory.embedding_settings`` 必须一起打桩：``当前指纹()`` 是从 memory 自己
    导入的那个函数读配置的，只补脚本那一份的话，两边会从两个世界取配置。
    """

    def 装(库内=库内一致, 条数=0, 有Key=True, 端点尾斜杠=False):
        键 = "sk-真key" if 有Key else ""
        # 先打桩，再算指纹——顺序不能反（见「库内一致」哨兵的注释）
        monkeypatch.setattr(memory, "_collection", None, raising=False)
        monkeypatch.setattr(memory, "embedding_settings", lambda: (当前端点, 当前模型, 键))
        monkeypatch.setattr(脚本, "embedding_settings", lambda: (当前端点, 当前模型, 键))
        monkeypatch.setattr(脚本, "is_llm_configured", lambda key=None: bool(有Key))

        if 库内 is 库内一致:
            元数据 = dict(memory.当前指纹())
        elif 库内 is 库内旧模型:
            元数据 = dict(memory.当前指纹())
            元数据["embedding模型"] = 旧模型名
        else:
            元数据 = 库内  # None = 库不存在；dict 原样用
        if 端点尾斜杠 and 元数据 is not None:
            元数据 = {**元数据, "embedding端点": 当前端点 + "/"}

        客户端 = 假客户端(元数据, 条数)
        monkeypatch.setattr(memory, "_get_client", lambda: 客户端)
        return 客户端

    yield 装
    monkeypatch.setattr(memory, "_collection", None, raising=False)


def 跑(开关: str, capsys) -> tuple[int, str]:
    sys.argv = ["重建记忆库.py", 开关]
    码 = 脚本.main()
    return 码, capsys.readouterr().out


# ═══════════════════════════════════════════════════════════════
# 二、F5：判据是指纹，不是条数
# ═══════════════════════════════════════════════════════════════
def test_空库但指纹旧_不再回无需重建(假库, capsys):
    """F5 的现场：0 条 + 库内是 F1 留下的假缺省指纹。

    红灯判据：修复前这里返回的是「[OK] 记忆库为空，无需重建」+ 退出码 0——
    看起来一切正常，服务却照旧起不来。
    """
    假库(库内旧模型, 条数=0)
    码, 输出 = 跑("--dry-run", capsys)
    assert "无需重建" not in 输出, "0 条不等于指纹一致——这就是 F5 的死局"
    assert "重新盖章" in 输出
    assert "不一致" in 输出
    assert 码 == 0


def test_空库但指纹旧_dryRun不删库(假库, capsys):
    """--dry-run 的老约定：一个字节都不能动用户的记忆。"""
    客户端 = 假库(库内旧模型, 条数=0)
    跑("--dry-run", capsys)
    assert 客户端.删过 == []
    assert 客户端.建过 == []


def test_空库但指纹旧_yes只重建不删数据(假库, capsys):
    """0 条时 --yes 该把状态归正（重新盖章），且如实说成「0 条未受影响」。"""
    客户端 = 假库(库内旧模型, 条数=0)
    码, 输出 = 跑("--yes", capsys)
    assert 码 == 0
    assert "已重新盖章" in 输出 and "0 条数据未受影响" in 输出
    assert 客户端.删过 == [memory._COLLECTION_NAME]
    assert 客户端.建过 and 客户端.建过[0][1]["embedding模型"] == 当前模型


def test_有数据且指纹旧_如实报删除条数(假库, capsys):
    """有数据时不能走「0 条未受影响」那套话术。"""
    假库(库内旧模型, 条数=12)
    码, 输出 = 跑("--yes", capsys)
    assert 码 == 0
    assert "已重建" in 输出 and "12 条历史记忆已删除" in 输出
    assert "未受影响" not in 输出


def test_指纹一致_什么都不做(假库, capsys):
    """指纹已是当前配置：连重建都不该做（重建会把可用的记忆清空）。"""
    客户端 = 假库(库内一致, 条数=7)
    码, 输出 = 跑("--yes", capsys)
    assert 码 == 0
    assert "无需重建" in 输出
    assert 客户端.删过 == [] and 客户端.建过 == []


def test_末尾斜杠不算换模型(假库, capsys):
    """运维在 .env 里多打一个 '/' 不该被当成换了语义空间。

    归一化在 `memory.校验指纹`（`memory.py:115` 的 `.strip().rstrip("/")`）里，
    本脚本复用 `_指纹一致判定` 就等于继承了这条约定——这里钉住它别被绕过去。
    """
    客户端 = 假库(库内一致, 条数=3, 端点尾斜杠=True)
    码, 输出 = 跑("--dry-run", capsys)
    assert 码 == 0 and "无需重建" in 输出
    assert 客户端.删过 == []


# ═══════════════════════════════════════════════════════════════
# 三、F6：collection 不存在时不能无条件 delete
# ═══════════════════════════════════════════════════════════════
def test_全新库_yes不崩且只新建(假库, capsys):
    """全新装机：get_collection 必然抛 NotFoundError。

    红灯判据：修复前这里直接抛
        chromadb.errors.NotFoundError: Collection [agent_memories] does not exist
    脚本带 traceback 退出，运维看到的是「重建脚本坏了」而不是「库本来就是空的」。
    """
    客户端 = 假库(None)
    码, 输出 = 跑("--yes", capsys)
    assert 码 == 0
    assert 客户端.删过 == [], "库压根不存在，delete_collection 只会抛 NotFoundError"
    assert 客户端.建过 and 客户端.建过[0][0] == memory._COLLECTION_NAME
    assert "重新盖章" in 输出


def test_全新库_文案区分没盖过章与盖错了(假库, capsys):
    """两种 0 条必须分开说：

    · 指纹未知 = 压根没盖过章（全新库，或阶段 61 之前的老库）
    · 指纹不一致 = 上一份配置留下的

    混成一句话就是在给运维一个错的因果判断。
    """
    假库(None)
    _, 新库输出 = 跑("--dry-run", capsys)
    假库(库内旧模型, 条数=0)
    _, 旧库输出 = 跑("--dry-run", capsys)
    assert "一个指纹字段都没有" in 新库输出
    assert "一个指纹字段都没有" not in 旧库输出
    assert "不一致" in 旧库输出


# ═══════════════════════════════════════════════════════════════
# 四、保护条款：不能因为修判据而放松
# ═══════════════════════════════════════════════════════════════
def test_不给开关直接报错退出(假库, capsys):
    """只敲脚本名就回车的人，不该因此丢掉整库历史。"""
    客户端 = 假库(库内一致, 条数=5)
    sys.argv = ["重建记忆库.py"]
    with pytest.raises(SystemExit):
        脚本.main()
    assert 客户端.删过 == []


def test_Key是占位符_什么都不删就退出2(假库, capsys):
    """删库之后依然存不进新记忆，是比「指纹不一致」更糟的状态。"""
    客户端 = 假库(库内旧模型, 条数=9, 有Key=False)
    码, 输出 = 跑("--yes", capsys)
    assert 码 == 2
    assert "Key" in 输出
    assert 客户端.删过 == [] and 客户端.建过 == []