"""并发验证：/reports/generate-stream 超过 4 并发应返回 503（安全修复验证）。

用法: python scripts/verify_concurrency.py
前置：后端运行在 127.0.0.1:8000，账号 e2e_user/test123
"""
import concurrent.futures
import sys
import time

import requests

BASE = "http://127.0.0.1:8000"
s = requests.Session()
r = s.post(f"{BASE}/auth/login", json={"username": "e2e_user", "password": "test123"})
if r.status_code != 200:
    print("FATAL: login failed", r.text[:120]); sys.exit(1)
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

csv = "地区,销售额\n华东,100\n华南,200\n华北,150\n"
r = s.post(f"{BASE}/datasets/upload", headers=headers, files={"file": ("c.csv", csv, "text/csv")})
did = r.json()["数据集ID"]
payload = {
    "数据集ID": did, "分析需求": "各地区销售额对比", "图表类型": "自动推荐",
    "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
}

def call(i):
    t0 = time.time()
    try:
        # 真正模拟"发起即断开"：stream=True 只读响应头，with 退出即关闭连接，
        # 后端 worker 仍在后台生成（无人消费）
        with requests.post(f"{BASE}/reports/generate-stream", headers=headers,
                           json=payload, timeout=5, stream=True) as r:
            return i, r.status_code, round(time.time() - t0, 2)
    except Exception as exc:
        return i, f"exc:{type(exc).__name__}", round(time.time() - t0, 2)

# 12 个并发（远超上限 4）
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
    results = list(ex.map(call, range(12)))

codes = [c for _, c, _ in results]
print("并发结果:", results)
ok = sum(1 for c in codes if c == 200)
busy = sum(1 for c in codes if c == 503)
print(f"200={ok}  503={busy}  其他={[c for c in codes if c not in (200, 503)]}")
assert busy > 0, "应出现 503（并发限制未生效）"
assert ok > 0, "应至少一个成功"
print("[PASS] 并发限制生效：超出 4 并发的请求返回 503")

# 名额恢复验证：断开的 worker 应自然结束并释放并发名额，随后正常请求应恢复 200
time.sleep(3)  # 等待后台 worker 结束（无 LLM 环境生成约 0.1s）
r = s.post(f"{BASE}/reports/generate-stream", headers=headers, json=payload, timeout=10)
assert r.status_code == 200, f"名额未恢复，应 200，实际 {r.status_code}"
print("[PASS] 断开后名额恢复：正常请求重新获得 200")
