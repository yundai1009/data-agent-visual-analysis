"""UI 验证：分析直播界面 + 侧边栏玻璃 + 404 页截图（Playwright）。

用法: python scripts/verify_ui.py
前置：后端已运行在 127.0.0.1:8000，且已有账号 e2e_user/test123
"""
import json
import sys
import time

import requests
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"
OUT = "docs"

# 1. 登录 + 上传数据（复用 e2e_user）
s = requests.Session()
r = s.post(f"{BASE}/auth/login", json={"username": "e2e_user", "password": "test123"})
assert r.status_code == 200, r.text
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}

csv = ("地区,渠道,销售额,日期\n"
       "华东,线上,100,2024-01-01\n华东,线下,200,2024-01-02\n"
       "华南,线上,300,2024-01-03\n华南,线下,150,2024-01-04\n"
       "华北,线上,80,2024-01-05\n华北,线下,250,2024-01-06\n")
r = s.post(f"{BASE}/datasets/upload", headers=headers,
           files={"file": ("sales.csv", csv, "text/csv")})
assert r.status_code == 200, r.text
up = r.json()
print("upload ok:", up["数据集ID"], up["文件名"])
user_cache = json.dumps({"username": "e2e_user", "role": "analyst"})
dataset_cache = json.dumps({
    "数据集ID": up["数据集ID"],
    "文件名": up["文件名"],
    "数据画像": up["数据画像"],
})

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()

    # 注入登录态后直接进分析页
    page.goto(f"{BASE}/login")
    page.evaluate(
        """([token, user, dataset]) => {
            localStorage.setItem('access_token', token);
            localStorage.setItem('user_cache', user);
            localStorage.setItem('dataset_cache', dataset);
        }""",
        [token, user_cache, dataset_cache],
    )

    # 2. 分析页（侧边栏玻璃 + 布局）
    page.goto(f"{BASE}/analysis")
    page.wait_for_timeout(1200)
    page.screenshot(path=f"{OUT}/batch3-analysis.png", full_page=False)
    print("saved batch3-analysis.png")

    # 3. 输入需求 → 开始分析 → 截图直播面板
    page.fill("textarea", "按【地区】统计【销售额】占比")
    page.wait_for_timeout(400)
    page.click("text=开始分析")
    page.wait_for_timeout(1600)  # 让决策流出现
    page.screenshot(path=f"{OUT}/batch3-live.png", full_page=False)
    print("saved batch3-live.png")

    # 4. 等待跳转报表页
    page.wait_for_url("**/report/**", timeout=20000)
    page.wait_for_timeout(2500)
    page.screenshot(path=f"{OUT}/batch3-report.png", full_page=False)
    print("saved batch3-report.png")

    # 5. 404 页
    page.goto(f"{BASE}/no-such-page")
    page.wait_for_timeout(1200)
    page.screenshot(path=f"{OUT}/batch3-404.png", full_page=False)
    print("saved batch3-404.png")

    browser.close()
print("[PASS] UI 截图完成")
