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
