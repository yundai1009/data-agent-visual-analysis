"""决定性测试：浏览器走系统代理(127.0.0.1:17891)访问 8000，看加载的 JS hash。

- 若拿到旧 hash → 代理软件在缓存/改写 127.0.0.1:8000 响应（用户旧版元凶实锤）
- 若拿到新 hash → 代理未拦截本地地址，用户旧版另有原因
"""
import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
NEWEST = "index-DNaz2gQe.js"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, proxy={"server": "http://127.0.0.1:17891"})
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    loaded = []
    page.on("request", lambda r: loaded.append(r.url) if "/assets/" in r.url else None)
    try:
        page.goto(f"{BASE}/", timeout=8000)
        page.wait_for_timeout(2500)
    except Exception as exc:
        print("访问失败（可能代理拒绝本地地址）:", str(exc)[:120])
        sys.exit(0)
    js = [u.split("/")[-1] for u in loaded if u.endswith(".js")]
    print("URL:", page.url)
    print("加载的 JS:", js)
    if NEWEST in (js or []):
        print("[OK] 走代理仍是新版 → 代理未拦截本地地址，用户旧版另有原因")
    elif js:
        print("[FAIL] 走代理拿到旧 JS:", js, "→ 代理软件缓存/改写 127.0.0.1 响应（元凶实锤）")
    else:
        print("未加载到任何 JS（页面可能未正常渲染）")
    browser.close()
