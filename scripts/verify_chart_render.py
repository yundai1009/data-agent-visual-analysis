"""验证：报表页图表是否真正渲染（canvas 存在且有内容，无"图表加载中"残留）。"""
import sys
import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
s = requests.Session()
r = s.post(f"{BASE}/auth/login", json={"username": "e2e_user", "password": "test123"}, timeout=5)
if r.status_code != 200:
    print("FATAL login"); sys.exit(1)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

csv = "地区,销售额,日期\n华东,100,2024-01-01\n华南,200,2024-01-02\n华北,150,2024-01-03\n东北,80,2024-01-04"
r = s.post(f"{BASE}/datasets/upload", headers=h, files={"file": ("s.csv", csv, "text/csv")})
did = r.json()["数据集ID"]
r = s.post(f"{BASE}/reports/generate", headers=h, json={
    "数据集ID": did, "分析需求": "各地区销售额占比", "图表类型": "饼图",
    "x轴": "地区", "y轴": ["销售额"], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
})
rid = r.json()["报表ID"]
print("报表ID:", rid)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    console_msgs = []
    page.on("console", lambda m: console_msgs.append(m.text) if m.type == "error" else None)
    page.goto(f"{BASE}/login")
    page.evaluate("""([t]) => localStorage.setItem('access_token', t)""", [token])
    page.goto(f"{BASE}/report/{rid}")
    page.wait_for_timeout(4000)
    page.screenshot(path="docs/verify-chart-render.png", full_page=False)
    info = page.evaluate("""() => {
        const canvas = document.querySelector('canvas');
        const loading = document.body.innerText.includes('图表加载中');
        const err = document.body.innerText.includes('图表渲染异常');
        return {
            hasCanvas: !!canvas,
            canvasSize: canvas ? [canvas.width, canvas.height] : null,
            loadingText: loading,
            errorText: err,
            pageText: document.body.innerText.slice(0, 200),
        };
    }""")
    print("图表检查:", str(info).encode("gbk", "replace").decode("gbk"))
    print("控制台错误:", console_msgs[:5] if console_msgs else "无")
    ok = info["hasCanvas"] and info["canvasSize"][0] > 100 and not info["loadingText"] and not info["errorText"]
    print("[PASS] 图表渲染正常" if ok else "[FAIL] 图表未渲染")
    browser.close()
    sys.exit(0 if ok else 1)
