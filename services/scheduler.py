"""定时调度服务（阶段 30 · 定时生成）：cron 解析 + 后台线程 + 作业执行。

这个文件管什么：
    1. cron匹配(表达式, dt)——5 字段 cron（分 时 日 月 周）匹配判断，
       支持 *、数字、逗号列表、a-b 范围、*/n 步进；
    2. 启动调度器()——daemon 线程每 30 秒 tick 一次，找出当前分钟命中的
       启用任务并执行；
    3. 执行作业()——读模板配置 → 读数据集最新数据 → 生成报表入库，
       结果落入用户报表历史（与手动生成一致）。

为什么自写而不是引 APScheduler：
    项目理念是"零外部服务、依赖全版本锁定"；五分钟字段的 cron 解析
    约 60 行即可覆盖业务场景（每周一早 9 点 = "0 9 * * 1"），
    不引入新依赖。若未来需要复杂调度（时区/重叠保护）再评估迁移。

删除它会怎样：定时任务全部停摆，只剩手动生成。

替代方案：Windows 计划任务外部触发——需要部署方额外配置且报表
落入不了用户可见的历史；内嵌线程最简单且对用户透明。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TICK_INTERVAL = 30  # 秒；30s 粒度保证每分钟至少检查两次（防漂移丢分钟）
_scheduler_lock = threading.Lock()
_scheduler_thread: Optional[threading.Thread] = None

# S8 修复：进程内"执行中"任务集合——慢任务执行期间不再重复触发，
# 并限制并发作业数，防止线程无限堆积。
_in_flight: set = set()
_in_flight_lock = threading.Lock()
_MAX_CONCURRENT_JOBS = 5
# P0 修复（Bug28）：单作业超时保护（秒）——LLM 分析卡住时强制释放 in_flight
_JOB_TIMEOUT_SEC = 300  # 5 分钟：覆盖绝大多数分析任务；超时后作业后台丢弃


# ═══ 1. cron 解析（5 字段：分 时 日 月 周）═══

def cron合法(表达式: str) -> bool:
    """语法校验：5 字段且每字段模式合法（*、数字、a-b、列表、*/n）。

    注意：不能用"当前时间是否命中"来校验——"0 9 * * 1"在非周一永远不命中。
    """
    parts = str(表达式).strip().split()
    if len(parts) != 5:
        return False
    for part in parts:
        if not _字段模式合法(part):
            return False
    return True


def _字段模式合法(模式: str) -> bool:
    """单字段模式合法性：* / 数字 / a-b / a,b,c / */n（n>0）。"""
    模式 = 模式.strip()
    if not 模式:
        return False
    if 模式 == "*":
        return True
    if 模式.startswith("*/"):
        return 模式[2:].isdigit() and int(模式[2:]) > 0
    for item in 模式.split(","):
        item = item.strip()
        if not item:
            return False
        if "-" in item and not item.startswith("-"):
            lo, hi = item.split("-", 1)
            if not (lo.isdigit() and hi.isdigit()):
                return False
        elif not item.isdigit():
            return False
    return True


def cron匹配(表达式: str, dt: Optional[datetime] = None) -> bool:
    """判断 dt（默认当前时间）是否命中 cron 表达式。

    支持模式：* 任意、5 固定值、1,3,5 列表、1-5 范围、*/15 步进。
    周字段 0=周日，6=周六（标准 cron）。7 也视为周日（兼容标准 cron）。
    """
    if dt is None:
        dt = datetime.now()
    parts = str(表达式).strip().split()
    if len(parts) != 5:
        return False
    分, 时, 日, 月, 周 = parts
    # Python weekday(): 0=周一…6=周日；标准 cron 周字段：0=周日…6=周六 → (weekday+1)%7
    _周值 = (dt.weekday() + 1) % 7
    return (
        _字段匹配(分, dt.minute)
        and _字段匹配(时, dt.hour)
        and _字段匹配(日, dt.day)
        and _字段匹配(月, dt.month)
        and _匹配周字段(周, _周值)
    )


def _字段匹配(模式: str, 值: int) -> bool:
    模式 = 模式.strip()
    if 模式 == "*":
        return True
    for part in 模式.split(","):
        part = part.strip()
        if not part:
            continue
        if part.startswith("*/"):
            try:
                step = int(part[2:])
                if step > 0 and 值 % step == 0:
                    return True
            except ValueError:
                continue
        elif "-" in part and not part.startswith("-"):
            try:
                lo, hi = part.split("-", 1)
                if int(lo) <= 值 <= int(hi):
                    return True
            except ValueError:
                continue
        else:
            try:
                if int(part) == 值:
                    return True
            except ValueError:
                continue
    return False


def _匹配周字段(模式: str, 值: int) -> bool:
    """周字段匹配：兼容标准 cron 的 7=周日（与 0 同义）。

    Python weekday 映射把周日记为 0，标准 cron 允许 0 或 7 表示周日；
    旧实现只认 0，用户写 ``0 9 * * 7`` 时任务永不触发（静默失效）。
    这里对周日（值=0）额外识别模式中出现的独立 ``7`` 或范围端点含 7/0。
    """
    if 值 == 0:
        for part in 模式.split(","):
            part = part.strip()
            if part in ("0", "7"):
                return True
            if "-" in part and not part.startswith("-"):
                try:
                    lo, hi = part.split("-", 1)
                    lo_n, hi_n = int(lo), int(hi)
                except ValueError:
                    continue
                # 范围端点含 0 或 7 都覆盖周日（如 1-7 表示周一到周日）
                if lo_n <= 0 <= hi_n or lo_n <= 7 <= hi_n:
                    return True
    return _字段匹配(模式, 值)


def 下次执行时间(表达式: str, 起点: Optional[datetime] = None, 窗口分钟: int = 7 * 24 * 60) -> Optional[str]:
    """从起点（默认当前）往后找首次命中时间（窗口默认 7 天），ISO 字符串或 None。"""
    if 起点 is None:
        起点 = datetime.now()
    base = 起点.replace(second=0, microsecond=0)
    for i in range(窗口分钟):
        cand = base + timedelta(minutes=i)
        if cron匹配(表达式, cand):
            return cand.isoformat()
    return None


# ═══ 2. 作业执行 ═══

def 执行作业(任务: Dict[str, Any]) -> str:
    """执行一个定时任务：模板配置 + 数据集最新数据 → 新报表入库。

    返回 "ok" / 失败原因字符串。失败不影响其他任务（调度循环继续）。
    注意：定时任务没有 HTTP 请求上下文，LLM 配置用 用户账号 key → EnvConfig 兜底，
    不走请求级 provider 白名单（与手动生成语义一致：用户自己的 key 优先）。
    """
    try:
        from api.contracts import ReportGenerateRequest
        from config.settings import EnvConfig, LLMRequestConfig
        from repositories import report_repo, schedule_repo, template_repo, user_repo
        from 后端_核心.report_generator import 生成报表数据

        user_id = 任务["用户ID"]
        tpl = template_repo.读取模板(user_id, 任务["模板ID"])
        if not tpl:
            schedule_repo.记录执行结果(user_id, 任务["任务ID"], "失败: 模板不存在或已删除")
            return "模板不存在或已删除"
        payload = ReportGenerateRequest(**tpl["payload"])

        # 数据集最新数据（校验归属 + 存在）
        from api.routes.datasets import _仓储
        item = _仓储.读取(user_id, payload.数据集ID)
        if not item:
            schedule_repo.记录执行结果(user_id, 任务["任务ID"], "失败: 数据集不存在或已删除")
            return "数据集不存在或已删除"
        df = item["数据"]

        # LLM 配置：用户账号 key 优先，兜底 EnvConfig 全局
        api_key = user_repo.读取LLMKey(user_id) or EnvConfig.LLM_API_KEY or ""
        # 【Bug34 修复】原 provider 硬编码 "deepseek"，导致用户选 GPT-4o/自定义供应商后
        # 定时任务仍走 deepseek（静默走错 provider）。改为从模板 payload.model 匹配 provider：
        # payload.model 存在且在 LLM_PROVIDERS 某 provider 的 models 列表中 → 用该 provider；
        # 否则 fallback EnvConfig.LLM_MODEL 匹配，最终兜底 "deepseek"。
        _saved_model = payload.model or EnvConfig.LLM_MODEL or ""
        _matched = None
        for _pname, _pcfg in (getattr(EnvConfig, "LLM_PROVIDERS") or {}).items():
            _all_models = list(_pcfg.get("models") or []) + [_pcfg.get("default_model", "")]
            if _saved_model in _all_models:
                _matched = _pname
                break
        provider = _matched or "deepseek"
        provider_conf = getattr(EnvConfig, "LLM_PROVIDERS", {}).get(provider, {})
        llm_config = LLMRequestConfig(
            provider=provider,
            base_url=provider_conf.get("base_url", EnvConfig.LLM_BASE_URL),
            model=provider_conf.get("default_model", EnvConfig.LLM_MODEL),
            api_key=api_key,
        )

        report = 生成报表数据(
            df=df,
            分析需求=payload.分析需求,
            图表类型=payload.图表类型,
            x轴=payload.x轴,
            y轴=payload.y轴,
            分组字段=payload.分组字段,
            聚合方式=payload.聚合方式,
            筛选条件=[c.model_dump() for c in payload.筛选条件],
            topN=payload.topN,
            llm_config=llm_config,
            user_id=user_id,
        )
        report_repo.保存报表(
            user_id, payload.数据集ID,
            report["标题"], report["图表类型"], report,
        )
        schedule_repo.记录执行结果(user_id, 任务["任务ID"], "成功")
        logger.info("定时任务 %s 执行成功（用户 %s）", 任务["任务ID"], user_id)
        return "ok"
    except Exception as exc:  # noqa: BLE001 —— 调度循环必须兜住一切异常
        logger.exception("定时任务 %s 执行失败: %s", 任务.get("任务ID"), exc)
        try:
            from repositories import schedule_repo
            schedule_repo.记录执行结果(任务["用户ID"], 任务["任务ID"], f"失败: {exc}")
        except Exception:
            pass
        return str(exc)


# ═══ 3. 调度线程 ═══

def _tick() -> None:
    """检查并执行当前分钟命中的所有启用任务。"""

    def _同分钟(iso: Optional[str], now: datetime) -> bool:
        if not iso:
            return False
        try:
            last = datetime.fromisoformat(iso)
            return last.year == now.year and last.month == now.month \
                and last.day == now.day and last.hour == now.hour and last.minute == now.minute
        except ValueError:
            return False

    from repositories import schedule_repo

    now = datetime.now()
    for 任务 in schedule_repo.查启用的任务():
        if cron匹配(任务["cron"], now) and not _同分钟(任务["上次执行"], now):
            # S8 修复：任务执行中（_in_flight 含任务ID）跳过本轮，避免慢任务
            # 未结束时重复触发；并发作业数封顶，防线程无限增长。
            with _in_flight_lock:
                if 任务["任务ID"] in _in_flight or len(_in_flight) >= _MAX_CONCURRENT_JOBS:
                    continue
                _in_flight.add(任务["任务ID"])
            threading.Thread(target=_执行并释放, args=(任务,), daemon=True).start()


def _执行并释放(任务: Dict[str, Any]) -> None:
    """S8：执行作业并在 finally 中释放 in_flight 标记（异常也不残留）。

    P0 修复（Bug28）：LLM 分析可能长时间挂起（网络/超时重试），若作业线程
    永不结束，in_flight 标记永久占用，_MAX_CONCURRENT_JOBS 上限被耗尽后
    所有后续定时任务被跳过。这里用守护线程 + join(timeout) 做超时保护：
    超时后强制释放标记（线程仍 daemon 后台继续，结果丢弃），保证调度不瘫。
    """
    worker = threading.Thread(target=执行作业, args=(任务,), daemon=True, name=f"cron-job-{任务['任务ID'][:8]}")
    worker.start()
    worker.join(timeout=_JOB_TIMEOUT_SEC)
    if worker.is_alive():
        logger.warning("定时任务 %s 执行超时（%ds 强制释放 in_flight，作业仍在后台）", 任务["任务ID"], _JOB_TIMEOUT_SEC)
    with _in_flight_lock:
        _in_flight.discard(任务["任务ID"])


def _循环() -> None:
    while True:
        try:
            _tick()
        except Exception:
            logger.exception("调度 tick 异常（不影响下一轮）")
        time.sleep(_TICK_INTERVAL)


def 启动调度器() -> None:
    """幂等启动调度线程（daemon，随进程退出）。"""
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return
        _scheduler_thread = threading.Thread(target=_循环, daemon=True, name="cron-scheduler")
        _scheduler_thread.start()
        logger.info("定时调度器已启动（每 %ss tick 一次）", _TICK_INTERVAL)