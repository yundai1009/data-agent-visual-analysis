# -*- coding: utf-8 -*-
"""阶段 51：服务端 LLM 配额限流——检查/抛出/豁免/统计（TDD）。

- 配额只统计"服务端共享 Key"路径（BYOK 豁免在 reports.py 路由层判定）；
- 本文件覆盖 services/llm_quota 的判定逻辑与 usage_repo.用户今日用量 的统计口径。
"""
import os
import sys
from unittest import mock

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config.settings as settings_mod  # noqa: E402
from repositories import usage_repo  # noqa: E402
from services import llm_quota  # noqa: E402
from services.llm_quota import QuotaExceeded, 检查LLM配额  # noqa: E402


@pytest.fixture(autouse=True)
def 固定配额配置():
    with mock.patch.object(settings_mod.EnvConfig, "LLM_DAILY_TOKEN_QUOTA", "1000000"), \
         mock.patch.object(settings_mod.EnvConfig, "LLM_DAILY_REQUEST_QUOTA", "200"):
        yield


def test_未超限_返回当前用量(monkeypatch):
    monkeypatch.setattr("repositories.usage_repo.用户今日用量", lambda uid: {"记录数": 1, "总token": 5000})
    assert 检查LLM配额("u1") == {"记录数": 1, "总token": 5000}


def test_超token上限_抛QuotaExceeded(monkeypatch):
    monkeypatch.setattr("repositories.usage_repo.用户今日用量", lambda uid: {"记录数": 1, "总token": 1000000})
    with pytest.raises(QuotaExceeded, match="用量上限"):
        检查LLM配额("u1")


def test_超次数上限_抛QuotaExceeded(monkeypatch):
    monkeypatch.setattr("repositories.usage_repo.用户今日用量", lambda uid: {"记录数": 200, "总token": 100})
    with pytest.raises(QuotaExceeded, match="次数上限"):
        检查LLM配额("u1")


def test_配额0_视为不限(monkeypatch):
    with mock.patch.object(settings_mod.EnvConfig, "LLM_DAILY_TOKEN_QUOTA", "0"), \
         mock.patch.object(settings_mod.EnvConfig, "LLM_DAILY_REQUEST_QUOTA", "0"):
        monkeypatch.setattr("repositories.usage_repo.用户今日用量", lambda uid: {"记录数": 999, "总token": 10 ** 9})
        检查LLM配额("u1")  # 不抛


def test_用户今日用量_按天统计真实记录(monkeypatch, tmp_path):
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "quota_test.db"))
    usage_repo.记录用量("u-q", provider="deepseek", model="deepseek-chat", prompt_tokens=10, completion_tokens=5)
    usage_repo.记录用量("u-q", provider="deepseek", model="deepseek-chat", prompt_tokens=20, completion_tokens=10)
    usage_repo.记录用量("u-other", provider="deepseek", model="deepseek-chat", prompt_tokens=100, completion_tokens=0)

    用量 = usage_repo.用户今日用量("u-q")
    assert 用量["记录数"] == 2
    assert 用量["总token"] == 10 + 5 + 20 + 10  # 45