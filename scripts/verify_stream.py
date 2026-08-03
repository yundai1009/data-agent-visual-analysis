"""端到端验证：注册 → 上传 → 分析直播 SSE → 验证事件流。

用法: python scripts/verify_stream.py <验证码>
"""
import json, sys, time, requests

CODE = sys.argv[1] if len(sys.argv) > 1 else ""
BASE = "http://127.0.0.1:8000"
s = requests.Session()

# 0b. 未指定验证码时：只触发 send-code（验证码打印在 uvicorn 日志），随后退出
if not CODE:
    r = s.post(f"{BASE}/auth/send-code", json={"email": "e2e@test.com"})
    print("send-code:", r.status_code, r.text[:120])
    print("验证码已生成在后端日志（[SMTP_DRY_RUN] ... 验证码=xxxxxx），请用 python scripts/verify_stream.py <验证码> 继续")
    sys.exit(0)

# 1. 注册（dry-run 验证码来自后端日志）
r = s.post(f"{BASE}/auth/register", json={
    "username": "e2e_user", "email": "e2e@test.com", "code": CODE, "password": "test123"
})
print("register:", r.status_code, r.text[:120])

# 2. 登录
r = s.post(f"{BASE}/auth/login", json={"username": "e2e_user", "password": "test123"})
print("login:", r.status_code, r.text[:120])
token = r.json().get("access_token")
if not token:
    print("FATAL: cannot login"); exit(1)

headers = {"Authorization": f"Bearer {token}"}

# 3. 上传示例数据
csv = "地区,销售额,日期\n华东,100,2024-01-01\n华南,200,2024-01-02\n华北,150,2024-01-03\n东北,80,2024-01-04"
files = {"file": ("test.csv", csv, "text/csv")}
r = s.post(f"{BASE}/datasets/upload", headers=headers, files=files)
print("upload:", r.status_code, r.json().get("数据集ID"), r.json().get("行数"), "rows")
did = r.json()["数据集ID"]

# 4. 分析直播 SSE（无 LLM → 降级路径，但仍有 step 事件）
payload = {
    "数据集ID": did, "分析需求": "各地区销售额对比",
    "图表类型": "自动推荐", "x轴": None, "y轴": [],
    "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
}
if len(sys.argv) > 2:
    payload["agent_mode"] = sys.argv[2]  # 可传 multi 验证多智能体
print(f"\n--- SSE 分析直播（agent_mode={payload['agent_mode']}）---")
t0 = time.time()
r = s.post(f"{BASE}/reports/generate-stream", headers={**headers, "Accept": "text/event-stream"},
           json=payload, stream=True)
print("status:", r.status_code, "content-type:", r.headers.get("content-type"))
events = []
for line in r.iter_lines(decode_unicode=True):
    if line.startswith("data: "):
        ev = json.loads(line[6:])
        events.append(ev)
        elapsed = time.time() - t0
        if ev["type"] == "step":
            step = ev["data"]
            print(f"  [{elapsed:.1f}s] step: {step['步骤']} | {step['说明'] or step['理由'] or ''} | {step['状态']}")
        elif ev["type"] == "done":
            print(f"  [{elapsed:.1f}s] DONE: 报表ID={ev['报表ID'][:12]}… 标题={ev['标题']}")
        elif ev["type"] == "error":
            print(f"  [{elapsed:.1f}s] ERROR: {ev['message']}")

types = [e["type"] for e in events]
print(f"\n事件类型序列: {types}")
print(f"总步数: {sum(1 for e in events if e['type']=='step')}")
assert events, "没有收到任何事件"
assert events[-1]["type"] == "done", f"最后事件应为 done，实际: {events[-1]}"
print("[PASS] 分析直播端到端验证通过（step 事件实时推送 + done 事件完成）")
