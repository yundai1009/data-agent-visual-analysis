"""验证：/auth/llm-providers 推荐预设列表（含中文 label）。"""
import requests, sys
BASE = "http://127.0.0.1:8000"
s = requests.Session()
r = s.post(f"{BASE}/auth/login", json={"username": "e2e_user", "password": "test123"}, timeout=5)
if r.status_code != 200:
    print("login fail", r.status_code); sys.exit(1)
tok = r.json()["access_token"]
r = s.get(f"{BASE}/auth/llm-providers", headers={"Authorization": f"Bearer {tok}"}, timeout=5)
assert r.status_code == 200, r.text
providers = r.json()["providers"]
presets = [p for p in providers if not p.get("custom")]
print(f"推荐预设: {len(presets)} 个")
for p in presets:
    print(f"  {p['label']} [{p['id']}]: {len(p['models'])} 模型 | default={p['default']}")
print("自定义:", [p["label"] for p in providers if p.get("custom")] or "无")
assert len(presets) >= 7, "推荐预设应包含官方供应商"
print("[OK] 推荐预设列表验证通过")
