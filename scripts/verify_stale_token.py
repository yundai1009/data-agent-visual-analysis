"""根因实证 + 修复验证：token 残留时前端行为。

正式模式（AUTH_ENABLED=true）期望：
- 无效 token（默认）→ 自动登出 → 跳 /login + token 清空
- 有效 token（--valid，登录 e2e_user/test123）→ 不误踢 → 停留 /data
演示模式（AUTH_ENABLED=false，传 --demo）期望：不误踢 → 停留 /data 正常使用

用法: python scripts/verify_stale_token.py [--demo] [--valid]
前置：后端运行在 127.0.0.1:8000
"""
import sys
import time

from playwright.sync_api import sync_playwright

DEMO = "--demo" in sys.argv
VALID = "--valid" in sys.argv
BASE = "http://127.0.0.1:8000"
INVALID_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1X2JhZCIsImV4cCI6MTg5MzQ1NjAwMH0.invalid-signature"

if VALID:
    import requests
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": "e2e_user", "password": "test123"}, timeout=5)
    if r.status_code != 200:
        print("FATAL: 登录 e2e_user 失败（需先注册）", r.text[:120]); sys.exit(1)
    TOKEN = r.json()["access_token"]
else:
    TOKEN = INVALID_TOKEN

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(f"{BASE}/login")
    page.evaluate(
        """([token]) => {
            localStorage.setItem('access_token', token);
            localStorage.setItem('user_cache', JSON.stringify({username:'stale', role:'analyst'}));
        }""",
        [TOKEN],
    )
    # 带 token 打开受保护页（有效→应停留；无效→应自动登出）
    page.goto(f"{BASE}/data")
    page.wait_for_timeout(2500)
    url = page.url
    body = page.inner_text("body")[:300].replace("\n", " | ").encode("gbk", "replace").decode("gbk")
    token_val = page.evaluate("() => localStorage.getItem('access_token') || ''")
    token_left = bool(token_val)
    print(f"URL: {url}")
    print(f"token 残留值: {(token_val[:24] + '...') if token_val else '(空)'}")
    print(f"页面内容: {body}")
    print(f"token 是否仍残留: {token_left}")
    if DEMO:
        ok = "/data" in url  # 演示模式不校验 token：应正常停留，不误踢
        print("[OK] 演示模式不误踢（停留数据页正常使用）" if ok
              else "[FAIL] 演示模式被误踢出登录页")
    elif VALID:
        ok = "/data" in url  # 有效 token：应停留，不误踢
        print("[OK] 有效 token 不误踢（停留数据页正常使用）" if ok
              else "[FAIL] 有效 token 被误踢出登录页")
    else:
        ok = "/login" in url and not token_left  # 正式模式：应登出跳登录页且 token 清空
        print("[OK] 正式模式自动登出（跳登录页 + token 已清空）" if ok
              else "[FAIL] 正式模式未自动登出")
    browser.close()
    sys.exit(0 if ok else 1)
