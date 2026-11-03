# -*- coding: utf-8 -*-
"""阶段九十 · 单实例锁（第 7 道防线）专项测试。

背景：技术评审团 B1/B2 —— 原第 5 道防线只解析 CLI --workers，拦不住
「另开一个端口起的第二个进程」；本机实测曾有 8013 + 8021 同时写同一
data/chroma_db。本文件锁定 _获取单实例锁 / _尝试排它锁 的行为：

  1. 排它锁：第二个文件句柄拿不到（无论是否同一进程）；
  2. 同进程重复调用幂等（测试里反复建 TestClient 不受影响）；
  3. 目录被占用 → 拒绝启动（RuntimeError，含"另一个后端进程"文案）；
  4. 释放后重新可获取。
"""
import os

import pytest

from api import main


@pytest.fixture(autouse=True)
def _临时记忆目录(tmp_path, monkeypatch):
    """把记忆库目录指到临时目录，并复位模块级锁句柄，避免污染真实 data/。"""
    monkeypatch.setenv("DAA_CHROMA_PATH", str(tmp_path))
    monkeypatch.setattr(main, "_单实例锁句柄", None)
    yield
    if main._单实例锁句柄 is not None:
        try:
            main._单实例锁句柄.close()
        except OSError:
            pass
        main._单实例锁句柄 = None


def test_排它锁_第二个句柄拿不到(tmp_path):
    路径 = tmp_path / ".instance.lock"
    句柄a = open(路径, "a+", encoding="utf-8")
    句柄b = open(路径, "a+", encoding="utf-8")
    try:
        assert main._尝试排它锁(句柄a) is True
        assert main._尝试排它锁(句柄b) is False  # 另一句柄（哪怕同进程）拿不到
    finally:
        句柄a.close()
        句柄b.close()


def test_获取单实例锁_同进程重复调用幂等():
    main._获取单实例锁()  # 不应抛
    main._获取单实例锁()  # 幂等：本进程已持有 → 直接跳过
    assert main._单实例锁句柄 is not None


def test_获取单实例锁_目录被占用_拒绝启动(tmp_path):
    路径 = tmp_path / ".instance.lock"
    句柄 = open(路径, "a+", encoding="utf-8")
    try:
        assert main._尝试排它锁(句柄) is True
        with pytest.raises(RuntimeError, match="另一个后端进程"):
            main._获取单实例锁()
    finally:
        句柄.close()


def test_获取单实例锁_释放后可重新获取():
    main._获取单实例锁()
    if main._单实例锁句柄 is not None:
        main._单实例锁句柄.close()
        main._单实例锁句柄 = None
    main._获取单实例锁()  # 释放后不抛
    assert main._单实例锁句柄 is not None


def test_记忆库目录_默认回落_data_chroma():
    os.environ.pop("DAA_CHROMA_PATH", None)
    try:
        assert os.path.normpath(str(main._记忆库目录())) == os.path.normpath("data/chroma_db")
    finally:
        os.environ["DAA_CHROMA_PATH"] = os.environ.get("DAA_CHROMA_PATH", "")
