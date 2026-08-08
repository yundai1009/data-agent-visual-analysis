"""数据备份脚本（P2 加固）：一键打包 SQLite + chromadb 记忆 + .env 配置。

用法：
    python scripts/backup_db.py            # 生成 data/backups/backup-<时间戳>.zip
    python scripts/backup_db.py --keep 30  # 最多保留 30 个备份，超出删除最旧

包含：daa.db（SQLite 在线备份，免停机）、data/chroma_db/（Agent 记忆）、.env（配置）。
建议加入系统计划任务每天执行一次。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "daa.db"
CHROMA_DIR = DATA_DIR / "chroma_db"
ENV_PATH = PROJECT_ROOT / ".env"


def _backup_sqlite(src: Path, dst: Path) -> bool:
    """SQLite 在线备份（backup API，读一致性，无需停服）。"""
    try:
        src_conn = sqlite3.connect(str(src))
        dst_conn = sqlite3.connect(str(dst))
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] SQLite 备份失败: {exc}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="数据备份")
    parser.add_argument("--keep", type=int, default=20, help="保留最近 N 个备份")
    args = parser.parse_args()

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = BACKUP_DIR / f"backup-{timestamp}.zip"

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)

        # 1) SQLite 在线备份
        if DB_PATH.exists():
            if _backup_sqlite(DB_PATH, tmp / "daa.db"):
                print("  [OK] daa.db")
        else:
            print("  (未找到 daa.db，跳过)")

        # 2) chromadb 记忆目录
        if CHROMA_DIR.exists():
            shutil.copytree(CHROMA_DIR, tmp / "chroma_db", dirs_exist_ok=True)
            print(f"  [OK] chroma_db/（{sum(1 for _ in CHROMA_DIR.rglob('*'))} 项）")

        # 3) .env 配置（含密钥，随备份携带）
        if ENV_PATH.exists():
            shutil.copy2(ENV_PATH, tmp / ".env")
            print("  [OK] .env")

        # 打 zip
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in tmp.rglob("*"):
                if item.is_file():
                    zf.write(item, item.relative_to(tmp))
        print(f"[OK] 备份完成: {zip_path}（{zip_path.stat().st_size / 1024:.0f} KB）")

    # 清理旧备份
    backups = sorted(BACKUP_DIR.glob("backup-*.zip"), reverse=True)
    for old in backups[args.keep:]:
        old.unlink(missing_ok=True)
        print(f"  清理旧备份: {old.name}")

    print(f"当前保留 {min(len(backups), args.keep)} 份备份于 {BACKUP_DIR}")


if __name__ == "__main__":
    main()