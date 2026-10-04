# -*- coding: utf-8 -*-
"""阶段 54 · 存储后端抽象层。

目的：把 SQL 方言差异收敛到本模块，让 repositories 层不必为换库逐文件返工。
当前只实现 SQLite 行为（默认）；MySQL 后端见 mysql_backend.py。

约定
----
- repo 层 SQL 永远用 ``?`` 占位符；转 MySQL 时由 :func:`转换SQL` 变成 ``%s``
- SQL 文本中禁止出现字面问号（``'?'`` 之类），否则转换无法安全进行
"""
from __future__ import annotations

import re
import threading

# 写锁：SQLite 需要串行化写（进程内）；MySQL 靠事务/行锁，保留同对象仅为接口统一
写锁 = threading.Lock()

# 字面问号检测：匹配单引号字符串字面量（支持 SQL 标准 '' 双写转义与 \' 反斜杠
# 转义写法），凡字符串内出现 ? 即为字面问号（裸 ? 一律视为占位符）
_去字符串 = re.compile(r"'(?:[^'\\]|''|\\.)*'")


def 当前后端() -> str:
    """返回当前启用的后端名：``sqlite``（默认）或 ``mysql``。

    仅 config 导入失败（ImportError，如缺依赖/配置模块不存在）时回落默认值；
    其他异常（配置读取错误等）向上抛出，避免静默掩盖真实问题。
    """
    try:
        from config.settings import EnvConfig
        return (getattr(EnvConfig, "DB_BACKEND", "sqlite") or "sqlite").strip().lower()
    except ImportError:
        return "sqlite"


def 占位符风格(后端: str) -> str:
    """目标后端的参数占位符风格。"""
    return "%s" if 后端 == "mysql" else "?"


def 转换SQL(sql: str, 后端: str) -> str:
    """把 repo 层的 ``?`` 占位符转成目标后端风格。SQLite 原样返回。

    含字面问号（单引号字符串字面量内的 ?）时抛 ValueError——朴素替换会把字面问号
    也换成 %s，产生错误 SQL。裸 ? 一律视为占位符（约定如此），不会报错。

    检测范围：单引号字符串字面量，支持 SQL 标准 ``''`` 双写转义与常见 ``\\'``
    反斜杠转义写法。不在检测范围（已知限制）：双引号字符串 ``"q?"``、反引号标识符
    `` `col?` ``、``--`` 注释内的 ``?`` 会漏检、可能被误替换；项目纪律是 SQL 中
    禁止字面问号，未来接 MySQL 时应升级为 SQL 解析级检测（本函数不引入手写解析器）。
    """
    if 后端 != "mysql":
        return sql
    if any("?" in q for q in _去字符串.findall(sql)):
        raise ValueError(f"SQL 含字面问号，无法安全转换占位符：{sql}")
    return sql.replace("?", "%s")


def 自增主键DDL(后端: str) -> str:
    """自增主键列定义：SQLite 与 MySQL 拼写不同。"""
    return "INT AUTO_INCREMENT PRIMARY KEY" if 后端 == "mysql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


def 插入忽略(后端: str, 表名: str, 列清单: str, 值清单: str) -> str:
    """冲突忽略插入：SQLite 是 ``INSERT OR IGNORE``，MySQL 是 ``INSERT IGNORE``。"""
    关键字 = "INSERT IGNORE" if 后端 == "mysql" else "INSERT OR IGNORE"
    return f"{关键字} INTO {表名} {列清单} VALUES {值清单}"
