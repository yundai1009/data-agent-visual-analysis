"""复现用户流程：双击启动器 → 打开根路径 → 登录页（新版？）→ 注册/登录 → 数据页（新版？）。

特征判定：
- 新版：侧边栏半透明玻璃（bg-white/65 + backdrop-blur）、主背景藏青 radial 氛围、
  数据页统计卡主次重排、藏青主色 #0F4C81
- 旧版：纯白侧边栏（bg-white）、纯灰背景 #F7F8FA 或 indigo 紫蓝主色

用法: python scripts/repro_login_flow.py <验证码>
前置：后端运行在 127.0.0.1:8000（AUTH_ENABLED=true），dry-run 验证码在 server.log
"""
import sys
import time

import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
CODE = sys.argv[1] if len(sys.argv) > 1 else "000000"
USER = "flow_repro"
EMAIL = f"{USER}@test.com"

# 0. 触发验证码（dry-run 打印到 server.log，验证码由外部传入）
requests.post(f"{BASE}/auth/send-code", json={"email": EMAIL}, timeout=5)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    # 1. 启动器打开的根路径
    page.goto(f"{BASE}/")
    page.wait_for_timeout(2000)
    print("根路径 URL:", page.url)
    page.screenshot(path="docs/repro-1-root.png", full_page=False)
    root_text = page.inner_text("body")[:200].replace("\n", " | ").encode("gbk", "replace").decode("gbk")
    print("根路径内容:", root_text)

    # 2. 若跳登录页则注册新用户（dry-run 验证码来自 server.log）
    if "/login" in page.url:
        # 切注册
        try:
            page.click("text=去注册")
            page.wait_for_timeout(400)
        except Exception:
            pass
        page.fill('input[placeholder="输入用户名"]', USER)
        page.fill('input[placeholder="用于接收注册验证码"]', EMAIL)
        page.click("text=获取验证码")
        page.wait_for_timeout(800)
        print("已切注册并请求验证码（验证码在 server.log）")
        page.fill('input[maxlength="6"]', CODE)
        page.fill('input[type="password"]', "test123")
        page.screenshot(path="docs/repro-3-register-filled.png", full_page=False)
        page.click("button:has-text('注册')")
        page.wait_for_timeout(3000)
    else:
        print("根路径未跳登录页（演示模式/未受保护），直接尝试输入")
        page.screenshot(path="docs/repro-2-not-login.png", full_page=False)

    # 3. 登录后位置
    print("注册/登录后 URL:", page.url)
    page.wait_for_timeout(2500)
    page.screenshot(path="docs/repro-4-after-login.png", full_page=False)

    # 4. 特征检查
    checks = page.evaluate("""() => {
        const sb = document.querySelector('aside');
        const styles = sb ? getComputedStyle(sb) : null;
        return {
            sidebarBg: styles ? styles.backgroundColor : null,
            sidebarBackdrop: styles ? styles.backdropFilter : null,
            bodyBg: getComputedStyle(document.body).backgroundColor,
            hasLivePanel: !!document.querySelector('[class*=live]'),
            pageText: document.body.innerText.slice(0, 300),
        };
    }""")
    print("特征检查:", str(checks).encode("gbk", "replace").decode("gbk"))
    browser.close()
