# -*- coding: utf-8 -*-
"""阶段七十 · 执行态检查点仓储层红灯测试（四态：存 / 取 / 消费 / 过期）。

测试跑在 SQLite（tests/conftest.py 不覆盖 DB_BACKEND），MySQL 分支由
test_后端分发 一类的既有用例覆盖；这里只锁 sqlite 侧的业务语义。
"""
import json

import pytest

from repositories import checkpoint_repo as 检查点


@pytest.fixture(autouse=True)
def _临时库(tmp_path, monkeypatch):
    """把 sqlite 指向 tmp_path，并清掉「进程级已初始化」缓存（否则别的用例建过表就算已初始化）。"""
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "检查点.db"))
    monkeypatch.setattr(检查点, "_检查点表已初始化", {})
    # 直接建真表：不走 初始化检查点表() 的「进程级一次性」缓存，避免与别的用例相互干扰。
    检查点._初始化检查点表全量()


def _存一轮(用户="u-1", 数据集="d-1", 需求="帮我分析一下销售情况", 轮次=1, 消息=None):
    return 检查点.保存检查点(
        user_id=用户,
        dataset_id=数据集,
        requirement=需求,
        profile={"行数": 100, "数值字段": ["销售额"]},
        messages=消息 or [{"role": "user", "content": 需求}],
        已完成轮次=轮次,
        rule_text="",
        model="glm-4",
    )


def test_保存后能原样读回_画像与messages都不丢():
    检查点ID = _存一轮(轮次=1)
    取到 = 检查点.读取检查点("u-1", "帮我分析一下销售情况")
    assert 取到 is not None
    assert 取到["检查点ID"] == 检查点ID
    assert 取到["轮次"] == 1
    assert 取到["画像"]["行数"] == 100
    assert 取到["画像"]["数值字段"] == ["销售额"]
    assert 取到["messages"][0]["content"] == "帮我分析一下销售情况"
    assert 取到["模型"] == "glm-4"
    assert 取到["状态"] == "可用"


def test_同一键重复保存只更新同一行_不堆行():
    检查点ID = _存一轮(轮次=1)
    消息 = [{"role": "user", "content": "帮我分析一下销售情况"},
            {"role": "tool", "content": "画像：4 列"}]
    检查点.保存检查点(
        user_id="u-1",
        dataset_id="d-1",
        requirement="帮我分析一下销售情况",
        profile={"行数": 100, "数值字段": ["销售额"], "已更新": True},
        messages=消息,
        已完成轮次=2,
    )
    取到 = 检查点.读取检查点("u-1", "帮我分析一下销售情况")
    assert 取到["检查点ID"] == 检查点ID
    assert 取到["轮次"] == 2
    assert 取到["画像"]["已更新"] is True
    assert len(取到["messages"]) == 2


def test_读取必须按用户隔离_跨用户读不到():
    _存一轮(用户="u-甲")
    assert 检查点.读取检查点("u-甲", "帮我分析一下销售情况") is not None
    assert 检查点.读取检查点("u-乙", "帮我分析一下销售情况") is None


def test_需求不同也不串味():
    _存一轮(需求="看华南区")
    assert 检查点.读取检查点("u-1", "看华东区") is None
    assert 检查点.读取检查点("u-1", "看华南区") is not None


def test_消费后不再续跑():
    检查点ID = _存一轮()
    assert 检查点.消费检查点(检查点ID) is True
    assert 检查点.读取检查点("u-1", "帮我分析一下销售情况") is None


def test_重复消费是安全的_第二次返回False():
    检查点ID = _存一轮()
    assert 检查点.消费检查点(检查点ID) is True
    assert 检查点.消费检查点(检查点ID) is False


def test_过期存档不续跑_且被就地标记():
    _存一轮(轮次=1)
    # 直接把 expires_at 改到过去：等价于「存了 31 分钟之后用户才回来」
    with 检查点._get_conn() as conn:
        conn.execute("UPDATE checkpoints SET expires_at = ? WHERE user_id = ?",
                     ("2020-01-01T00:00:00+00:00", "u-1"))
    assert 检查点.读取检查点("u-1", "帮我分析一下销售情况") is None
    with 检查点._get_conn() as conn:
        row = conn.execute("SELECT status FROM checkpoints WHERE user_id = ?", ("u-1",)).fetchone()
    assert row["status"] == "已过期"


def test_过期后可重新存档并续跑():
    _存一轮(轮次=1)
    with 检查点._get_conn() as conn:
        conn.execute("UPDATE checkpoints SET expires_at = ? WHERE user_id = ?",
                     ("2020-01-01T00:00:00+00:00", "u-1"))
    检查点.读取检查点("u-1", "帮我分析一下销售情况")   # 触发过期标记
    新ID = _存一轮(轮次=1)
    取到 = 检查点.读取检查点("u-1", "帮我分析一下销售情况")
    assert 取到 is not None and 取到["检查点ID"] == 新ID


def test_清理过期检查点():
    _存一轮(轮次=1)
    assert 检查点.清理过期检查点() == 0
    with 检查点._get_conn() as conn:
        conn.execute("UPDATE checkpoints SET expires_at = ? WHERE user_id = ?",
                     ("2020-01-01T00:00:00+00:00", "u-1"))
    assert 检查点.清理过期检查点() == 1
    assert 检查点.清理过期检查点() == 0


def test_删除检查点():
    _存一轮(需求="看华南区")
    _存一轮(需求="看华东区")
    assert 检查点.删除检查点("u-1") == 2
    assert 检查点.读取检查点("u-1", "看华南区") is None


def test_删除检查点可按需求收窄():
    _存一轮(需求="看华南区")
    _存一轮(需求="看华东区")
    assert 检查点.删除检查点("u-1", requirement="看华南区") == 1
    assert 检查点.读取检查点("u-1", "看华南区") is None
    assert 检查点.读取检查点("u-1", "看华东区") is not None


def test_messages能存下多轮对话_中文不丢():
    检查点.保存检查点(
        user_id="u-1",
        dataset_id="d-1",
        requirement="华南区销售额为什么下滑",
        profile={"列名": ["地区", "销售额"]},
        messages=[
            {"role": "system", "content": "你是数据分析师"},
            {"role": "user", "content": "华南区销售额为什么下滑"},
            {"role": "assistant", "content": None,
             "tool_calls": [{"id": "call_1", "function": {"name": "聚合分析", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "call_1", "content": "华南: 408500"},
        ],
        已完成轮次=2,
    )
    取到 = 检查点.读取检查点("u-1", "华南区销售额为什么下滑")
    assert [m["role"] for m in 取到["messages"]] == ["system", "user", "assistant", "tool"]
    assert 取到["messages"][3]["content"] == "华南: 408500"
    # 落库必须是合法 JSON（不是 Python repr）
    with 检查点._get_conn() as conn:
        row = conn.execute("SELECT messages_json FROM checkpoints WHERE user_id = ?", ("u-1",)).fetchone()
    json.loads(row["messages_json"])
