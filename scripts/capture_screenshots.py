# -*- coding: utf-8 -*-
"""作品集截图生成：起 demo 服务 → API 造数据 → Playwright 截 6 张页面图。

用法：python scripts/capture_screenshots.py
输出：docs/screenshots/{01..06}-*.png
前置：frontend/dist-demo 已构建（npm run build -- --mode demo --outDir dist-demo）
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PORT = 8021
BASE = f"http://127.0.0.1:{PORT}"
OUT = ROOT / "docs" / "screenshots"

PAGES = [
    ("01-login", "/login", "登录页（Celestial 深空风格）"),
    ("02-data", "/data", "数据管理（画像/洞察）"),
    ("03-analysis", "/analysis", "智能分析（自然语言 + 直播决策流）"),
    ("04-report", "/report/{rid}", "报表（图表/结论/追问溯源）"),
    ("05-dashboard", "/dashboard", "图表看板（多图对比）"),
    ("06-admin", "/admin", "管理后台（用量/审计）"),
]


def wait_health(timeout=30):
    for _ in range(timeout * 2):
        try:
            with urllib.request.urlopen(f"{BASE}/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main():
    tmp_db = Path(tempfile.gettempdir()) / "shot_demo.db"
    if tmp_db.exists():
        tmp_db.unlink()
    env = dict(os.environ)
    env["DAA_SQLITE_PATH"] = str(tmp_db)
    env["FRONTEND_DIST"] = str(ROOT / "frontend" / "dist-demo")
    env["AUTH_ENABLED"] = "false"

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_health():
            print("服务启动失败")
            sys.exit(1)

        import requests

        # API 造数据：上传 → 生成报表 → 建看板
        s = requests.Session()
        r = s.post(f"{BASE}/datasets/upload",
                   files={"file": ("销售数据.csv", "地区,月份,销售额\n华东,2026-01,120\n华东,2026-02,150\n华南,2026-01,180\n华南,2026-02,90\n华北,2026-01,140\n华北,2026-02,110\n华中,2026-01,95\n华中,2026-02,130".encode(), "text/csv")})
        did = r.json()["数据集ID"]
        r = s.post(f"{BASE}/reports/generate",
                   json={"数据集ID": did, "分析需求": "各区域销售额占比", "图表类型": "自动推荐", "agent_mode": "single"})
        rid = r.json()["报表ID"]
        r = s.post(f"{BASE}/dashboards", json={"名称": "销售看板", "报表ID列表": [rid]})
        print("造数据 OK: report", rid)

        # Playwright 截图
        from playwright.sync_api import sync_playwright
        OUT.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
            for name, path, _label in PAGES:
                url = BASE + path.format(rid=rid)
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2200)  # 等图表渲染
                page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)
                print("截图:", name)
            browser.close()

        # 清理看板/数据集数据文件（保留报表便于重跑）
        tmp_db.unlink(missing_ok=True)
        print("完成：", OUT)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


if __name__ == "__main__":
    main()