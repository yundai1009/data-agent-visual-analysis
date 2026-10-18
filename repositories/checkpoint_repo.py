# -*- coding: utf-8 -*-
# ============================================================
# 【文件定位】checkpoints 表的唯一出入口：把「一次 ReAct 分析跑到了第几轮、中间产出什么」落库，
#            让进程被杀 / 客户端断连后的下一次同需求请求能从断点续跑，而不是从第 1 轮重来。
# ============================================================
# 【做了什么】
#   1. 建 checkpoints 表 + idx_checkpoints_user_dataset 索引（进程级一次性、按 DB 路径分键缓存）。
#   2. 保存检查点：同一 (user_id, dataset_id, requirement) 只保留一行——已存在「可用」行就 UPDATE
#      （每轮一次写，不堆行），否则 INSERT。
#   3. 读取检查点：只按「归属用户 + 同数据集 + 同需求 + 状态可用 + 未过期」取最近一行；
#      命中过期行就地标记 已过期 并返回 None（坏存档当没有存档，绝不抛错给调用方）。
#   4. 消费检查点（一次性语义，防同一份存档被两次续跑）/ 删除检查点 / 清理过期检查点。
# 【为什么这么做】
#   - 这是「把长链路 Agent 的中间态当一等公民持久化」：阶段六十七的取消令牌只能省下
#     「还没发出去的 LLM 调用」，已经飞出去的请求拦不住；第 1/2 轮的真实产出不落库，
#     用户重新点一次就要再等 30 秒。检查点补的正是这一段。
#   - 存 messages（ReAct 对话体）而不只存轮次号：续跑时 LLM 必须看得见上一轮的工具返回，
#     只存「跑到第 2 轮」会让它凭空接话，等于换了道题在答。
#   - 不存 DataFrame（太大且可再生，按 dataset_id 重取）；不存 trace（它属于「这一次执行」
#     的呈现物，把旧 trace 塞进新结果会让用户看到两段拼接的历史）。
#   - 不存 api_key：续跑总是由一次新的 HTTP 请求触发，请求级 BYOK 配置自带密钥；
#     落库只会白白扩大泄漏面。只留 model 便于排查「续跑时换了模型」。
#   - TTL 默认 30 分钟：数据集可能被删/改，过期上下文里的字段名与行数已不保真，
#     宁可让用户重跑，也别拿过期状态出一份错报表。
# 【关键约定与坑】
#   - user_id 过滤是硬约定（与 report_repo 一致），每个对外函数都带，越权一律查不到。
#   - 时间列存带 +00:00 偏移的 ISO 串原文（与全库一致，lexical 比较与 fromisoformat 都成立），
#     过期判断因此在 Python 侧做，而不是塞进 SQL 里比字符串。
#   - 写操作必须同时拿 backend.写锁 + _get_conn，与其它仓储一致（MySQL 下 ? 由连接包装转 %s）。
#   - 列名一律英文（对齐既有表），对外返回中文字典键——Chinese 列名在 MySQL 侧要反引号包裹，
#     没必要为此破例。
# ============================================================

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from 后端_核心.存储.backend import 写锁 as _write_lock
from 后端_核心.存储.backend import 创建索引SQL as _建索引SQL, 当前后端 as _后端
from 后端_核心.存储.连接 import _get_conn   # 阶段 54-8：统一连接入口（按 DB_BACKEND 分发）

logger = logging.getLogger(__name__)

# 检查点有效期（秒）：超过这个时长的存档视为不可信（数据集可能已变），不再续跑。
检查点有效期秒 = 1800

状态可用 = "可用"
状态已消费 = "已消费"
状态已过期 = "已过期"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _过期时刻(有效期秒: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, int(有效期秒)))).isoformat()


def _是否过期(过期时刻: str, 有效期秒: Optional[int] = None) -> bool:
    """过期判断：优先看落库的 expires_at；缺列/坏值回退按「现在 - 有效期」口径。"""
    if 过期时刻:
        try:
            return datetime.fromisoformat(过期时刻) <= datetime.now(timezone.utc)
        except (TypeError, ValueError):
            pass
    if 有效期秒 is None:
        return True
    return False


