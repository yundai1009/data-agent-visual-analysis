# -*- coding: utf-8 -*-
"""阶段 54：把 datasets.df_json 里的数据本体一次性落成 parquet 文件。

幂等：已迁移（data_path 非空且文件存在）的记录跳过，可重复运行。
用法：
    python scripts/migrate_datasets_to_parquet.py --dry-run            # 只报告不写
    python scripts/migrate_datasets_to_parquet.py                      # 实际迁移
    python scripts/migrate_datasets_to_parquet.py --clear-df-json      # 迁移后清空 df_json
    python scripts/migrate_datasets_to_parquet.py --dry-run --clear-df-json

--clear-df-json 的含义与风险（Fix 6 设计权衡）：
    迁移成功后 parquet 与 df_json 双份冗余，datasets 表仍占约 53MB。
    但 df_json 是 parquet 文件丢失/损坏时的灾难恢复副本（读取会自动回退）。
    默认**保留** df_json 作为安全网；--clear-df-json 仅在迁移**全部成功**
    （循环无异常到达清理步骤）后，把那些 parquet 文件已存在的行的 df_json
    置空，从而释放库空间。代价：一旦 parquet 被误删，该数据集将不可恢复，
    请确认备份后再启用。
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
    ap.add_argument(
        "--clear-df-json", action="store_true",
        help="迁移全部成功后把 df_json 置空（释放库空间；失去 parquet 丢失时的 JSON 恢复副本）",
    )
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

    if args.clear_df_json:
        # 走到这里说明迁移循环无异常（全部成功或已跳过）；任何失败都会在循环内抛异常中止
        if args.dry_run:
            print(f"[dry-run] --clear-df-json：迁移完成后将清空 {迁移 + 跳过} 行的 df_json（数据均已落 parquet）")
        else:
            with sr._get_conn() as conn:
                to_clear = conn.execute(
                    "SELECT dataset_id, data_path FROM datasets "
                    "WHERE df_json IS NOT NULL AND df_json != ''"
                ).fetchall()
            cleared = 0
            for r in to_clear:
                if r["data_path"] and Path(r["data_path"]).exists():
                    with sr._write_lock, sr._get_conn() as conn:
                        conn.execute("UPDATE datasets SET df_json = '' WHERE dataset_id = ?",
                                     (r["dataset_id"],))
                    cleared += 1
            print(f"[clear-df-json] 已清空 {cleared} 行的 df_json（仅清空 parquet 文件已存在的记录）")

    print(f"完成：迁移 {迁移} 条，跳过 {跳过} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
