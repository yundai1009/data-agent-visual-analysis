"""清理数据集表 df_json 残留列脚本（阶段 54 迁移 parquet 后的垃圾列）。

背景
====
阶段 54 起数据本体落 parquet 文件（datasets.data_path），DB 不再存整表
JSON；但**存量行**的 df_json 垃圾列仍占着表空间——压测实测 user52a 的
11 行残留 25.36MB df_json，148 行整表物理占 ~64MB，直接放大
`WHERE user_id=?` 全表扫描成本（单查 ~20ms，列表端点一次跑 2 条 ~40ms）。

判定规则
========
df_json 非空 且 data_path 非空 且 data_path 指向的 parquet 文件存在
→ 数据本体已由 parquet 承载，df_json 是纯垃圾 → 候选。

用法
====
    python scripts/cleanup_df_json.py             # dry-run：只报告，不删
    python scripts/cleanup_df_json.py --delete    # 置空候选行的 df_json（不动 parquet）
    python scripts/cleanup_df_json.py --delete --yes  # 跳过确认
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 项目根目录（脚本位于 scripts/ 下）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from 后端_核心.存储.sqlite_repo import _get_conn  # noqa: E402


def 扫描() -> list:
    """返回候选行列表：df_json 非空 且 parquet 文件存在（df_json 为垃圾列）。"""
    候选: list = []
    try:
        with _get_conn() as conn:
            rows = conn.execute(
                "SELECT dataset_id, user_id, file_name, df_json, data_path "
                "FROM datasets WHERE df_json IS NOT NULL AND df_json != ''"
            ).fetchall()
    except Exception as exc:
        print(f"[跳过] 数据库不可读（{exc}），无法扫描")
        return []
    for row in rows:
        data_path = (row["data_path"] or "").strip()
        if not data_path:
            continue
        if not Path(data_path).is_file():
            continue
        候选.append({
            "dataset_id": row["dataset_id"],
            "user_id": row["user_id"],
            "file_name": row["file_name"],
            "df_json字节": len(row["df_json"].encode("utf-8", errors="ignore")),
            "data_path": data_path,
        })
    return 候选


def 删除(dataset_id: str) -> int:
    """把单个候选行的 df_json 置空（不动 data_path/parquet，数据本体仍可读）。"""
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE datasets SET df_json = '' WHERE dataset_id = ? AND df_json != ''",
            (dataset_id,),
        )
        return cur.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 datasets.df_json 残留列（数据本体已在 parquet）")
    parser.add_argument("--delete", action="store_true", help="实际置空 df_json（默认 dry-run 只报告）")
    parser.add_argument("--yes", action="store_true", help="跳过删除确认")
    args = parser.parse_args()

    候选 = 扫描()
    if not 候选:
        print("没有 df_json 残留（全部数据已由 parquet 承载或库不可读），一切干净 [OK]")
        return 0

    total = sum(r["df_json字节"] for r in 候选)
    print(f"发现 {len(候选)} 个数据集带 df_json 残留，共 {total / 1024 / 1024:.2f} MB")
    for r in 候选[:50]:
        print(f"  - {r['file_name']}（{r['dataset_id']}，user={r['user_id']}，"
              f"{r['df_json字节'] / 1024:.1f} KB）")
    if len(候选) > 50:
        print(f"  … 其余 {len(候选) - 50} 个省略")

    if not args.delete:
        print("\n[dry-run] 未修改任何数据。确认后加 --delete 执行（只置空 df_json，不动 parquet）。")
        return 0

    if not args.yes:
        answer = input(f"确认置空以上 {len(候选)} 行的 df_json？[y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消。")
            return 1

    cleared = sum(删除(r["dataset_id"]) for r in 候选)
    print(f"已置空 {cleared}/{len(候选)} 行的 df_json（parquet 本体与 data_path 未动）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())