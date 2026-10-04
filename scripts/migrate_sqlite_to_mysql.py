# -*- coding: utf-8 -*-
"""阶段 54 · SQLite → MySQL 数据迁移（幂等）。

把生产 SQLite 的业务表迁到 MySQL ``daa`` 库：MySQL 存元信息，数据本体（parquet
文件）仍在文件系统，``datasets.data_path`` 只存路径。

用法
----
    python scripts/migrate_sqlite_to_mysql.py --dry-run          # 只报告，不连目标库
    python scripts/migrate_sqlite_to_mysql.py --清空目标          # 正式迁移（先清空目标表）
    python scripts/migrate_sqlite_to_mysql.py --include-df-json  # 连 datasets.df_json 大字段也迁
    python scripts/migrate_sqlite_to_mysql.py --源库 data/daa.db --报告 报告.json

设计
----
- **表清单动态发现**：``sqlite_master`` 里所有非 ``sqlite_%`` 的表，表增减不改脚本
- **列类型映射**：见 :func:`列类型映射`（单列 INTEGER 主键→自增、TEXT 主键→VARCHAR、
  时间列→DATETIME(6)、其余按 SQLite 声明类型映射）
- **时间转换**：ISO 时间串（``2026-08-01T05:22:30.480774+00:00``）→ naive UTC datetime
- **幂等**：``INSERT ... ON DUPLICATE KEY UPDATE``，重复运行不产生重复行
- **默认跳过 ``datasets.df_json``**：数据本体的归宿是文件系统，MySQL 只存元信息
- **dry-run 纯只读**：连 MySQL 都不连，只统计源库行数

安全约束
--------
- 源库以 ``mode=ro`` 打开：迁移脚本**不可能**写坏生产 SQLite（dry-run 亦然）。
- 目标库凭据只从 ``.env`` 的 ``MYSQL_*`` 读（复用 :mod:`mysql_backend`），脚本内无任何密码。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional, Sequence, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 后端_核心.存储 import backend, mysql_backend, sqlite_backend  # noqa: E402

# 默认跳过的列：datasets.df_json 是数据本体（parquet 文件在 data/parquet/），
# MySQL 侧只存元信息，迁 54MB JSON 进 MySQL 既无必要也会撑爆 max_allowed_packet。
_默认跳过列: Dict[str, set] = {"datasets": {"df_json"}}

# 时间列名判定：以这些后缀结尾的 TEXT 列按 ISO 时间串处理
_时间列后缀 = ("_at", "_time", "时间", "日期")

# 批量写入：行数上限 + 单批载荷字节上限（防一次攒出超过 max_allowed_packet 的包）
_批行数 = 200
_批字节 = 8 * 1024 * 1024


# --------------------------------------------------------------------------- 报告


class 迁移结果:
    """迁移报告。

    既支持按表名取报告（``报告["users"]["迁入"]``），也支持整体序列化（``--报告``）。
    """

    def __init__(self, *, 源库: str, dry_run: bool, 清空目标: bool, 表: Dict[str, dict]):
        self.源库 = 源库
        self.dry_run = dry_run
        self.清空目标 = 清空目标
        self.表 = 表

    # 映射式访问
    def __getitem__(self, 表名: str) -> dict:
        return self.表[表名]

    def __contains__(self, 表名: str) -> bool:
        return 表名 in self.表

    def __iter__(self) -> Iterator[str]:
        return iter(self.表)

    def __len__(self) -> int:
        return len(self.表)

    def keys(self):
        return self.表.keys()

    def items(self):
        return self.表.items()

    @property
    def 总源行数(self) -> int:
        return sum(t.get("源行数", 0) for t in self.表.values())

    @property
    def 总迁入(self) -> int:
        return sum(t.get("迁入", 0) for t in self.表.values())

    @property
    def 总警告(self) -> int:
        return sum(len(t.get("警告", [])) for t in self.表.values())

    def as_dict(self) -> dict:
        return {
            "源库": self.源库,
            "dry_run": self.dry_run,
            "清空目标": self.清空目标,
            "表数": len(self.表),
            "总源行数": self.总源行数,
            "总迁入": self.总迁入,
            "总警告": self.总警告,
            "表": self.表,
        }


# --------------------------------------------------------------------------- 源库


@contextmanager
def _开源连接(源库路径: str) -> Iterator[sqlite3.Connection]:
    """**只读**打开源 SQLite 库（``mode=ro``）：迁移脚本写不坏生产库。"""
    conn = sqlite3.connect(Path(源库路径).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def 发现表清单(源: sqlite3.Connection) -> List[str]:
    """动态发现业务表：``sqlite_master`` 中排除 ``sqlite_%`` 内部表。表增减不改脚本。"""
    return [
        r[0]
        for r in 源.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def 表结构(源: sqlite3.Connection, 表名: str) -> List[dict]:
    """读 ``PRAGMA table_info``，返回列信息字典列表（cid/name/type/notnull/dflt_value/pk）。"""
    return [
        {"cid": r["cid"], "name": r["name"], "type": r["type"] or "",
         "notnull": r["notnull"], "default": r["dflt_value"], "pk": r["pk"]}
        for r in 源.execute(f'PRAGMA table_info("{表名}")')
    ]


# --------------------------------------------------------------------------- 类型映射


def 是时间列名(列名: str) -> bool:
    """按列名判定时间列：``created_at`` / ``gen_time`` / ``创建时间`` / ``截止日期`` 等。"""
    名 = (列名 or "").strip().lower()
    return any(名.endswith(后缀) for 后缀 in _时间列后缀)


def 列类型映射(列名: str, 源类型: str, *, 是主键: bool, 主键列数: int) -> str:
    """SQLite 声明类型 → MySQL 列类型。

    规则（按优先级）：

    1. 单列 INTEGER 主键 → ``backend.自增主键DDL("mysql")``（方言收敛，不重复造）
    2. 其余主键列（含 TEXT 主键）→ ``VARCHAR(255) PRIMARY KEY``；复合主键用 191
       （MySQL 的 TEXT/BLOB **不能做主键**：无默认长度、加不了索引长度前缀）
    3. 时间列名 + TEXT 值 → ``DATETIME(6)``（保留微秒，ISO 串精度不丢）
    4. ``BOOLEAN`` → ``BOOLEAN``；INTEGER 族 → ``INT``；REAL 族 → ``DOUBLE``
    5. BLOB 族 → ``LONGBLOB``；其余 TEXT 族 → ``LONGTEXT``
       （SQLite 文本无长度上限：实测 ``datasets.df_json`` 单行最大 1236 万字符、
       ``reports.report_json`` 最大 30 万字符，MySQL ``TEXT`` 只有 64KB 会直接截断报错）
    """
    源类型 = (源类型 or "").strip().upper()
    是文本族 = ("TEXT" in 源类型 or "CHAR" in 源类型 or "CLOB" in 源类型 or not 源类型)

    if 是主键:
        if 源类型.startswith("INT") and 主键列数 == 1:
            return backend.自增主键DDL("mysql")          # INT AUTO_INCREMENT PRIMARY KEY
        # TEXT 主键 / 复合主键：VARCHAR(255)（单列）/ VARCHAR(191)（复合，utf8mb4 索引更安全）
        长度 = 255 if 主键列数 == 1 else 191
        return f"VARCHAR({长度}) PRIMARY KEY"

    if 是文本族 and 是时间列名(列名):
        return "DATETIME(6)"
    if 源类型 == "BOOLEAN":
        return "BOOLEAN"
    if 源类型.startswith(("INT", "BIGINT", "SMALLINT", "TINYINT", "MEDIUMINT")):
        return "INT"
    if 源类型.startswith(("REAL", "FLOA", "DOUB", "NUMER", "DECIM")):
        return "DOUBLE"
    if "BLOB" in 源类型:
        return "LONGBLOB"
    return "LONGTEXT"


def _建表DDL(表名: str, 结构: Sequence[dict]) -> str:
    """按源库列结构生成 MySQL 建表 DDL（复用 mysql_backend.建表语句）。"""
    主键列数 = sum(1 for c in 结构 if c["pk"])
    列定义 = [
        (c["name"], 列类型映射(c["name"], c["type"], 是主键=bool(c["pk"]), 主键列数=主键列数))
        for c in 结构
    ]
    return mysql_backend.建表语句(表名, 列定义)


# --------------------------------------------------------------------------- 值转换


def 转时间值(值) -> Tuple[Optional[datetime], Optional[str]]:
    """ISO 时间串 → naive UTC datetime；失败返回 ``(None, 原因)``。

    源库时间值有两种形态：``2026-08-01T05:22:30.480774+00:00``（带时区）与
    ``2026-08-18 11:20:07``（无时区）。带时区的一律折算成 UTC 再去掉 tzinfo——
    MySQL ``DATETIME`` 不带时区语义，留着 offset 只会被服务端按会话时区二次偏移。
    """
    if 值 is None:
        return None, None
    if isinstance(值, datetime):
        return _去时区(值), None
    文本 = str(值).strip()
    if not 文本:
        return None, None
    try:
        return _去时区(datetime.fromisoformat(文本)), None
    except ValueError:
        return None, f"时间值不是合法 ISO 时间串，已置 NULL：{文本[:40]}"


def _去时区(值: datetime) -> datetime:
    return 值.astimezone(timezone.utc).replace(tzinfo=None) if 值.tzinfo else 值


# --------------------------------------------------------------------------- 迁移


def 建目标表(源库路径: str, *, 表清单: Optional[Sequence[str]] = None,
             include_df_json: bool = False) -> Dict[str, str]:
    """按源库 schema 在 MySQL 目标库建表（``CREATE TABLE IF NOT EXISTS``），**不写任何行**。

    单独暴露建表步骤：``--dry-run`` 是纯只读、不建表，运维/测试可先调它预热结构。
    返回 ``{表名: DDL}``。
    """
    建表语句集: Dict[str, str] = {}
    with _开源连接(源库路径) as 源:
        清单 = list(表清单) if 表清单 is not None else 发现表清单(源)
        with mysql_backend.get_conn() as 目标:
            with 目标.cursor() as cur:
                for 表名 in 清单:
                    结构 = 表结构(源, 表名)
                    if not 结构:
                        continue
                    DDL = _建表DDL(表名, 结构)
                    cur.execute(DDL)
                    建表语句集[表名] = DDL
    return 建表语句集


def 迁移(源库路径, *, 清空目标: bool = False, dry_run: bool = False,
         include_df_json: bool = False,
         输出: Optional[Callable[[str], None]] = None) -> 迁移结果:
    """把源 SQLite 库的业务表迁到 MySQL 目标库，返回 :class:`迁移结果`。

    参数
    ----
    源库路径
        源 SQLite 文件；脚本以只读（``mode=ro``）方式打开。
    清空目标
        迁每张表前先 ``DELETE FROM`` 目标表。仅在显式开启时执行（``DELETE`` 而非
        ``TRUNCATE``：``TRUNCATE`` 需要 DROP 权限，业务账号通常没有）。
    dry_run
        只统计与打印，**连目标库都不连**，绝不建表/删表/写数据。
    include_df_json
        是否连 ``datasets.df_json`` 大字段一起迁（默认跳过）。
    """
    say = 输出 if 输出 is not None else print
    源库路径 = str(源库路径)
    if not Path(源库路径).exists():
        raise FileNotFoundError(f"源 SQLite 库不存在：{源库路径}")

    目标库 = _目标库描述()
    前缀 = "[dry-run]" if dry_run else "[迁移]"
    say(f"{前缀} 源库={源库路径} → 目标库={目标库}"
        f"{'（只报告，不写）' if dry_run else ''}")

    报告表: Dict[str, dict] = {}
    with _开源连接(源库路径) as 源:
        表清单 = 发现表清单(源)
        if dry_run:
            for 表名 in 表清单:
                报告表[表名] = _只统计(源, 表名, include_df_json=include_df_json)
        else:
            # 一次连接覆盖全部表：数据写入在同一个事务里，异常时整体回滚
            # （DDL 例外——MySQL 的 CREATE TABLE 本身即隐式提交）。
            with mysql_backend.get_conn() as 目标:
                with 目标.cursor() as cur:
                    for 表名 in 表清单:
                        报告表[表名] = _迁表(源, cur, 表名, 清空目标=清空目标,
                                            include_df_json=include_df_json)

    结果 = 迁移结果(源库=源库路径, dry_run=dry_run, 清空目标=清空目标, 表=报告表)
    for 表名, 表报 in 报告表.items():
        行 = (f"{前缀} {表名:<22} 源行数={表报['源行数']:<6} 迁入={表报['迁入']:<6} "
              f"列数={表报['列数']}")
        if 表报["跳过列"]:
            行 += f"  跳过列={','.join(表报['跳过列'])}"
        if 表报["警告"]:
            行 += f"  警告×{len(表报['警告'])}"
        say(行)
        for 警告 in 表报["警告"][:5]:
            say(f"{前缀}   ! {警告}")
        if len(表报["警告"]) > 5:
            say(f"{前缀}   ! …另有 {len(表报['警告']) - 5} 条警告")
    say(f"{前缀} 合计 {len(报告表)} 张表，源行数 {结果.总源行数}"
        + (f"，实际迁入 {结果.总迁入} 行" if not dry_run else "（dry-run 不写库）"))
    return 结果


def _目标库描述() -> str:
    """目标库标识（仅 host/库名/账号，绝不打印密码）。"""
    from config.settings import EnvConfig
    return f"{EnvConfig.MYSQL_USER}@{EnvConfig.MYSQL_HOST}:{EnvConfig.MYSQL_PORT}/{EnvConfig.MYSQL_DATABASE}"


def _跳过列(表名: str, include_df_json: bool) -> List[str]:
    if include_df_json:
        return []
    return sorted(_默认跳过列.get(表名, set()))


def _只统计(源: sqlite3.Connection, 表名: str, *, include_df_json: bool) -> dict:
    """dry-run 分支：只数行、算列映射，不碰目标库。"""
    结构 = 表结构(源, 表名)
    跳过 = _跳过列(表名, include_df_json)
    迁列 = [c for c in 结构 if c["name"] not in 跳过]
    主键列 = [c["name"] for c in sorted(结构, key=lambda c: c["pk"]) if c["pk"]]
    警告: List[str] = [] if 主键列 else ["源表无主键，dry-run 报告按全表统计（正式迁移将跳过）"]
    源行数 = 源.execute(f'SELECT COUNT(*) FROM "{表名}"').fetchone()[0]
    return {
        "列数": len(结构),
        "源行数": 源行数,
        "迁入": 0,
        "跳过": 0,
        "跳过列": 跳过,
        "警告": 警告,
        "已建表": False,
        "迁入列数": len(迁列),
    }


def _迁表(源: sqlite3.Connection, 游标, 表名: str, *, 清空目标: bool,
          include_df_json: bool) -> dict:
    """迁移单表：建表 → （可选）清空 → 批量 upsert。"""
    结构 = 表结构(源, 表名)
    跳过 = _跳过列(表名, include_df_json)
    迁列 = [c for c in 结构 if c["name"] not in 跳过]
    主键列 = [c["name"] for c in sorted(结构, key=lambda c: c["pk"]) if c["pk"]]
    时间列 = {c["name"] for c in 迁列 if _该列是时间(结构, c["name"])}
    警告: List[str] = []

    游标.execute(_建表DDL(表名, 结构))
    if 清空目标:
        游标.execute(f"DELETE FROM `{表名}`")

    报告 = {"列数": len(结构), "源行数": 0, "迁入": 0, "跳过": 0,
            "跳过列": 跳过, "警告": 警告, "已建表": True, "迁入列数": len(迁列)}

    if not 主键列:
        警告.append("源表无主键：无法用 ON DUPLICATE KEY UPDATE 保证幂等，整表跳过")
        报告["跳过"] = 源.execute(f'SELECT COUNT(*) FROM "{表名}"').fetchone()[0]
        报告["源行数"] = 报告["跳过"]
        return 报告
    if not 迁列:
        警告.append("迁入列为空（全部列被跳过），整表跳过")
        return 报告

    SQL = _upsertSQL(表名, 迁列, 主键列)
    列片段 = ", ".join(f'"{c["name"]}"' for c in 迁列)
    待写: List[tuple] = []
    待写字节 = 0
    主键位 = [c["name"] for c in 迁列]

    def _落批():
        nonlocal 待写, 待写字节
        if 待写:
            游标.executemany(SQL, 待写)
            报告["迁入"] += len(待写)
            待写, 待写字节 = [], 0

    for 行 in 源.execute(f'SELECT {列片段} FROM "{表名}"'):
        报告["源行数"] += 1
        if any(行[k] is None for k in 主键列):
            # SQLite 允许 TEXT PRIMARY KEY 存 NULL，MySQL 主键列隐式 NOT NULL：
            # 这类行既插不进也 upsert 不掉，只能跳过并留痕。
            报告["跳过"] += 1
            警告.append("主键含 NULL，该行已跳过（MySQL 主键不可为 NULL）")
            continue
        值 = []
        for 名 in 主键位:
            原值 = 行[名]
            if 名 in 时间列:
                转换值, 错 = 转时间值(原值)
                if 错:
                    警告.append(f"{名}：{错}")
                原值 = 转换值
            值.append(原值)
        待写.append(tuple(值))
        待写字节 += sum(len(v) for v in 值 if isinstance(v, (str, bytes)))
        if len(待写) >= _批行数 or 待写字节 >= _批字节:
            _落批()
    _落批()
    return 报告


def _该列是时间(结构: Sequence[dict], 列名: str) -> bool:
    """时间列判定（与 :func:`列类型映射` 第 3 条同一口径：仅 TEXT 族 + 时间列名）。"""
    列 = next((c for c in 结构 if c["name"] == 列名), None)
    if 列 is None or 列["pk"]:
        return False
    源类型 = (列["type"] or "").strip().upper()
    是文本族 = ("TEXT" in 源类型 or "CHAR" in 源类型 or "CLOB" in 源类型 or not 源类型)
    return 是文本族 and 是时间列名(列名)


def _upsertSQL(表名: str, 迁列: Sequence[dict], 主键列: Sequence[str]) -> str:
    """``INSERT ... ON DUPLICATE KEY UPDATE``：重复运行覆盖旧值，不产生重复行。"""
    列清单 = ", ".join(f"`{c['name']}`" for c in 迁列)
    占位 = ", ".join(["%s"] * len(迁列))
    非主键 = [c["name"] for c in 迁列 if c["name"] not in 主键列]
    if 非主键:
        更新 = ", ".join(f"`{名}`=VALUES(`{名}`)" for 名 in 非主键)
    else:
        # 只有主键列：给个空转更新，避免 ON DUPLICATE KEY UPDATE 后无内容导致语法错
        更新 = f"`{迁列[0]['name']}`=`{迁列[0]['name']}`"
    return f"INSERT INTO `{表名}` ({列清单}) VALUES ({占位}) ON DUPLICATE KEY UPDATE {更新}"


# --------------------------------------------------------------------------- CLI


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="SQLite → MySQL 幂等迁移（MySQL 存元信息，数据本体在文件系统）")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写（连目标库都不连）")
    ap.add_argument("--清空目标", action="store_true",
                    help="迁每张表前先清空目标表（DELETE FROM，非 TRUNCATE）")
    ap.add_argument("--include-df-json", action="store_true",
                    help="连 datasets.df_json 大字段也迁（默认跳过，数据本体在文件系统）")
    ap.add_argument("--源库", default=None,
                    help="源 SQLite 路径（默认 DAA_SQLITE_PATH / 配置 / data/daa.db）")
    ap.add_argument("--报告", default=None, help="可选：把迁移报告写成 JSON 文件")
    args = ap.parse_args(argv)

    源库 = args.源库 or str(sqlite_backend.解析db路径())
    结果 = 迁移(源库, 清空目标=args.清空目标, dry_run=args.dry_run,
                include_df_json=args.include_df_json)

    if args.报告:
        Path(args.报告).write_text(
            json.dumps(结果.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[报告] 已写入 {args.报告}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
