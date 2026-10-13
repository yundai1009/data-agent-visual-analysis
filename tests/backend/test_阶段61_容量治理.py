# -*- coding: utf-8 -*-
"""阶段 61 · Task 2：向量记忆容量治理（单用户配额 + 全库硬上限 + 水位摊销）。

改之前的 `清理记忆(keep=5000)` 只有一把全局尺子，多租户下有两个结构性问题：

  1. **写放大**：它在编排器里是「每保存一条记忆就跑一次」，每次都
     `col.get(include=["metadatas"])` 把整库拉进内存 → O(全库) per write。
  2. **配额不公**：全局只留 5000 条时，挤掉的一定是「全库最旧」的那些，也就是
     早期用户的历史；一个疯狂分析的重用户就能把别人的记忆全删光。

本文件用假集合（不连真 chromadb）验证改造后的三件事：① 单用户配额只裁自己；
② 水位没到时**一次 col.get() 都不发**（摊销是本 Task 的核心论点，必须有用例钉住）；
③ 分层裁剪之后全局硬上限依然兜得住底，且两轮裁剪不会把同一个 id 删两遍。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from config.settings import EnvConfig
from 后端_核心.agent import memory


# ═══════════════════════════════════════════════════════════════
# 假集合：只实现 清理记忆 真正用到的那几个方法
# ═══════════════════════════════════════════════════════════════


class 假集合:
    """chromadb.Collection 的最小替身。

    真实 `col.get()` 会把整库 metadata 读进内存——这正是本 Task 要摊销的成本，
    所以假集合必须**如实记账**：调了几次 get、删了哪些 id，一笔不漏，
    用例才能断言「水位没到时真的没扫全库」。
    """

    def __init__(self, 条目: List[Tuple[str, str, str]]):
        # 条目元素 = (id, user_id, created_at)
        self.条目: List[Tuple[str, str, str]] = list(条目)
        self.次数: Dict[str, int] = {"get": 0, "delete": 0}
        self.删除的ids: List[str] = []

    # -- 测试可读的快照 --
    @property
    def 剩余(self) -> List[str]:
        return [x[0] for x in self.条目]

    @staticmethod
    def _元数据(条: Tuple[str, str, str]) -> Dict[str, Any]:
        return {"user_id": 条[1], "created_at": 条[2]}

    # -- chromadb.Collection 接口 --
    def count(self) -> int:
        return len(self.条目)

    def get(self, include: Any = None, where: Any = None) -> Dict[str, Any]:
        self.次数["get"] += 1
        命中 = self.条目
        if where:
            命中 = [x for x in 命中
                    if all(self._元数据(x).get(k) == v for k, v in where.items())]
        return {
            "ids": [x[0] for x in 命中],
            "metadatas": [self._元数据(x) for x in 命中],
        }

    def delete(self, ids: Any = None) -> None:
        self.次数["delete"] += 1
        待删 = set(ids or [])
        self.删除的ids.extend(ids or [])
        self.条目 = [x for x in self.条目 if x[0] not in 待删]


def _装(monkeypatch: pytest.MonkeyPatch, 集合: 假集合, 步长: int = 1, 全局上限: int = 1000) -> 假集合:
    """把 清理记忆 接到假集合上，并把容量配置钉死（避免读到开发机 .env 的真实值）。"""
    monkeypatch.setattr(memory, "_get_collection", lambda: 集合)
    monkeypatch.setattr(memory, "_清理水位", 0, raising=False)
    monkeypatch.setattr(EnvConfig, "MEMORY_CLEAN_STEP", 步长, raising=False)
    monkeypatch.setattr(EnvConfig, "MEMORY_TOTAL_LIMIT", 全局上限, raising=False)
    return 集合


# ═══════════════════════════════════════════════════════════════
# 一、单用户配额：只裁自己，绝不动别人的
# ═══════════════════════════════════════════════════════════════


def test_单用户超限只删自己最旧的(monkeypatch):
    """u1 有 3 条、每人上限 2 → 删掉 u1 里 created_at 最旧的那条，返回 1。"""
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u1", "2026-10-02"),
        ("m3", "u1", "2026-10-03"),
    ]))
    assert memory.清理记忆(每人上限=2) == 1
    assert 集.删除的ids == ["m1"]
    assert 集.剩余 == ["m2", "m3"]


def test_各用户不超限不删(monkeypatch):
    """每人都 ≤ 上限 → 返回 0，一次 delete 都不该发。"""
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u2", "2026-10-02"),
        ("m3", "u1", "2026-10-03"),
    ]))
    assert memory.清理记忆(每人上限=2, 全局上限=100) == 0
    assert 集.删除的ids == []
    assert 集.次数["delete"] == 0


def test_重用户不吃掉别人配额(monkeypatch):
    """u1 刷了 5 条、u2 只有 1 条：裁掉的必须全是 u1 的，u2 一条都不能少。

    这条是旧实现最痛的回归：全局 keep=5000 一撞顶，删的就是全库最旧的，
    于是「谁用得少谁先被删光」，被删的永远是早期用户。
    """
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u1", "2026-10-02"),
        ("m3", "u1", "2026-10-03"),
        ("m4", "u1", "2026-10-04"),
        ("m5", "u1", "2026-10-05"),
        ("m6", "u2", "2026-10-06"),
    ]))
    assert memory.清理记忆(每人上限=2, 全局上限=100) == 3
    assert 集.删除的ids == ["m1", "m2", "m3"]
    assert 集.剩余 == ["m4", "m5", "m6"]
    assert "m6" not in 集.删除的ids  # u2 的唯一一条，纹丝不动


def test_不传参时回落环境配置(monkeypatch):
    """两个上限都走 EnvConfig 默认值——且必须是**调用时**读（见下面那条用例）。"""
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u1", "2026-10-02"),
        ("m3", "u1", "2026-10-03"),
    ]))
    monkeypatch.setattr(EnvConfig, "MEMORY_PER_USER_LIMIT", 1, raising=False)
    assert memory.清理记忆() == 2
    assert 集.删除的ids == ["m1", "m2"]


# ═══════════════════════════════════════════════════════════════
# 二、水位摊销：核心论点——水位没到时一次全库扫描都不许发
# ═══════════════════════════════════════════════════════════════


def test_水位未到不扫全库(monkeypatch):
    """count() < _清理水位 → 返回 0，且 col.get() 调用次数必须是 0。

    这条钉住的是整个 Task 的价值：编排器每保存一条记忆就调一次 清理记忆，
    不门控就是每次写入一次全库扫描（O(n) 写放大）。
    """
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u1", "2026-10-02"),
        ("m3", "u1", "2026-10-03"),
    ]), 步长=50, 全局上限=1000)
    monkeypatch.setattr(memory, "_清理水位", 100)  # 水位远高于当前条数
    assert memory.清理记忆(每人上限=2) == 0
    assert 集.次数["get"] == 0
    assert 集.删除的ids == []


def test_扫过一次后水位推进后续写入不再扫全库(monkeypatch):
    """水位推进公式 = total + MEMORY_CLEAN_STEP：3 条扫完抬到 3+50，接下来 50 次写入零扫描。"""
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u1", "2026-10-02"),
        ("m3", "u1", "2026-10-03"),
    ]), 步长=50, 全局上限=1000)
    assert memory.清理记忆(每人上限=2) == 1
    assert 集.次数["get"] == 1
    assert memory._清理水位 == 3 + 50
    # 库没再长（还是 3 条 < 水位 53）→ 这次直接 O(1) 返回，连 get 都不发
    assert memory.清理记忆(每人上限=2) == 0
    assert 集.次数["get"] == 1


def test_步长配成0不会退化成每次全扫(monkeypatch):
    """max(1, 步长) 是防呆：MEMORY_CLEAN_STEP=0 时水位只推进 total，不会卡死在 0。"""
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u1", "2026-10-02"),
    ]), 步长=0, 全局上限=1000)
    assert memory.清理记忆(每人上限=2) == 0
    assert memory._清理水位 == 2 + 1


# ═══════════════════════════════════════════════════════════════
# 三、全局硬上限：分层之后仍要兜得住底
# ═══════════════════════════════════════════════════════════════


def test_全局硬上限仍生效(monkeypatch):
    """单用户上限给得很宽（10），但全局上限=3 → 仍要降到 3 条。"""
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u2", "2026-10-02"),
        ("m3", "u3", "2026-10-03"),
        ("m4", "u4", "2026-10-04"),
    ]), 步长=1, 全局上限=3)
    assert memory.清理记忆(每人上限=10, 全局上限=3) == 1
    assert 集.删除的ids == ["m1"]
    assert 集.剩余 == ["m2", "m3", "m4"]


def test_全局裁剪不与单用户裁剪重复计数(monkeypatch):
    """两轮裁剪叠加：4 条归 1 人、每人 2 → 删 2；全局 2 → 再删 2，总共 4，不能重号。

    没排除已选 id 的话，全局那轮会把刚删掉的 id 再塞进 delete，返回条数虚高，
    线上表现为「日志说删了 6 条，库却少了 5 条」——最容易被当成 chroma 抽风。
    """
    集 = _装(monkeypatch, 假集合([
        ("m1", "u1", "2026-10-01"),
        ("m2", "u1", "2026-10-02"),
        ("m3", "u1", "2026-10-03"),
        ("m4", "u1", "2026-10-04"),
    ]), 步长=1, 全局上限=2)
    assert memory.清理记忆(每人上限=2, 全局上限=2) == 2
    assert sorted(集.删除的ids) == ["m1", "m2"]
    assert 集.剩余 == ["m3", "m4"]


# ═══════════════════════════════════════════════════════════════
# 四、兜底：记忆是可降级依赖，清理出问题绝不能冒泡
# ═══════════════════════════════════════════════════════════════


def test_空库不抛(monkeypatch):
    """count() 返回 0 → 返回 0。"""
    集 = _装(monkeypatch, 假集合([]))
    assert memory.清理记忆() == 0
    assert 集.删除的ids == []


def test_扫描失败只告警不抛(monkeypatch):
    """col.get() 炸了（磁盘/索引故障）→ 吞掉异常返回 0，分析主流程照跑。"""
    class 坏集合(假集合):
        def get(self, include=None, where=None):
            self.次数["get"] += 1
            raise RuntimeError("chroma 炸了")

    集 = _装(monkeypatch, 坏集合([("m1", "u1", "2026-10-01")]), 步长=1, 全局上限=1000)
    assert memory.清理记忆(每人上限=0) == 0