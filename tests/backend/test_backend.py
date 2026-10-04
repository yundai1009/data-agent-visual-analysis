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


# ---- Fix A：字面问号检测边界（'' 双写转义 / \\' 反斜杠转义 / 混合）----


def test_转换SQL_mysql双单引号转义内问号判字面报错():
    # '' 双写转义：'it''s ?' 是单个字面量，其内的 ? 是字面问号。
    # 按项目纪律（SQL 禁止字面问号）抛 ValueError，绝不静默替换成 %s。
    with pytest.raises(ValueError, match="字面问号"):
        backend.转换SQL("SELECT * FROM t WHERE a = 'it''s ?' AND b = ?", "mysql")


def test_转换SQL_mysql双单引号转义无问号时正常转换():
    # '' 双写转义 + 多个无问号字符串字面量：b 的 ? 转 %s，字符串原样保留
    sql = "SELECT * FROM t WHERE a = 'it''s' AND c = 'x' AND b = ?"
    assert backend.转换SQL(sql, "mysql") \
        == "SELECT * FROM t WHERE a = 'it''s' AND c = 'x' AND b = %s"


def test_转换SQL_mysql反斜杠转义引号内问号判字面报错():
    # 反斜杠转义引号 'it\'s ?'：检测已支持 \\' 转义，字符串内含字面 ? → 抛
    # ValueError（修复历史漏检——旧正则会把 'it\' 当配对、漏掉串内 ?，静默
    # 替换成 %s 产生错误 SQL）。SQLite 语义下本写法本身非法，报错即安全。
    with pytest.raises(ValueError, match="字面问号"):
        backend.转换SQL("SELECT * FROM t WHERE a = 'it\\'s ?' AND b = ?", "mysql")


def test_转换SQL_mysql混合占位符与字面问号报错():
    # 既有契约：占位符 + 字符串内字面问号同时出现 → 仍抛 ValueError
    with pytest.raises(ValueError, match="字面问号"):
        backend.转换SQL("SELECT * FROM t WHERE name = ? AND note = '?', ?", "mysql")


# ---- Fix B：当前后端() 异常捕获收窄（仅吞 ImportError）----


def test_当前后端_config导入ImportError回落sqlite(monkeypatch):
    # config.settings 导入失败（ImportError）→ 仍安全回落默认后端 sqlite
    import sys
    monkeypatch.setitem(sys.modules, "config.settings", None)
    assert backend.当前后端() == "sqlite"


def test_当前后端_非ImportError异常不再被吞(monkeypatch):
    # 收窄后：读取配置期间的非导入错误（如 RuntimeError）必须向上抛，不得静默掩盖
    import sys
    import types

    class _坏配置(types.ModuleType):
        @property
        def EnvConfig(self):
            raise RuntimeError("模拟读取DB_BACKEND失败")

    monkeypatch.setitem(sys.modules, "config.settings", _坏配置("config.settings"))
    with pytest.raises(RuntimeError, match="模拟读取DB_BACKEND失败"):
        backend.当前后端()
