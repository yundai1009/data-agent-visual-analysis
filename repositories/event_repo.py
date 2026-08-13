# ============================================================
# 文件头 · 预测数据采集仓储（面试讲解）
# ------------------------------------------------------------
# 管什么：为「会员开通预测系统」采集四张业务事件表并导出 CSV：
#   用户注册表 / 生成日志表 / 拦截日志表 / 支付记录表。
# 为什么需要它：预测系统靠这四张表算特征、定标签（注册后 7 天
#   是否开月卡、拦截后 3 天是否转化）。本模块是 agent 平台侧的
#   "埋点落库 + 按规范导出"通道，未来上线后数据自动沉淀。
# 关键设计：
#   - user_id 复用现有 `u_`+16hex 脱敏编号（secrets.token_hex(8)），
#     与预测系统规范的"脱敏稳定编号"天然一致，四表全局对齐；
#   - 事件表独立于业务表：即使业务表结构演进，埋点口径不变；
#   - 导出统一转东八区 YYYY-MM-DD HH:MM:SS + 中文表头，直接进
#     预测系统 data/raw 跑 check-data 验收。
# 删除它会怎样：预测系统失去数据来源，会员开通预测无法进行。
# ============================================================
from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from 后端_核心.存储.sqlite_repo import _get_conn, _write_lock

logger = logging.getLogger(__name__)

# 东八区固定偏移（规范：全平台统一时区，推荐东八区）
_TZ_CN = timezone(timedelta(hours=8))

# 导出文件名（与预测系统 config.yaml data.tables 一致）
EXPORT_FILES: Dict[str, str] = {
    "event_register": "用户注册表.csv",
    "event_gen": "生成日志表.csv",
    "event_paywall": "拦截日志表.csv",
    "event_payment": "支付记录表.csv",
}

# 表 -> 导出列（顺序即 CSV 列顺序；中文表头 = 预测系统 schema 的对外字段名）
EXPORT_COLUMNS: Dict[str, list[tuple[str, str]]] = {
    "event_register": [
        ("user_id", "用户编号"),
        ("register_time", "注册时间"),
        ("channel", "来源渠道"),
        ("device_type", "设备类型"),
        ("city_tier", "城市线级"),
        ("user_source", "活动来源"),
    ],
    "event_gen": [
        ("user_id", "用户编号"),
        ("gen_time", "生成时间"),
        ("image_count", "生成图数"),
        ("analysis_type", "分析类型"),
        ("is_paid_quota", "是否消耗付费额度"),
        ("source_page", "发起入口"),
    ],
    "event_paywall": [
        ("user_id", "用户编号"),
        ("hit_time", "拦截时间"),
        ("action_after", "拦截后行为"),
        ("shown_price", "弹窗展示价"),
    ],
    "event_payment": [
        ("order_id", "订单编号"),
        ("user_id", "用户编号"),
        ("pay_time", "支付时间"),
        ("product_type", "商品类型"),
        ("amount", "实付金额"),
    ],
}

_TABLES: Dict[str, str] = {
    "event_register": "event_register",
    "event_gen": "event_gen",
    "event_paywall": "event_paywall",
    "event_payment": "event_payment",
}


def _now_cn() -> str:
    """当前时间（东八区）格式化为 YYYY-MM-DD HH:MM:SS。"""
    return datetime.now(_TZ_CN).strftime("%Y-%m-%d %H:%M:%S")


def _转导出时间(value: Optional[str]) -> str:
    """把存储的 ISO 时间转成东八区 YYYY-MM-DD HH:MM:SS（无法解析则原样返回）。"""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_TZ_CN).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value


