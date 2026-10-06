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


def 冲突更新SQL(后端: str, 表名: str, 列清单: str, 值清单: str, 冲突列: str, 更新列: list) -> str:
    """upsert（冲突覆盖更新）：SQLite 用 ``ON CONFLICT(col) DO UPDATE SET x = excluded.x``，
    MySQL 用 ``ON DUPLICATE KEY UPDATE x = new.x``（8.0.19+ 行别名语法）。

    Fix M1（阶段54-9 · MySQL 审查 Minor-2）：MySQL 8.0.20+ 弃用 ``VALUES(col)``
    别名（8.4 移除；8.0.23 仍可用但已 deprecated）——改用 ``VALUES (...) AS new
    ON DUPLICATE KEY UPDATE c = new.c``（8.0.19+ 支持，需 MySQL ≥ 8.0.19）。

    参数
    ----
    - 表名/列清单/值清单：INSERT 的三段（repo 层原有写法原样传入）
    - 冲突列：触发 upsert 的键列（唯一/主键；MySQL 分支不使用，仅保持签名一致）
    - 更新列：冲突时需覆盖的列名列表（sqlite → ``excluded.列``；mysql → ``new.列``）
    """
    if 后端 == "mysql":
        更新 = ", ".join(f"{c} = new.{c}" for c in 更新列)
        return f"INSERT INTO {表名} {列清单} VALUES {值清单} AS new ON DUPLICATE KEY UPDATE {更新}"
    更新 = ", ".join(f"{c} = excluded.{c}" for c in 更新列)
    return f"INSERT INTO {表名} {列清单} VALUES {值清单} ON CONFLICT({冲突列}) DO UPDATE SET {更新}"


def 表存在SQL(后端: str) -> str:
    """枚举全部业务表：SQLite 查 ``sqlite_master``；MySQL 查 information_schema。
    两种后端结果行都含 ``name`` 键（对齐：TABLE_NAME AS name / name）。
    """
    if 后端 == "mysql":
        return (
            "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
        )
    return "SELECT name FROM sqlite_master WHERE type='table'"


def 表结构SQL(后端: str, 表名: str) -> str:
    """取一张表的列名集合：SQLite 用 ``PRAGMA table_info``；MySQL 用 information_schema。
    两种后端结果行都含 ``name`` 键（对齐：COLUMN_NAME AS name / name）。

    ``表名`` 只允许代码常量（项目纪律：SQL 中禁止用户输入作标识符），直接内联。
    """
    if 后端 == "mysql":
        return (
            f"SELECT COLUMN_NAME AS name FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{表名}'"
        )
    return f"PRAGMA table_info({表名})"


def 创建索引SQL(后端: str, 索引名: str, 表名: str, 列: str, 唯一: bool = False) -> str:
    """repo 层创建索引的 SQL：SQLite 返回 ``CREATE [UNIQUE] INDEX IF NOT EXISTS ...``；
    MySQL 返回空串——索引由 ``mysql_repo.初始化数据库`` 统一管理
    （MySQL 8 不支持 ``CREATE INDEX IF NOT EXISTS``，重复建会 1061）。

    调用方约定：``sql = 创建索引SQL(...); if sql: conn.execute(sql)``。
    ``列`` 传单列名（如 ``email``）或括号片段（如 ``(user_id, created_at)``）。
    """
    if 后端 == "mysql":
        return ""
    前缀 = "CREATE UNIQUE INDEX" if 唯一 else "CREATE INDEX"
    if 列.startswith("("):
        return f"{前缀} IF NOT EXISTS {索引名} ON {表名} {列}"      # 多列片段：ON reports (a, b)
    return f"{前缀} IF NOT EXISTS {索引名} ON {表名}({列})"          # 单列：ON users(email)（与既有 DDL 逐字一致）


def 唯一冲突(异常: Exception) -> bool:
    """识别「唯一约束冲突」异常：SQLite 报 ``UNIQUE constraint failed``；
    MySQL（pymysql）报 ``(1062, \"Duplicate entry ...\")``——消息里没有 UNIQUE 字样，
    必须按 errno/关键字识别，否则重复注册/改名在 MySQL 下会变成 500 而非 400。
    """
    消息 = str(异常) or ""
    if "UNIQUE" in 消息:
        return True
    if "Duplicate entry" in 消息 or "1062" in 消息:
        return True
    参数 = getattr(异常, "args", None)
    if 参数 and str(参数[0]) == "1062":
        return True
    return False