# Fix E1 同款：初始化检查点表 与 初始化报表表 一致——进程级一次性 + 按 DB 路径分键缓存
# （隔离测试各 tmp_path 各自首次初始化），失败不缓存下次重试；双检锁防并发重复建表。
_检查点表已初始化: Dict[str, bool] = {}
_检查点表初始化锁 = threading.Lock()


def _当前db键() -> str:
    """初始化缓存键：SQLite 文件路径（MySQL 分支提前 return，不参与缓存）。"""
    from 后端_核心.存储.sqlite_backend import 解析db路径
    return str(解析db路径())


def _初始化检查点表全量() -> None:
    """完整执行 checkpoints 表 DDL（仅首次/失败重试时调用）。"""
    with _get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                user_id       TEXT NOT NULL,
                dataset_id    TEXT NOT NULL,
                requirement   TEXT NOT NULL,
                rule_text     TEXT NOT NULL DEFAULT '',
                profile_json  TEXT NOT NULL,
                messages_json TEXT NOT NULL,
                done_rounds   INTEGER NOT NULL,
                model         TEXT NOT NULL DEFAULT '',
                status        TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                expires_at    TEXT NOT NULL
            )
            """
        )
        _sql = _建索引SQL(_后端(), "idx_checkpoints_user_dataset", "checkpoints", "(user_id, dataset_id)")
        if _sql:
            conn.execute(_sql)


def 初始化检查点表() -> None:
    """幂等创建 checkpoints 表（MySQL 分支交给 mysql_repo.初始化数据库 统一建）。"""
    if _后端() == "mysql":
        return  # 阶段 54-8 约定：sqlite DDL 在 MySQL 下语义校验即报错，表结构由 mysql_repo 管理
    key = _当前db键()
    if _检查点表已初始化.get(key):
        return
    with _检查点表初始化锁:
        if _检查点表已初始化.get(key):
            return
        # 失败回退：异常向上抛且不置标志，下次调用重试
        _初始化检查点表全量()
        _检查点表已初始化[key] = True


def _行转检查点(row: Any) -> Dict[str, Any]:
    """DB 行 → 对外字典（中文键 + 反序列化后的画像/messages）。坏 JSON 当空值，不抛。"""
    画像: Dict[str, Any] = {}
    消息: List[Dict[str, Any]] = []
    try:
        画像 = json.loads(row["profile_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        画像 = {}
    try:
        消息 = json.loads(row["messages_json"] or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        消息 = []
    if not isinstance(画像, dict):
        画像 = {}
    if not isinstance(消息, list):
        消息 = []
    return {
        "检查点ID": row["checkpoint_id"],
        "轮次": int(row["done_rounds"] or 0),
        "画像": 画像,
        "messages": 消息,
        "规则文本": row["rule_text"] or "",
        "模型": row["model"] or "",
        "状态": row["status"],
        "更新时刻": row["updated_at"],
        "过期时刻": row["expires_at"] or "",
    }


def 保存检查点(
    user_id: str,
    dataset_id: str,
    requirement: str,
    profile: Dict[str, Any],
    messages: List[Dict[str, Any]],
    已完成轮次: int,
    rule_text: str = "",
    model: str = "",
    有效期秒: int = 检查点有效期秒,
) -> str:
    """保存/更新执行态检查点，返回 checkpoint_id。

    同一 (user_id, dataset_id, requirement) 的「可用」行只保留一行：
    第 1 轮写 INSERT，第 2 轮起走 UPDATE（一次分析只占一行，不堆 3 行）。
    """
    初始化检查点表()
    now = _now_iso()
    到期 = _过期时刻(有效期秒)
    画像_json = json.dumps(profile or {}, ensure_ascii=False, default=str)
    消息_json = json.dumps(messages or [], ensure_ascii=False, default=str)
    with _write_lock, _get_conn() as conn:
        row = conn.execute(
            "SELECT checkpoint_id FROM checkpoints "
            "WHERE user_id = ? AND dataset_id = ? AND requirement = ? AND status = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (user_id, dataset_id, requirement, 状态可用),
        ).fetchone()
        if row is not None:
            checkpoint_id = row["checkpoint_id"]
            conn.execute(
                "UPDATE checkpoints SET rule_text = ?, profile_json = ?, messages_json = ?, "
                "done_rounds = ?, model = ?, updated_at = ?, expires_at = ? "
                "WHERE checkpoint_id = ?",
                (rule_text, 画像_json, 消息_json, int(已完成轮次), model, now, 到期, checkpoint_id),
            )
        else:
            checkpoint_id = uuid.uuid4().hex
            conn.execute(
                "INSERT INTO checkpoints (checkpoint_id, user_id, dataset_id, requirement, rule_text, "
                "profile_json, messages_json, done_rounds, model, status, created_at, updated_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (checkpoint_id, user_id, dataset_id, requirement, rule_text, 画像_json, 消息_json,
                 int(已完成轮次), model, 状态可用, now, now, 到期),
            )
    logger.info("保存执行态检查点 %s（用户 %s，已完成轮次 %s）", checkpoint_id, user_id, 已完成轮次)
    return checkpoint_id


def 读取检查点(
    user_id: str,
    requirement: str,
    dataset_id: Optional[str] = None,
    有效期秒: int = 检查点有效期秒,
) -> Optional[Dict[str, Any]]:
    """取「同用户 + 同需求（+ 同数据集）」最近一份可用检查点；没有/过期/坏存档一律返回 None。

    过期行就地标记 已过期：这样它不会再被下一次请求读到，也给清理留了依据。
    """
    初始化检查点表()
    sql = ("SELECT checkpoint_id, done_rounds, profile_json, messages_json, rule_text, model, "
           "status, created_at, updated_at, expires_at FROM checkpoints "
           "WHERE user_id = ? AND requirement = ? AND status = ?")
    参数: List[Any] = [user_id, requirement, 状态可用]
    if dataset_id is not None:
        sql += " AND dataset_id = ?"
        参数.append(dataset_id)
    sql += " ORDER BY created_at DESC LIMIT 1"
    with _get_conn() as conn:
        row = conn.execute(sql, tuple(参数)).fetchone()
    if row is None:
        return None
    检查点 = _行转检查点(row)
    if _是否过期(检查点["过期时刻"]):
        消费检查点(检查点["检查点ID"], 状态=状态已过期)
        logger.info("执行态检查点 %s 已过期（TTL %s 秒），本次不续跑", 检查点["检查点ID"], 有效期秒)
        return None
    return 检查点


def 消费检查点(checkpoint_id: str, 状态: str = 状态已消费) -> bool:
    """把检查点标记为已消费/已过期（只对「可用」行生效），返回是否真的改了。"""
    if not checkpoint_id:
        return False
    初始化检查点表()
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(
            "UPDATE checkpoints SET status = ?, updated_at = ? WHERE checkpoint_id = ? AND status = ?",
            (状态, _now_iso(), checkpoint_id, 状态可用),
        )
        改动 = int(getattr(cur, "rowcount", 0) or 0)
    return 改动 > 0


def 删除检查点(user_id: str, requirement: Optional[str] = None, dataset_id: Optional[str] = None) -> int:
    """删除某用户的检查点（可按需求/数据集收窄），返回删除行数。"""
    初始化检查点表()
    sql = "DELETE FROM checkpoints WHERE user_id = ?"
    参数: List[Any] = [user_id]
    if requirement is not None:
        sql += " AND requirement = ?"
        参数.append(requirement)
    if dataset_id is not None:
        sql += " AND dataset_id = ?"
        参数.append(dataset_id)
    with _write_lock, _get_conn() as conn:
        cur = conn.execute(sql, tuple(参数))
        return int(getattr(cur, "rowcount", 0) or 0)


def 清理过期检查点(有效期秒: int = 检查点有效期秒) -> int:
    """把已过期的「可用」行标记为 已过期，返回处理行数（不物理删除，留档便于排查）。"""
    初始化检查点表()
    过期ID: List[str] = []
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT checkpoint_id, expires_at FROM checkpoints WHERE status = ?", (状态可用,)
        ).fetchall()
    for row in rows:
        if _是否过期(row["expires_at"] or ""):
            过期ID.append(row["checkpoint_id"])
    if not 过期ID:
        return 0
    now = _now_iso()
    with _write_lock, _get_conn() as conn:
        for checkpoint_id in 过期ID:
            conn.execute(
                "UPDATE checkpoints SET status = ?, updated_at = ? WHERE checkpoint_id = ? AND status = ?",
                (状态已过期, now, checkpoint_id, 状态可用),
            )
    logger.info("清理过期执行态检查点 %s 份", len(过期ID))
    return len(过期ID)
