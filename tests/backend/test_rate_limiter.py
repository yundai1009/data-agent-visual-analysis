# tests/backend/test_rate_limiter.py
"""阶段八十七：限流后端（services/rate_limiter.py）单测。

- 内存固定窗口：边界语义必须与迁出前的 _窗口限流 逐次对齐
  （第 1..max_fails 放行，第 max_fails+1 次起拦截；窗口过期重置；清除）。
- Redis固定窗口：用假 client 验证 INCR/EXPIRE/FAIL-OPEN 行为，不依赖真实 Redis。
- 取限流器：REDIS_RATE_LIMIT=false（conftest 钉死）必须返回内存实现。
"""

import time

from services import rate_limiter
from services.rate_limiter import Redis固定窗口, 内存固定窗口


class _FakeRedis:
    """最小假 Redis：只实现本模块用到的 INCR/EXPIRE/DELETE/PING。"""

    def __init__(self):
        self.store = {}
        self.expires = {}

    def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key, ttl):
        self.expires[key] = ttl
        return True

    def delete(self, key):
        self.store.pop(key, None)
        self.expires.pop(key, None)
        return 1

    def ping(self):
        return True


def test_内存_边界与内存实现逐次对齐():
    limiter = 内存固定窗口(capacity=5000)
    # 第 1..max_fails 次放行，第 max_fails+1 次起拦截
    for i in range(1, 6):
        assert limiter.命中("k", 5, 600) is False, f"第 {i} 次应放行"
    assert limiter.命中("k", 5, 600) is True, "第 6 次应被拦截"
    # 不同 key 互不影响
    assert limiter.命中("other", 5, 600) is False


def test_内存_窗口过期后重置():
    limiter = 内存固定窗口()
    for _ in range(5):
        limiter.命中("k", 5, 600)
    assert limiter.命中("k", 5, 600) is True
    # 伪造窗口起点已过期：直接改内部状态模拟时间流逝（不 sleep）
    limiter._store["k"] = (time.time() - 601, 5)
    assert limiter.命中("k", 5, 600) is False, "过期后应重置计数并放行"


def test_内存_清除后重新计数():
    limiter = 内存固定窗口()
    for _ in range(5):
        limiter.命中("k", 5, 600)
    assert limiter.命中("k", 5, 600) is True
    limiter.清除("k")
    assert limiter.命中("k", 5, 600) is False, "清除后应从头计数"


def test_内存_容量上限清空():
    limiter = 内存固定窗口(capacity=3)
    limiter.命中("a", 5, 600)
    limiter.命中("b", 5, 600)
    limiter.命中("c", 5, 600)
    # 第 4 个 key 触达容量 → 整体清空
    assert limiter.命中("d", 5, 600) is False
    assert len(limiter._store) == 1, "触达容量应清空旧条目"


def test_redis_边界与内存语义一致():
    client = _FakeRedis()
    limiter = Redis固定窗口(client)
    for i in range(1, 6):
        assert limiter.命中("k", 5, 600) is False, f"第 {i} 次应放行"
    assert limiter.命中("k", 5, 600) is True, "第 6 次应被拦截"
    # 首次写入才设 EXPIRE，窗口起点固定
    assert client.expires["daa:rl:k"] == 600


def test_redis_失败时fail_open放行():
    class _断连:
        def incr(self, key):
            raise ConnectionError("redis down")

    limiter = Redis固定窗口(_断连())
    assert limiter.命中("k", 5, 600) is False, "Redis 异常必须放行（fail-open），不能把登录打死"


def test_redis_清除删除键():
    client = _FakeRedis()
    limiter = Redis固定窗口(client)
    limiter.命中("k", 5, 600)
    assert "daa:rl:k" in client.store
    limiter.清除("k")
    assert "daa:rl:k" not in client.store


def test_取限流器_未开启Redis时返回内存实现():
    # conftest 已把 REDIS_RATE_LIMIT 置 false，这里再显式重置一次，确保是干净起点
    rate_limiter.重置限流器()
    try:
        limiter = rate_limiter.取限流器()
        assert isinstance(limiter, 内存固定窗口), "REDIS_RATE_LIMIT=false 必须用内存实现"
    finally:
        rate_limiter.重置限流器()


def test_重置限流器_丢弃单例():
    rate_limiter.重置限流器()
    a = rate_limiter.取限流器()
    rate_limiter.重置限流器()
    b = rate_limiter.取限流器()
    rate_limiter.重置限流器()
    assert a is not b, "重置后必须新建实例（测试隔离 / 配置热变更）"


def test_取限流器_Redis不可用时回落内存实现(monkeypatch):
    """Redis 开着开关却连不上：必须回落内存实现而不是抛异常（限流不是可用性前置条件）。

    指向一个必然关闭的端口（6399）并压到 0.2 秒超时，避免用例被网络等待拖慢。
    """
    monkeypatch.setattr(rate_limiter.EnvConfig, "REDIS_RATE_LIMIT", True)
    monkeypatch.setattr(rate_limiter.EnvConfig, "REDIS_URL", "redis://127.0.0.1:6399/0")
    monkeypatch.setattr(rate_limiter.EnvConfig, "REDIS_TIMEOUT", 0.2)
    rate_limiter.重置限流器()
    try:
        limiter = rate_limiter.取限流器()
        assert isinstance(limiter, 内存固定窗口), "连不上 Redis 必须回落内存实现"
    finally:
        rate_limiter.重置限流器()
