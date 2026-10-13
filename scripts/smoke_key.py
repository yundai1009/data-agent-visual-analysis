# 一句话定位：部署后手工冒烟脚本（非 pytest、非运行时路径）——按真实 HTTP 打一遍账号级 LLM Key 的
# 增删查链路，验证 `AUTH_ENABLED=true` 下的认证与脱敏行为。
#
# 做了什么：顶层顺序执行，无函数无 main——`POST /auth/login`（e2e_user/test123）拿 token 塞进
# `Authorization` 头，然后 `GET`/`PUT`/`GET`/`DELETE`/`GET` `/auth/llm-key`，用两个 `assert` 验证
# `has_key` 先变 True 再变 False，并打印脱敏后的 `masked`。
#
# 为什么这么做：
#   - 不写成 pytest：它要打一个真的在 8000 端口跑着的服务、还要一个真实账号，是验收冒烟不是单测，进测试套件只会让无服务的 CI 必红。
#   - 只用假 Key `sk-test-1234567890abcdef`：本脚本验的是"保存/脱敏/清除"的存储链路，不验上游连通性（那是 `/auth/llm-providers/test` 的事），所以永不产生真实调用与账单。
#   - 全脚本不设 try/except：冒烟脚本就该在任何一步出错时立刻炸出来并带非零退出码。
#
# 关键约定与坑：
#   - 硬编码 `BASE = "http://127.0.0.1:8000"` 与账号 `e2e_user/test123`：换环境要手改，没有参数入口。
#   - `assert` 在 `python -O` 下会被剥掉，本脚本必须用普通 `python scripts/smoke_key.py` 跑。
#   - 跑完会把该账号的 Key 清成空（脚本最后一步是 DELETE），不会自动还原。
"""smoke: account-level LLM Key end-to-end (AUTH_ENABLED=true)."""
import requests
import sys

BASE = "http://127.0.0.1:8000"
s = requests.Session()
r = s.post(f"{BASE}/auth/login", json={"username": "e2e_user", "password": "test123"}, timeout=5)
if r.status_code != 200:
    print("FATAL: login failed", r.status_code)
    sys.exit(1)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}
print("1. login ok")

r = s.get(f"{BASE}/auth/llm-key", headers=h, timeout=5)
print(f"2. GET key: {r.json()}")

r = s.put(f"{BASE}/auth/llm-key", json={"api_key": "sk-test-1234567890abcdef"}, headers=h, timeout=5)
print(f"3. PUT key: {r.status_code}")

r = s.get(f"{BASE}/auth/llm-key", headers=h, timeout=5)
assert r.json()["has_key"] is True
print(f"4. GET key: has_key={r.json()['has_key']} masked={r.json()['masked']}")
print("   [PASS] save+mask verified")

r = s.delete(f"{BASE}/auth/llm-key", headers=h, timeout=5)
r = s.get(f"{BASE}/auth/llm-key", headers=h, timeout=5)
assert r.json()["has_key"] is False
print(f"5. DELETE then GET: has_key={r.json()['has_key']}")
print("   [PASS] delete verified")
print("\n[PASS] account-level key smoke test complete")
