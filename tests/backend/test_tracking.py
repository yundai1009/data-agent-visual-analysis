# -*- coding: utf-8 -*-
"""后端采集推断单元测试（services/tracking.py）。

覆盖目标
========
- 设备类型推断：安卓/苹果/网页（含 UA 缺失兜底）
- 渠道与活动来源解析：channel / utm_source / utm_campaign / 缺失兜底
- 发起入口推断：/analysis → 提问框 等，无 Referer 兜底"未知"
- 异常输入不抛错（非法 URL 等）
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services.tracking import 解析渠道与活动来源, 推断发起入口, 推断设备类型


# ── 设备类型 ──────────────────────────────────────────────

def test_设备_安卓():
    assert 推断设备类型("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36") == "安卓"


def test_设备_苹果():
    assert 推断设备类型("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)") == "苹果"
    assert 推断设备类型("Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X)") == "苹果"


def test_设备_网页与缺失():
    assert 推断设备类型("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0") == "网页"
    assert 推断设备类型(None) == "网页"
    assert 推断设备类型("") == "网页"


# ── 渠道与活动来源 ────────────────────────────────────────

def test_渠道_from_channel参数():
    assert 解析渠道与活动来源("http://127.0.0.1:5173/login?channel=微信") == ("微信", "")


def test_渠道_from_utm_source():
    assert 解析渠道与活动来源("https://example.com/landing?utm_source=搜索引擎&utm_campaign=活动A") == (
        "搜索引擎",
        "活动A",
    )


def test_渠道_缺失兜底():
    assert 解析渠道与活动来源(None) == ("未知", "")
    assert 解析渠道与活动来源("http://127.0.0.1:5173/login") == ("未知", "")


def test_渠道_异常输入不抛错():
    # 非法 URL（parse_qs 抛 ValueError 时兜底）
    assert 解析渠道与活动来源("http://%zz") == ("未知", "")


# ── 发起入口 ──────────────────────────────────────────────

def test_发起入口_按路径():
    assert 推断发起入口("http://127.0.0.1:5173/analysis") == "提问框"
    assert 推断发起入口("http://127.0.0.1:5173/report/abc123") == "报表页"
    assert 推断发起入口("http://127.0.0.1:5173/dashboard") == "看板"
    assert 推断发起入口("http://127.0.0.1:5173/data") == "数据管理"


def test_发起入口_缺失兜底():
    assert 推断发起入口(None) == "未知"
    assert 推断发起入口("") == "未知"
    assert 推断发起入口("http://127.0.0.1:5173/account") == "未知"
