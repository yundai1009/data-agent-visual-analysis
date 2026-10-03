# -*- coding: utf-8 -*-
"""阶段 54 · 存储抽象层单测：占位符转换与后端选择（不连真实数据库）。"""

from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pytest

from 后端_核心.存储 import backend


def test_占位符风格_sqlite是问号_mysql是百分号():
    assert backend.占位符风格("sqlite") == "?"
    assert backend.占位符风格("mysql") == "%s"


def test_转换SQL_sqlite原样返回():
    sql = "SELECT * FROM users WHERE user_id = ? LIMIT ?"
    assert backend.转换SQL(sql, "sqlite") == sql


def test_转换SQL_mysql把问号换成百分号():
    sql = "SELECT * FROM users WHERE user_id = ? LIMIT ?"
    assert backend.转换SQL(sql, "mysql") == "SELECT * FROM users WHERE user_id = %s LIMIT %s"


def test_转换SQL_mysql遇到字面问号报错():
    # SQL 文本里出现字面 '?' 会让朴素替换产生错误语义 → 必须显式报错
    with pytest.raises(ValueError, match="字面问号"):
        backend.转换SQL("SELECT * FROM t WHERE name = '?', ?", "mysql")


def test_当前后端_默认sqlite(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "sqlite", raising=False)
    assert backend.当前后端() == "sqlite"


def test_当前后端_可切换mysql(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)
    assert backend.当前后端() == "mysql"


def test_自增主键DDL两后端不同():
    assert backend.自增主键DDL("sqlite") == "INTEGER PRIMARY KEY AUTOINCREMENT"
    assert backend.自增主键DDL("mysql") == "INT AUTO_INCREMENT PRIMARY KEY"


def test_插入忽略语句两后端不同():
    assert backend.插入忽略("sqlite", "event_payment", "(order_id)", "(1,'x')") \
        == "INSERT OR IGNORE INTO event_payment (order_id) VALUES (1,'x')"
    assert backend.插入忽略("mysql", "event_payment", "(order_id)", "(1,'x')") \
        == "INSERT IGNORE INTO event_payment (order_id) VALUES (1,'x')"
