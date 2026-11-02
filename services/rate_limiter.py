"""限流后端（阶段八十七）：Redis 固定窗口优先，Redis 不可用时回落进程内 dict。

做了什么
========
- `内存固定窗口`：迁出前 `api/routes/auth.py::_窗口限流` 的逐行等价实现（进程内 dict +
  线程锁 + 容量上限）。多 worker 下各持一份，是**刻意保留的降级路径**。
- `Redis固定窗口`：`INCR` + 首次 `EXPIRE` 的固定窗口，所有 worker / 进程共享同一份计数。
- `取限流器()`：按 `EnvConfig.REDIS_RATE_LIMIT` 选后端，Redis 连不上就回落内存实现。

为什么这么做
==========
- 迁移动机：进程内 dict 的登录限流换个账号或起第二个 worker 就能绕过（历史欠账 §8）。
  Redis 让「IP+账号 5 次 / 纯 IP 20 次」在多 worker 部署下仍然成立。
- 为什么保留内存实现：限流是安全增强，不是可用性前置条件。Redis 没装 / 没起 /
  网络不通时若直接报错，「登录接口全站 500」比「限流失效」严重得多。降级只告警。

关键约定与坑
==========
- 两个后端对外语义**逐次对齐**：第 1..max_fails 次放行，第 max_fails+1 次起拦截。
  旧实现是「检查 count >= max_fails 再自增」，Redis 是「INCR 后判断 n > max_fails」，
  数学上等价，改任一侧都必须重新对一遍边界（有用例锁定）。
- Redis 键统一加 `键前缀`，避免与同一实例上的其它应用撞键；`清除()` 必须用同一前缀。
- Redis 报错一律 **fail-open（放行 + 告警）**：宁可漏拦一次，也不让 Redis 抖动把登录打死。
- 单例缓存在 `_限流器`；测试要换后端必须调用 `重置限流器()`，否则下一次 命中 还用旧对象。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

from config.settings import EnvConfig

logger = logging.getLogger(__name__)


class 内存固定窗口:
    """进程内固定窗口限流（迁出前实现的等价搬运）。

    `capacity` 是字典条目上限：达到上限直接清空整个 dict（旧实现的行为）。
    代价是清空瞬间会丢掉其它键的合法计数——只在极端流量下发生，换来的是内存不无限增长。
    """

    def __init__(self, capacity: int = 5000) -> None:
        self._store: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._capacity = capacity

    def 命中(self, key: str, max_fails: int, window_sec: int) -> bool:
        """记一次尝试；返回 True = 本次应被拦截。"""
        now = time.time()
        with self._lock:
            # 容量清理必须在锁内：旧实现在 with lock 之前 clear，多线程同时到达时
            # 可能各自清空 store，丢掉别的线程刚写入的合法计数（限流被绕过）。
            if len(self._store) >= self._capacity:
                self._store.clear()
            window_start, count = self._store.get(key, (now, 0))
            if now - window_start > window_sec:
                self._store[key] = (now, 1)
                return False
            if count >= max_fails:
                return True
            self._store[key] = (window_start, count + 1)
            return False

    def 清除(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)


class Redis固定窗口:
    """Redis 固定窗口限流：INCR 计数 + 窗口期 TTL，多 worker 共享。"""

    键前缀 = "daa:rl:"

    def __init__(self, client: Any) -> None:
        self._client = client

    def 命中(self, key: str, max_fails: int, window_sec: int) -> bool:
        """记一次尝试；返回 True = 本次应被拦截。

        第 1..max_fails 次放行（n<=max_fails），第 max_fails+1 次起拦截——与内存实现对齐。
        被拦截时仍然 INCR，窗口内计数继续累积；EXPIRE 只在首次写入时设置，
        所以窗口起点固定为「本轮第一次尝试」，不会因为持续尝试被无限延长。
        """
        完整键 = self.键前缀 + key
        try:
            n = int(self._client.incr(完整键))
            if n == 1:
                self._client.expire(完整键, window_sec)
            return n > max_fails
        except Exception:  # noqa: BLE001 - fail-open：限流不该成为可用性单点
            logger.warning("Redis 限流不可用，本次放行（fail-open）", exc_info=True)
            return False

    def 清除(self, key: str) -> None:
        try:
            self._client.delete(self.键前缀 + key)
        except Exception:  # noqa: BLE001 - 清失败只影响「成功登录后重置计数」的体验
            logger.warning("Redis 清除限流键失败", exc_info=True)


_限流器: Optional[Any] = None
_锁 = threading.Lock()


def _构建限流器() -> Any:
    if not EnvConfig.REDIS_RATE_LIMIT or not EnvConfig.REDIS_URL:
        logger.info("限流后端：进程内 dict（REDIS_RATE_LIMIT 未开启）")
        return 内存固定窗口()
    try:
        import redis  # 延迟导入：没装 redis 包也应能跑（回落内存实现）

        client = redis.Redis.from_url(
            EnvConfig.REDIS_URL,
            socket_connect_timeout=EnvConfig.REDIS_TIMEOUT,
            socket_timeout=EnvConfig.REDIS_TIMEOUT,
            decode_responses=True,
        )
        client.ping()
        logger.info("限流后端：Redis %s（多 worker 共享窗口）", EnvConfig.REDIS_URL)
        return Redis固定窗口(client)
    except Exception as exc:  # noqa: BLE001 - 任何异常都回落，不阻断启动
        logger.warning(
            "Redis 不可用（%s），限流回落到进程内 dict；多 worker 下各持一份窗口，属已知降级",
            exc,
        )
        return 内存固定窗口()


def 取限流器() -> Any:
    """返回进程级限流器单例（首次调用时选后端并连接）。"""
    global _限流器
    if _限流器 is not None:
        return _限流器
    with _锁:
        if _限流器 is None:
            _限流器 = _构建限流器()
    return _限流器


def 重置限流器() -> None:
    """丢弃单例，下次 取限流器() 重新按当前配置选后端（供测试与配置热变更用）。"""
    global _限流器
    with _锁:
        _限流器 = None
