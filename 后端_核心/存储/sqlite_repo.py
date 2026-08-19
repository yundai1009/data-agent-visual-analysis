"""SQLite 仓储实现：数据集持久化。

设计原则（写代码前先钉死）
==========================
1. **一律参数化查询 ``?``**：禁止字符串拼接 SQL，杜绝 SQL 注入
2. **DataFrame 序列化为 JSON**：pandas DataFrame 不能直接进 SQLite，转 JSON 字符串存 TEXT 列
3. **画像也序列化为 JSON**：跟 DataFrame 同样的方式
4. **每次请求用完即关连接**：不留长连接，避免多线程问题
5. **写操作走事务**：``with conn:`` 上下文管理自动 commit/rollback
6. **Schema 固定**：表名固定 ``datasets``，不接受用户输入作表名
7. **SQLite 路径只从配置读**：不接受用户输入

为什么不在 API 路由里直接写 sqlite3 代码
========================================
- 仓储模式（Repository Pattern）把存储细节从路由层解耦，便于测试与未来换 MySQL
- 路由层只关心业务逻辑，不关心 SQL 怎么写
- 单元测试可以 mock 仓储接口，不打真实 SQLite

未来从 SQLite 换到 MySQL/Postgres
===================================
- 只需替换本文件的实现
- 路由层调用接口 ``保存数据集`` ``读取数据集`` 等不动
- 这就是仓储模式的价值

DataFrame 序列化的取舍
======================
- 选 JSON 而不是 pickle：JSON 可读、可跨语言、安全（pickle 反序列化有 RCE 风险）
- 选 `df.to_json(orient="records", force_ascii=False)`：保留中文、行结构清晰
- 读取时 `pd.read_json(..., orient="records")` 反序列化
- 缺点：丢失 dtype；但本项目读出后立即用 `生成报表数据` 重新算画像，不影响
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# 默认 SQLite 文件路径：项目根目录下的 ``data/daa.db``
# 路径优先级：``DAA_SQLITE_PATH`` 环境变量 > ``EnvConfig.SQLITE_PATH`` > 默认值
_DEFAULT_DB_PATH = Path("data/daa.db")

# 线程锁，保护 SQLite 连接的写操作
# SQLite 默认不允许跨线程共享连接，所以我们每次请求都新建连接，但用一个锁串行化写
_write_lock = threading.Lock()


def _resolve_db_path() -> Path:
    """解析 SQLite 文件路径。优先级：环境变量 > 默认值。"""
    from config.settings import EnvConfig
    configured = ""
    try:
        configured = (EnvConfig.SQLITE_PATH or "").strip()
    except AttributeError:
        # 防御性：EnvConfig 可能还没加 SQLITE_PATH 字段
        configured = ""
    env_path = os.getenv("DAA_SQLITE_PATH", "").strip()
    chosen = env_path or configured or str(_DEFAULT_DB_PATH)
    return Path(chosen)


@contextmanager
def _get_conn() -> Iterator[sqlite3.Connection]:
    """获取 SQLite 连接，用完即关。

    - 每次请求新建连接（SQLite 推荐用法，避免跨线程问题）
    - ``row_factory`` 设为 ``sqlite3.Row`` 让结果以列名访问
    - ``PRAGMA foreign_keys = ON`` 打开外键约束
    - ``PRAGMA journal_mode = WAL`` 提升并发读性能
    """
    db_path = _resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # S9 修复：isolation_level="DEFERRED"（显式事务）替代 None（autocommit）——
    # 之前 with conn: 在 autocommit 下不开启事务，多表删除非原子、rollback 无效。
    # timeout=30 + busy_timeout 让写锁竞争时等待而非立即报 database is locked。
    conn = sqlite3.connect(str(db_path), isolation_level="DEFERRED", timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        # S9 修复：DEFERRED 显式事务下，with 块结束前必须显式提交。
        # _get_conn 是 @contextmanager 上下文，本身不执行 commit；旧
        # isolation_level=None（autocommit）模式下 execute 即提交，把这个缺陷掩盖了。
        # 现改 DEFERRED 后，若只依靠 conn.close()，未提交事务会被隐式回滚——
        # 导致验证码/用户/数据集/事件全部写入对其它连接不可见（注册查不到码、admin 种子
        # 查不到、sqlite_repo round-trip 失败）。finally 提交；异常分支已 rollback。
        try:
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()


def 初始化数据库() -> None:
    """创建表 schema。幂等，重复调用安全。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS datasets (
                dataset_id    TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL DEFAULT 'demo',
                file_name     TEXT NOT NULL,
                stored_path   TEXT NOT NULL,
                rows_count    INTEGER NOT NULL,
                cols_count    INTEGER NOT NULL,
                df_json       TEXT NOT NULL,
                profile_json  TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_datasets_created_at
            ON datasets (created_at)
            """
        )
        # 迁移：旧表没有 user_id 列时，补列并将旧数据归到 demo 用户
        _迁移_datasets_user_id(conn)
        # 用户表（阶段 3 认证体系）
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role          TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
            """
        )
    logger.info("SQLite 数据库已初始化: %s", _resolve_db_path())


