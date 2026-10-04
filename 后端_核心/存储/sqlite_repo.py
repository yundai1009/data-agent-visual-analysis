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
import re
import sqlite3
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from 后端_核心.存储 import sqlite_backend
from 后端_核心.存储.backend import 写锁 as _write_lock   # 阶段 54：写锁统一到抽象层

logger = logging.getLogger(__name__)


# 阶段 54：数据本体出库——DataFrame 落 parquet 文件，DB 只留元信息
_PARQUET_DIR = Path("data/parquet")


# 阶段 54：连接管理与写锁委托给存储后端（向后兼容别名，现有调用方零改动）
_get_conn = sqlite_backend.get_conn
_resolve_db_path = sqlite_backend.解析db路径


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
        # 优化⑬：parent_id 列（数据集版本链：清洗/合并后记录来源数据集）
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(datasets)").fetchall()}
        if "parent_id" not in cols:
            conn.execute("ALTER TABLE datasets ADD COLUMN parent_id TEXT")
        # 阶段 54：data_path 列（数据本体 parquet 文件路径；旧数据为空，走 df_json 回退）
        cols2 = {row["name"] for row in conn.execute("PRAGMA table_info(datasets)").fetchall()}
        if "data_path" not in cols2:
            conn.execute("ALTER TABLE datasets ADD COLUMN data_path TEXT")
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


def _df_to_json_split(df: pd.DataFrame) -> str:
    """DataFrame → JSON（split 格式：columns/index/data 分开存）。

    Fix 4 兜底：records 格式以列名为 key，表达不了重复列名
    （pandas 抛 "DataFrame columns must be unique for orient='records'"）；
    split 格式按位置存列名与数据，重复列名也能原样写出、读回。
    """
    return df.to_json(orient="split", force_ascii=False, date_format="iso")


