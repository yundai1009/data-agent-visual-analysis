"""数据备份脚本（P2 加固）：一键打包 SQLite + chromadb 记忆 + .env 配置。

用法：
    python scripts/backup_db.py            # 生成 data/backups/backup-<时间戳>.zip
    python scripts/backup_db.py --keep 30  # 最多保留 30 个备份，超出删除最旧
    备份失败（mysqldump 未装/连接失败/daa.db 备份失败）时以非零码退出，
    供 Windows 计划任务按退出码识别真失败。

包含：daa.db（SQLite 在线备份，免停机）、data/chroma_db/（Agent 记忆）、.env（配置）。
DB_BACKEND=mysql 时改走 mysqldump（生成 mysql-<时间戳>.sql，SQL 文本备份）。
建议加入系统计划任务每天执行一次。
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

# 【C-1 修复】standalone 运行时 sys.path 注入：python scripts/backup_db.py 时
# sys.path[0] 是 scripts/，不加这段无法 import 后端_核心（与 migrate_sqlite_to_mysql.py 同款惯例）。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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


def _备份MySQL() -> bool:
    """mysqldump 备份 MySQL（DB_BACKEND=mysql 时用）。返回是否成功。

    密码安全说明：``-p{密码}`` 会短暂出现在进程命令行里，对本地脚本可接受；
    生产环境建议改用 ``--defaults-extra-file=xxx.cnf``，避免密码暴露在进程列表。
    无论哪种方式，密码绝不 print 到输出。
    """
    import subprocess
    from config.settings import EnvConfig
    时间戳 = datetime.now().strftime("%Y%m%d-%H%M%S")
    dump_path = BACKUP_DIR / f"mysql-{时间戳}.sql"
    cmd = [
        "mysqldump",
        "-h", EnvConfig.MYSQL_HOST,
        "-P", str(EnvConfig.MYSQL_PORT),
        "-u", EnvConfig.MYSQL_USER,
        f"-p{EnvConfig.MYSQL_PASSWORD}",
        "--single-transaction",
        EnvConfig.MYSQL_DATABASE,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            print(f"[warn] mysqldump 失败: {result.stderr[:300]}")
            return False
        dump_path.write_text(result.stdout, encoding="utf-8")
        print(f"[OK] MySQL 备份: {dump_path}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] MySQL 备份异常: {exc}")
        return False


def _清理旧备份(pattern: str, keep: int) -> int:
    """按模式清理旧备份，返回保留份数。两分支共用，产物都受 ``--keep`` 约束。

    C-3 修复：MySQL 分支原先 early-return 在清理逻辑之前，``mysql-*.sql`` 永不
    删除、日跑填满磁盘；现统一按「glob + mtime 倒序 + 删超出部分」清理——
    SQLite 传 ``backup-*.zip``、MySQL 传 ``mysql-*.sql``，都保留最近 keep 份。
    """
    backups = sorted(
        BACKUP_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[keep:]:
        old.unlink(missing_ok=True)
        print(f"  清理旧备份: {old.name}")
    return min(len(backups), keep)


def main() -> None:
    parser = argparse.ArgumentParser(description="数据备份")
    parser.add_argument("--keep", type=int, default=20, help="保留最近 N 个备份")
    args = parser.parse_args()

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # 【阶段54】DB_BACKEND=mysql 时改走 mysqldump（SQL 文本备份）；
    # SQLite 仍走下方 zip 打包逻辑，备份内容语义不变。
    # C-2 修复：备份失败立刻 sys.exit(1)，计划任务不再"假成功"；
    # C-3 修复：mysql-*.sql 产物与 SQLite 一样受 --keep 约束。
    from 后端_核心.存储.backend import 当前后端
    if 当前后端() == "mysql":
        if not _备份MySQL():
            sys.exit(1)
        _清理旧备份("mysql-*.sql", args.keep)
        return

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    zip_path = BACKUP_DIR / f"backup-{timestamp}.zip"

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)

        # 1) SQLite 在线备份
        if DB_PATH.exists():
            if not _backup_sqlite(DB_PATH, tmp / "daa.db"):
                # C-2 对齐：与 MySQL 分支一致，备份失败以非零码退出（原行为只
                # warn 不退出、zip 缺 daa.db 也照常生成，计划任务会误判成功）。
                print("  [warn] daa.db 备份失败，脚本以非零码退出（供计划任务识别）")
                sys.exit(1)
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

    # 清理旧备份（C-3：backup-*.zip 与 mysql-*.sql 统一走 _清理旧备份）
    剩余份数 = _清理旧备份("backup-*.zip", args.keep)
    print(f"当前保留 {剩余份数} 份备份于 {BACKUP_DIR}")


if __name__ == "__main__":
    main()