def 初始化事件表() -> None:
    """幂等创建四张预测事件表。重复调用安全。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_register (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT NOT NULL,
                register_time TEXT NOT NULL,
                channel       TEXT,
                device_type   TEXT,
                city_tier     TEXT,
                user_source   TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_gen (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT NOT NULL,
                gen_time      TEXT NOT NULL,
                image_count   INTEGER NOT NULL DEFAULT 1,
                analysis_type TEXT,
                is_paid_quota INTEGER NOT NULL DEFAULT 0,
                source_page   TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_paywall (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                hit_time     TEXT NOT NULL,
                action_after TEXT NOT NULL,
                shown_price  REAL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_payment (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id     TEXT UNIQUE NOT NULL,
                user_id      TEXT NOT NULL,
                pay_time     TEXT NOT NULL,
                product_type TEXT NOT NULL,
                amount       REAL NOT NULL
            )
            """
        )
    logger.info("预测事件表已初始化（4 张）")


# ── 写入（打点）──────────────────────────────────────────────────

def 记录注册事件(
    user_id: str,
    channel: Optional[str] = None,
    device_type: Optional[str] = None,
    city_tier: Optional[str] = None,
    user_source: Optional[str] = None,
    register_time: Optional[str] = None,
) -> None:
    """注册落库后调用：记录一条用户注册事件。"""
    初始化事件表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO event_register (user_id, register_time, channel, device_type, city_tier, user_source) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, register_time or _now_cn(), channel, device_type, city_tier, user_source),
        )


def 记录生成事件(
    user_id: str,
    image_count: int = 1,
    analysis_type: Optional[str] = None,
    is_paid_quota: int = 0,
    source_page: Optional[str] = None,
    gen_time: Optional[str] = None,
) -> None:
    """报表生成完成后调用：记录一次生成事件（单/多 Agent 路径共用）。"""
    初始化事件表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO event_gen (user_id, gen_time, image_count, analysis_type, is_paid_quota, source_page) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, gen_time or _now_cn(), int(image_count), analysis_type, int(is_paid_quota), source_page),
        )


def 记录拦截事件(
    user_id: str,
    action_after: str,
    shown_price: Optional[float] = None,
    hit_time: Optional[str] = None,
) -> None:
    """免费额度校验失败时调用：记录一次付费墙拦截事件。"""
    初始化事件表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "INSERT INTO event_paywall (user_id, hit_time, action_after, shown_price) VALUES (?, ?, ?, ?)",
            (user_id, hit_time or _now_cn(), action_after, shown_price),
        )


def 记录支付事件(
    order_id: str,
    user_id: str,
    product_type: str,
    amount: float,
    pay_time: Optional[str] = None,
) -> None:
    """支付回调成功时调用：记录一笔支付事件。order_id 冲突时忽略（幂等）。"""
    初始化事件表()
    with _write_lock, _get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO event_payment (order_id, user_id, pay_time, product_type, amount) "
            "VALUES (?, ?, ?, ?, ?)",
            (order_id, user_id, pay_time or _now_cn(), product_type, float(amount)),
        )


# ── 导出（给预测系统）──────────────────────────────────────────────

def 导出事件CSV(table: str, out_dir: str | Path) -> Path:
    """把一张事件表导出为中文表头 CSV（预测系统 data/raw 格式）。"""
    初始化事件表()
    columns = EXPORT_COLUMNS[table]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / EXPORT_FILES[table]

    sql = f"SELECT {', '.join(c for c, _ in columns)} FROM {_TABLES[table]} ORDER BY id"
    with _get_conn() as conn:
        cur = conn.execute(sql)
        rows = cur.fetchall()
        col_names = [r[0] for r in cur.description]

    def _row_to_values(row: tuple) -> list[str]:
        values = []
        for col, _ in columns:
            idx = col_names.index(col)
            v = row[idx]
            if v is None:
                values.append("")
            elif col.endswith("_time") and isinstance(v, str):
                values.append(_转导出时间(v))
            else:
                values.append(str(v))
        return values

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([cn for _, cn in columns])
        for row in rows:
            writer.writerow(_row_to_values(row))
    logger.info("导出 %s → %s（%d 行）", table, out_path, len(rows))
    return out_path


def 导出全部事件CSV(out_dir: str | Path) -> Dict[str, Path]:
    """导出四张表 CSV，返回 {表: 文件路径}。"""
    return {table: 导出事件CSV(table, out_dir) for table in EXPORT_FILES}