def _迁移_datasets_user_id(conn: sqlite3.Connection) -> None:
    """兼容旧库：datasets 表缺少 user_id 列时补列，旧数据归 demo 用户。

    SQLite 的 ALTER TABLE ADD COLUMN 不能加带非空默认值的列，
    所以先加可空列，再 UPDATE 填充默认值。
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(datasets)")}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE datasets ADD COLUMN user_id TEXT")
        conn.execute("UPDATE datasets SET user_id = 'demo' WHERE user_id IS NULL")
        logger.info("datasets 表已迁移：新增 user_id 列，旧数据归入 demo 用户")
    else:
        # 已有列但部分行可能为 NULL（极端情况），兜底填充
        conn.execute("UPDATE datasets SET user_id = 'demo' WHERE user_id IS NULL")


# ---- 序列化辅助 --------------------------------------------------------------


def _df_to_json(df: pd.DataFrame) -> str:
    """DataFrame → JSON 字符串。"""
    return df.to_json(orient="records", force_ascii=False, date_format="iso")


def _df_from_json(json_str: str) -> pd.DataFrame:
    """JSON 字符串 → DataFrame。

    注意：``pd.read_json`` 在新版本中针对字面字符串会抛 ``FutureWarning``，
    需用 ``StringIO`` 包一层；这是 pandas 官方推荐的写法。
    """
    return pd.read_json(StringIO(json_str), orient="records")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- 仓储主接口 --------------------------------------------------------------


def 保存数据集(
    user_id: str,
    dataset_id: str,
    文件名: str,
    存储路径: str,
    df: pd.DataFrame,
    画像: Dict[str, Any],
) -> None:
    """新增或覆盖保存一个数据集（归属指定用户）。"""
    df_json = _df_to_json(df)
    profile_json = json.dumps(画像, ensure_ascii=False, default=str)
    rows_count = int(len(df))
    cols_count = int(len(df.columns))
    now = _now_iso()

    with _write_lock, _get_conn() as conn:
        # upsert: 存在则更新，不存在则插入
        conn.execute(
            """
            INSERT INTO datasets
                (dataset_id, user_id, file_name, stored_path, rows_count, cols_count,
                 df_json, profile_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
                user_id       = excluded.user_id,
                file_name     = excluded.file_name,
                stored_path   = excluded.stored_path,
                rows_count    = excluded.rows_count,
                cols_count    = excluded.cols_count,
                df_json       = excluded.df_json,
                profile_json  = excluded.profile_json,
                updated_at    = excluded.updated_at
            """,
            (dataset_id, user_id, 文件名, 存储路径, rows_count, cols_count,
             df_json, profile_json, now, now),
        )
    logger.info("保存数据集 %s（用户 %s, %s, %d 行）", dataset_id, user_id, 文件名, rows_count)


def 读取数据集(user_id: str, dataset_id: str) -> Optional[Dict[str, Any]]:
    """读取一个数据集（仅限归属用户）。不存在或不属于该用户返回 None。"""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT dataset_id, user_id, file_name, stored_path, rows_count, cols_count, "
            "df_json, profile_json, created_at, updated_at "
            "FROM datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        ).fetchone()

    if row is None:
        return None

    return {
        "数据集ID": row["dataset_id"],
        "用户ID": row["user_id"],
        "文件名": row["file_name"],
        "路径": row["stored_path"],
        "行数": row["rows_count"],
        "列数": row["cols_count"],
        "数据": _df_from_json(row["df_json"]),
        "数据画像": json.loads(row["profile_json"]),
        "创建时间": row["created_at"],
        "更新时间": row["updated_at"],
    }


def 数据集是否存在(user_id: str, dataset_id: str) -> bool:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        ).fetchone()
    return row is not None


def 列出数据集(user_id: str, limit: int = 200, q: str = "", sort: str = "created_at_desc") -> List[Dict[str, Any]]:
    """列出某用户的数据集，支持文件名搜索与排序（阶段 31 · 数据集管理增强）。

    sort 取值：created_at_desc（默认，最新在前）/ rows_desc（行数最多在前）/ file_name_asc（按名称）。
    q 非空时按文件名模糊匹配（LIKE %q%）。
    """
    _排序映射 = {
        "created_at_desc": "created_at DESC",
        "rows_desc": "rows_count DESC",
        "file_name_asc": "file_name ASC",
    }
    order_by = _排序映射.get(sort, "created_at DESC")
    sql = (
        "SELECT dataset_id, file_name, rows_count, cols_count, created_at "
        "FROM datasets WHERE user_id = ?"
    )
    params: List[Any] = [user_id]
    if q:
        sql += " AND file_name LIKE ?"
        params.append(f"%{q}%")
    sql += f" ORDER BY {order_by} LIMIT ?"
    params.append(limit)
    with _get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        {
            "数据集ID": row["dataset_id"],
            "文件名": row["file_name"],
            "行数": row["rows_count"],
            "列数": row["cols_count"],
            "创建时间": row["created_at"],
        }
        for row in rows
    ]


def 统计数据集(user_id: str) -> Dict[str, int]:
    """阶段 31：数据集概览统计（空间占用面板）——总数 + 总行数。"""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(rows_count), 0) AS total_rows "
            "FROM datasets WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return {"总数": int(row["cnt"]), "总行数": int(row["total_rows"])}


def _删除存储文件(存储路径: Optional[str]) -> None:
    """删除数据集对应的物理文件（best-effort，失败仅告警不阻断业务）。"""
    if not 存储路径:
        return
    try:
        Path(存储路径).unlink(missing_ok=True)
    except Exception as exc:
        logger.warning("清理数据集物理文件失败 %s: %s", 存储路径, exc)


def 删除数据集(user_id: str, dataset_id: str) -> bool:
    """删除一个数据集（仅限归属用户）。返回是否真的删除了。

    P0 修复：删除 DB 记录的同时清理 data/uploads/ 的物理文件副本，
    避免上传-删除循环在磁盘上累积孤儿文件。
    """
    with _write_lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT stored_path FROM datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        ).fetchone()
        stored_path = row["stored_path"] if row else None
        cur = conn.execute(
            "DELETE FROM datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        )
        deleted = cur.rowcount > 0
    if deleted:
        _删除存储文件(stored_path)
        logger.info("删除数据集 %s（用户 %s）", dataset_id, user_id)
    return deleted


def 重命名数据集(user_id: str, dataset_id: str, 新文件名: str) -> bool:
    """重命名数据集（仅限归属用户）。返回是否成功。"""
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            "UPDATE datasets SET file_name = ?, updated_at = ? WHERE dataset_id = ? AND user_id = ?",
            (新文件名, _now_iso(), dataset_id, user_id),
        )
        return cur.rowcount > 0


# ---- 仓储类（依赖注入友好） ---------------------------------------------------


class 数据集仓储:
    """仓储类，方便路由层依赖注入。本类只是上面函数的薄封装。"""

    def __init__(self) -> None:
        初始化数据库()

    def 保存(self, user_id: str, dataset_id: str, 文件名: str, 存储路径: str,
            df: pd.DataFrame, 画像: Dict[str, Any]) -> None:
        保存数据集(user_id, dataset_id, 文件名, 存储路径, df, 画像)

    def 读取(self, user_id: str, dataset_id: str) -> Optional[Dict[str, Any]]:
        return 读取数据集(user_id, dataset_id)

    def 存在(self, user_id: str, dataset_id: str) -> bool:
        return 数据集是否存在(user_id, dataset_id)

    def 列表(self, user_id: str, limit: int = 200, q: str = "", sort: str = "created_at_desc") -> List[Dict[str, Any]]:
        return 列出数据集(user_id, limit=limit, q=q, sort=sort)

    def 统计(self, user_id: str) -> Dict[str, int]:
        return 统计数据集(user_id)

    def 删除(self, user_id: str, dataset_id: str) -> bool:
        return 删除数据集(user_id, dataset_id)

    def 重命名(self, user_id: str, dataset_id: str, 新文件名: str) -> bool:
        return 重命名数据集(user_id, dataset_id, 新文件名)
