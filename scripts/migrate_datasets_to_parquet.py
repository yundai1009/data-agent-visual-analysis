# -*- coding: utf-8 -*-
"""阶段 54：把 datasets.df_json 里的数据本体一次性落成 parquet 文件。

幂等：已迁移（data_path 非空且文件存在）的记录跳过，可重复运行。
用法：
    python scripts/migrate_datasets_to_parquet.py --dry-run   # 只报告不写
    python scripts/migrate_datasets_to_parquet.py             # 实际迁移
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 后端_核心.存储 import sqlite_repo as sr  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告不写文件")
    args = ap.parse_args()

    sr.初始化数据库()
    with sr._get_conn() as conn:
        rows = conn.execute(
            "SELECT dataset_id, df_json, data_path FROM datasets "
            "WHERE df_json IS NOT NULL AND df_json != ''"
        ).fetchall()

    迁移 = 跳过 = 0
    for r in rows:
        if r["data_path"] and Path(r["data_path"]).exists():
            跳过 += 1
            continue
        target = sr._parquet路径(r["dataset_id"])
        if args.dry_run:
            print(f"[dry-run] 将迁移 {r['dataset_id']} -> {target}")
            迁移 += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        df = sr._df_from_json(r["df_json"])
        df.to_parquet(target, index=False)
        with sr._write_lock, sr._get_conn() as conn:
            conn.execute("UPDATE datasets SET data_path = ? WHERE dataset_id = ?",
                         (str(target), r["dataset_id"]))
        print(f"[迁移] {r['dataset_id']} -> {target}（{len(df)} 行）")
        迁移 += 1

    print(f"完成：迁移 {迁移} 条，跳过 {跳过} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
