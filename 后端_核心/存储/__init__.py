"""后端核心 · 存储子包

阶段 2 范围
==========
把 `_DATASET_DB` 进程内字典升级为本地 SQLite 持久化，让进程重启后数据仍在。

为什么 SQLite
-------------
- Python 标准库自带 `sqlite3`，零依赖
- 部署目标 A：代码上 GitHub，面试官本地 clone + `pip install -r requirements.txt` + `python api/main.py` 直接能跑
- 不需要装 MySQL 服务器、不需要配账号、不需要建库
- SQLite → MySQL 的迁移成本远低于反过来

模块结构
--------
- ``sqlite_repo``  : SQLite 仓储实现，参数化查询、DataFrame 序列化、事务安全
"""

from 后端_核心.存储.sqlite_repo import (
    初始化数据库,
    保存数据集,
    读取数据集,
    数据集是否存在,
    列出数据集,
    删除数据集,
    数据集仓储,
)

__all__ = [
    "初始化数据库",
    "保存数据集",
    "读取数据集",
    "数据集是否存在",
    "列出数据集",
    "删除数据集",
    "数据集仓储",
]
