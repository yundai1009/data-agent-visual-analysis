"""无痕浏览器截图：登录后数据页实际渲染（区分新旧版判断）。"""
import sys
import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
r = requests.post(f"{BASE}/auth/login", json={"username": "e2e_user", "password": "test123"}, timeout=5)
if r.status_code != 200:
    print("FATAL login:", r.status_code, r.text[:100]); sys.exit(1)
TOKEN = r.json()["access_token"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})  # 新 context = 无痕无缓存
    page = ctx.new_page()
    page.goto(f"{BASE}/login")
    page.evaluate(
        """([t]) => {
            localStorage.setItem('access_token', t);
            localStorage.setItem('user_cache', JSON.stringify({username:'e2e_user', role:'analyst'}));
        }""",
        [TOKEN],
    )
    page.goto(f"{BASE}/data")
    page.wait_for_timeout(3000)
    page.screenshot(path="docs/verify-incognito-data.png", full_page=False)
    feats = page.evaluate("""() => {
        const aside = document.querySelector('aside');
        const main = document.querySelector('.flex.h-screen') || document.body.parentElement;
        const root = document.querySelector('#root > div');
        const asideCss = aside ? getComputedStyle(aside) : null;
        const bgCss = root ? getComputedStyle(root) : null;
        return {
            sidebarBg: asideCss ? asideCss.backgroundColor : null,
            sidebarBackdrop: asideCss ? asideCss.backdropFilter : null,
            appBg: bgCss ? bgCss.backgroundImage.slice(0, 80) : null,
            navActive: !!document.querySelector('a[class*=bg-accent]'),
        };
    }""")
    print("特征:", str(feats).encode("gbk", "replace").decode("gbk"))
    print("截图: docs/verify-incognito-data.png")
    browser.close()
