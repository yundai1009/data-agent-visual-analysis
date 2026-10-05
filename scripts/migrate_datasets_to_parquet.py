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

per-row 失败降级（阶段 54 Task 8 修复）：
    真实库 145 条中有 2 条 df_json 含 object 列（数字 + '2，4' 全角逗号
    字符串混排），pyarrow 严格类型检查拒绝转换，旧逻辑 to_parquet 抛异常
    中止整轮迁移。现在：
    - object 列先尝试 ``astype(str)`` 宽松兜底（脏数据列转字符串可写 parquet）
    - 单行仍失败时**不中止**，记录进失败清单（dataset_id + 原因）继续迁移
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from 后端_核心.存储 import sqlite_repo as sr  # noqa: E402


def _df_宽松化(df):
    """把 object 列转成 str——df_json 读回时 dtype 有损（混合列被推断成
    object），pyarrow 严格类型检查拒绝 object→数值的转换。对脏数据列转
    字符串可写 parquet；正常 dtype 列不受影响。"""
    for col in df.columns:
        if df[col].dtype == "object":
            df[col] = df[col].astype(str)
    return df


def 迁移(dry_run: bool = False, clear_df_json: bool = False) -> dict:
    """执行迁移，返回结果 dict：{迁移: int, 跳过: int, 失败: [dict]}。

    失败项形如 {"dataset_id": str, "原因": str}。dry_run 时不写任何文件。
    """
    结果 = {"迁移": 0, "跳过": 0, "失败": []}
    sr.初始化数据库()
    with sr._get_conn() as conn:
        rows = conn.execute(
            "SELECT dataset_id, df_json, data_path FROM datasets "
            "WHERE df_json IS NOT NULL AND df_json != ''"
        ).fetchall()

    for r in rows:
        if r["data_path"] and Path(r["data_path"]).exists():
            结果["跳过"] += 1
            continue
        target = sr._parquet路径(r["dataset_id"])
        if dry_run:
            print(f"[dry-run] 将迁移 {r['dataset_id']} -> {target}")
            结果["迁移"] += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            df = sr._df_from_json(r["df_json"])
            try:
                df.to_parquet(target, index=False)
            except Exception:
                # 宽松兜底：object 列转 str 再试（脏数据 dtype 有损场景）
                _df_宽松化(df).to_parquet(target, index=False)
        except Exception as exc:
            结果["失败"].append({"dataset_id": r["dataset_id"], "原因": str(exc)[:200]})
            print(f"[失败] {r['dataset_id']}: {str(exc)[:100]}（保留 df_json，可重跑或人工修复）")
            continue
        with sr._write_lock, sr._get_conn() as conn:
            conn.execute("UPDATE datasets SET data_path = ? WHERE dataset_id = ?",
                         (str(target), r["dataset_id"]))
        print(f"[迁移] {r['dataset_id']} -> {target}（{len(df)} 行）")
        结果["迁移"] += 1

    if clear_df_json:
        if dry_run:
            print(f"[dry-run] --clear-df-json：迁移完成后将清空 {结果['迁移'] + 结果['跳过']} 行的 df_json")
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

    print(f"完成：迁移 {结果['迁移']} 条，跳过 {结果['跳过']} 条，失败 {len(结果['失败'])} 条")
    return 结果


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只报告不写文件")
    ap.add_argument(
        "--clear-df-json", action="store_true",
        help="迁移全部成功后把 df_json 置空（释放库空间；失去 parquet 丢失时的 JSON 恢复副本）",
    )
    args = ap.parse_args()
    结果 = 迁移(dry_run=args.dry_run, clear_df_json=args.clear_df_json)
    return 1 if 结果["失败"] else 0


if __name__ == "__main__":
    sys.exit(main())
