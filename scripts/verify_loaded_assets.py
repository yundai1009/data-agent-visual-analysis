"""决定性验证：模拟"用户双击启动器后浏览器打开 8000"，捕获实际加载的资源。

区分两种可能：
- 浏览器加载的 JS 是 index-DNaz2gQe.js（最新）→ 服务端没问题，用户旧版来自浏览器缓存
- 浏览器加载的是其他旧 hash → 服务端/中间层有问题

用法: python scripts/verify_loaded_assets.py
前置：后端运行在 127.0.0.1:8000
"""
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
NEWEST_JS = "index-DNaz2gQe.js"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    loaded = []
    page.on("request", lambda req: loaded.append(req.url) if "/assets/" in req.url else None)

    page.goto(f"{BASE}/")
    page.wait_for_timeout(2500)
    print("URL:", page.url)
    for u in loaded:
        print("加载资源:", u.split("/")[-1])
    js_assets = [u.split("/")[-1] for u in loaded if u.endswith(".js")]
    ok = any(NEWEST_JS in j for j in js_assets)
    print(f"加载的 JS: {js_assets}")
    if ok:
        print(f"[OK] 浏览器加载的是最新构建 {NEWEST_JS} → 服务端无旧产物，用户旧版来自浏览器缓存")
    else:
        print(f"[FAIL] 浏览器未加载 {NEWEST_JS} → 需查服务端/中间层")
    # 登录页特征（新版双栏）
    has_brand = page.inner_text("body").find("把数据说成一句话") >= 0
    print(f"登录页新版特征（左侧品牌区文案）: {has_brand}")
    browser.close()
    sys.exit(0 if ok else 1)