def _parquet路径(dataset_id: str) -> Path:
    """阶段 54：某个数据集的 parquet 本体文件路径。

    Fix 3：dataset_id 拼进文件名前先净化——仅允许 [A-Za-z0-9_-]，
    其余字符抛 ValueError，防止未来用户可控的 dataset_id 造成路径穿越/删除任意文件。
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", dataset_id or ""):
        raise ValueError(f"非法的 dataset_id：{dataset_id!r}（仅允许字母、数字、下划线、连字符）")
    return _PARQUET_DIR / f"{dataset_id}.parquet"


def _df_from_json(json_str: str) -> pd.DataFrame:
    """JSON 字符串 → DataFrame。

    注意：``pd.read_json`` 在新版本中针对字面字符串会抛 ``FutureWarning``，
    需用 ``StringIO`` 包一层；这是 pandas 官方推荐的写法。

    Fix 4：split 格式（重复列名降级产物，以 ``{`` 开头且含 columns/data 键）
    自动识别为 orient="split"，records 格式走原路径。
    """
    text = json_str.lstrip()
    if text.startswith("{"):
        try:
            head = json.loads(json_str)
        except Exception:
            head = None
        if isinstance(head, dict) and "columns" in head and "data" in head:
            return pd.read_json(StringIO(json_str), orient="split")
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
    parent_id: Optional[str] = None,
) -> None:
    """新增或覆盖保存一个数据集（归属指定用户）。

    优化⑬：parent_id 记录来源数据集（清洗另存/合并产物的版本链来源）。

    阶段 54：DataFrame 本体落 parquet 文件，DB 只留元信息。
    """
    profile_json = json.dumps(画像, ensure_ascii=False, default=str)
    rows_count = int(len(df))
    cols_count = int(len(df.columns))
    now = _now_iso()
    # 阶段 54：DataFrame 落 parquet 文件（保留 dtype、压缩率高），DB 不再存整表 JSON
    # Fix 2：先写临时文件再 os.replace 原子替换——避免并发/读取时读到写一半的 parquet
    # Fix 4：pyarrow 序列化不了（如重复列名）时降级存 df_json，保证保存不硬失败
    pq = _parquet路径(dataset_id)
    pq.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PARQUET_DIR / f".{dataset_id}.parquet.tmp"
    df_json = ""
    data_path = str(pq)
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, pq)
    except Exception as exc:
        logger.warning("保存数据集 %s 写 parquet 失败（%s），降级存 df_json", dataset_id, exc)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        data_path = ""
        try:
            df_json = _df_to_json(df)
        except Exception as exc2:
            # 重复列名连 records JSON 都无法表达 → 用 split 格式兜底（列/数据分行存）
            logger.warning("保存数据集 %s records JSON 序列化失败（%s），改用 split 格式", dataset_id, exc2)
            df_json = _df_to_json_split(df)

    with _write_lock, _get_conn() as conn:
        # upsert: 存在则更新，不存在则插入
        conn.execute(
            """
            INSERT INTO datasets
                (dataset_id, user_id, file_name, stored_path, rows_count, cols_count,
                 df_json, profile_json, created_at, updated_at, parent_id, data_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
                user_id       = excluded.user_id,
                file_name     = excluded.file_name,
                stored_path   = excluded.stored_path,
                rows_count    = excluded.rows_count,
                cols_count    = excluded.cols_count,
                df_json       = excluded.df_json,
                profile_json  = excluded.profile_json,
                updated_at    = excluded.updated_at,
                data_path     = excluded.data_path
            """,
            (dataset_id, user_id, 文件名, 存储路径, rows_count, cols_count,
             df_json, profile_json, now, now, parent_id, data_path),
        )
    logger.info("保存数据集 %s（用户 %s, %s, %d 行）", dataset_id, user_id, 文件名, rows_count)


def 读取数据集(user_id: str, dataset_id: str) -> Optional[Dict[str, Any]]:
    """读取一个数据集（仅限归属用户）。不存在或不属于该用户返回 None。"""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT dataset_id, user_id, file_name, stored_path, rows_count, cols_count, "
            "df_json, profile_json, created_at, updated_at, parent_id, data_path "
            "FROM datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        ).fetchone()

    if row is None:
        return None

    # 阶段 54 Fix 1：parquet 缺失/损坏时回退 df_json；两者皆空/皆失败 → 返回 None，
    # 不让接口 500（此前 data_path 存在但 parquet 文件丢失会走 _df_from_json("") 抛 ValueError）。
    data_path = row["data_path"] or ""
    df = None
    if data_path:
        try:
            if Path(data_path).exists():
                df = pd.read_parquet(data_path)   # 阶段 54：优先读 parquet（快且保 dtype）
        except Exception as exc:
            logger.warning("读取数据集 %s 的 parquet 失败（%s），回退 df_json", dataset_id, exc)
    if df is None and row["df_json"]:
        try:
            df = _df_from_json(row["df_json"])   # 回退：旧数据仍存 df_json
        except Exception as exc:
            logger.error("读取数据集 %s 回退 df_json 失败: %s", dataset_id, exc)
    if df is None:
        logger.error("读取数据集 %s 失败：parquet 与 df_json 均不可用（data_path=%s）", dataset_id, data_path)
        return None

    return {
        "数据集ID": row["dataset_id"],
        "用户ID": row["user_id"],
        "文件名": row["file_name"],
        "路径": row["stored_path"],
        "行数": row["rows_count"],
        "列数": row["cols_count"],
        "数据": df,
        "数据路径": data_path,
        "数据画像": json.loads(row["profile_json"]),
        "创建时间": row["created_at"],
        "更新时间": row["updated_at"],
        "来源数据集ID": row["parent_id"] or None,  # 优化⑬：版本链来源
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
            "SELECT stored_path, data_path FROM datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        ).fetchone()
        stored_path = row["stored_path"] if row else None
        data_path = row["data_path"] if row else None
        cur = conn.execute(
            "DELETE FROM datasets WHERE dataset_id = ? AND user_id = ?",
            (dataset_id, user_id),
        )
        deleted = cur.rowcount > 0
    if deleted:
        _删除存储文件(stored_path)
        _删除存储文件(data_path)   # 阶段 54：一并清理 parquet 本体
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
            df: pd.DataFrame, 画像: Dict[str, Any], parent_id: Optional[str] = None) -> None:
        保存数据集(user_id, dataset_id, 文件名, 存储路径, df, 画像, parent_id=parent_id)

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
