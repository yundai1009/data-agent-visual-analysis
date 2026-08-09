"""孤儿上传文件清理脚本。

背景
====
历史版本删除数据集时只删 SQLite 记录、不删 data/uploads/ 的物理文件副本，
导致磁盘上累积大量"库中无记录"的孤儿文件（本项目曾累积 2000+ 个）。

用法
====
    python scripts/cleanup_orphan_uploads.py            # dry-run：只报告，不删除
    python scripts/cleanup_orphan_uploads.py --delete   # 实际删除（带确认）
    python scripts/cleanup_orphan_uploads.py --delete --yes  # 跳过确认

判定规则
========
遍历 data/uploads/ 下所有文件，其规范化绝对路径若不在
datasets.stored_path 集合中，即视为孤儿文件。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 项目根目录（脚本位于 scripts/ 下）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from 后端_核心.存储.sqlite_repo import _get_conn  # noqa: E402


def 收集库内路径() -> set:
    """返回 DB 中所有数据集的 stored_path 规范化绝对路径集合。"""
    stored: set = set()
    try:
        with _get_conn() as conn:
            rows = conn.execute("SELECT stored_path FROM datasets WHERE stored_path IS NOT NULL").fetchall()
        for row in rows:
            try:
                stored.add(str(Path(row["stored_path"]).resolve()))
            except Exception:
                continue
    except Exception as exc:
        print(f"[跳过] 数据库不可读（{exc}），将把所有文件视为孤儿——请确认后再 --delete")
    return stored


def 扫描上传目录() -> list:
    upload_dir = PROJECT_ROOT / "data" / "uploads"
    if not upload_dir.is_dir():
        print(f"上传目录不存在: {upload_dir}")
        return []
    return sorted(upload_dir.iterdir())


def main() -> int:
    parser = argparse.ArgumentParser(description="清理 data/uploads/ 中的孤儿文件（库中无记录）")
    parser.add_argument("--delete", action="store_true", help="实际删除（默认 dry-run 只报告）")
    parser.add_argument("--yes", action="store_true", help="跳过删除确认")
    args = parser.parse_args()

    stored = 收集库内路径()
    orphans = [
        f for f in 扫描上传目录()
        if f.is_file()
        and f.name != ".gitkeep"  # git 空目录占位文件，永不删除
        and str(f.resolve()) not in stored
    ]

    if not orphans:
        print("没有孤儿文件，一切干净 ✅")
        return 0

    total = sum(f.stat().st_size for f in orphans)
    print(f"发现 {len(orphans)} 个孤儿文件，共 {total / 1024 / 1024:.2f} MB")
    for f in orphans[:50]:
        print(f"  - {f.name} ({f.stat().st_size} B)")
    if len(orphans) > 50:
        print(f"  … 其余 {len(orphans) - 50} 个省略")

    if not args.delete:
        print("\n[dry-run] 未删除任何文件。确认无误后加 --delete 执行。")
        return 0

    if not args.yes:
        answer = input(f"确认删除以上 {len(orphans)} 个文件？[y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("已取消。")
            return 1

    removed = 0
    for f in orphans:
        try:
            f.unlink()
            removed += 1
        except Exception as exc:
            print(f"  删除失败 {f.name}: {exc}")
    print(f"已删除 {removed}/{len(orphans)} 个孤儿文件。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
