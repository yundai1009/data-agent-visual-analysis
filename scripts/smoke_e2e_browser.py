"""真实浏览器 E2E 冒烟（Playwright + Chromium，demo 模式）。

自启动后端（临时 SQLite + frontend/dist-demo），headless Chromium 走完整用户链路：
首页 → 上传数据集 → 生成报表（等待追问条出现）→ 报表页（图表/分享/重放按钮）→
创建分享链接 → 新标签页匿名访问分享页 → 图表看板页。
任意环节失败退出码 1；截图存 scripts/.smoke/。
"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

# CI runner（en-US）默认 stdout 是 cp1252，中文 print 会 UnicodeEncodeError；强制 UTF-8
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT = 8011
BASE = f"http://127.0.0.1:{PORT}"
SHOT_DIR = ROOT / "scripts" / ".smoke"
fail = []


def check(name, ok, extra=""):
    status = "[OK]" if ok else "[FAIL]"
    print(f"  {status} {name}{(' -- ' + extra) if extra else ''}")
    if not ok:
        fail.append(name)


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
    # 临时库 + demo 前端
    tmp_db = Path(tempfile.gettempdir()) / "smoke_e2e_browser.db"
    if tmp_db.exists():
        tmp_db.unlink()
    env = dict(os.environ)
    env["DAA_SQLITE_PATH"] = str(tmp_db)
    env["FRONTEND_DIST"] = str(ROOT / "frontend" / "dist-demo")

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_health():
            print("后端启动失败")
            sys.exit(1)
        print(f"后端就绪 {BASE}")

        SHOT_DIR.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()

            print("\n== 1. 首页（demo 模式自动进入系统）==")
            page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("text=数据管理", timeout=20000)
            check("侧边栏「数据管理」可见", True)
            page.screenshot(path=str(SHOT_DIR / "01-home.png"))

            print("\n== 2. 上传数据集 ==")
            page.goto(BASE + "/data", wait_until="domcontentloaded", timeout=30000)
            csv = SHOT_DIR / "test_data.csv"
            csv.write_text("地区,月份,销售额\n华东,2026-01,100\n华东,2026-02,150\n华南,2026-01,180\n华南,2026-02,90\n华北,2026-01,140\n华中,2026-02,110", encoding="utf-8")
            page.set_input_files("input[type=file]", str(csv))
            # 等待上传完成（出现数据集文件名）
            try:
                page.wait_for_selector("text=test_data.csv", timeout=30000)
                check("数据集上传成功并展示", True)
            except Exception:
                check("数据集上传成功并展示", False, "未找到 test_data.csv")
            page.screenshot(path=str(SHOT_DIR / "02-data.png"))

            print("\n== 3. 智能分析 → 生成报表 ==")
            page.goto(BASE + "/analysis", wait_until="domcontentloaded", timeout=30000)
            page.fill("textarea", "按地区统计销售额")
            page.click("button:has-text('开始分析')")
            try:
                page.wait_for_selector("text=继续追问", timeout=120000)
                check("分析完成（追问条出现）", True)
            except Exception:
                check("分析完成（追问条出现）", False, "120s 超时")
            page.screenshot(path=str(SHOT_DIR / "03-analysis-done.png"))
            page.click("button:has-text('查看报表')")
            page.wait_for_selector("text=报表查看", timeout=20000)
            page.wait_for_timeout(2500)  # echarts 懒加载 + 渲染
            check("报表页打开", True)
            page.screenshot(path=str(SHOT_DIR / "04-report.png"))

            print("\n== 4. 报表页功能入口 ==")
            for label in ("分享", "重放", "Excel", "CSV", "PDF"):
                check(f"按钮「{label}」存在", page.locator(f"button:has-text('{label}')").count() > 0)

            print("\n== 5. 创建分享链接 → 匿名访问 ==")
            page.click("button:has-text('分享')")
            page.wait_for_selector("text=生成分享链接", timeout=10000)
            page.click("button:has-text('生成分享链接')")
            try:
                page.wait_for_selector("text=/s/", timeout=15000)
                check("分享链接生成", True)
            except Exception:
                check("分享链接生成", False)
            # 提取链接：弹窗里 font-mono 文本
            link_text = ""
            try:
                link_text = page.locator(".font-mono").first.inner_text(timeout=5000).strip()
            except Exception:
                pass
            page.screenshot(path=str(SHOT_DIR / "05-share.png"))
            if "/s/" in link_text:
                page2 = ctx.new_page()
                page2.goto(link_text, wait_until="domcontentloaded", timeout=30000)
                try:
                    page2.wait_for_selector("text=分享的报表", timeout=15000)
                    check("匿名访问分享页", True)
                except Exception:
                    check("匿名访问分享页", False)
                page2.screenshot(path=str(SHOT_DIR / "06-shared.png"))
                page2.close()
            else:
                check("匿名访问分享页", False, f"未提取到链接: {link_text[:60]}")

            print("\n== 6. 图表看板页 ==")
            page.goto(BASE + "/dashboard", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("text=图表看板", timeout=15000)
            check("看板页打开", True)
            page.screenshot(path=str(SHOT_DIR / "07-dashboard.png"))

            browser.close()

        print()
        if fail:
            print(f"BROWSER SMOKE FAILED: {len(fail)} items -> {fail}")
            print(f"截图目录: {SHOT_DIR}")
            sys.exit(1)
        print("BROWSER SMOKE PASSED: full UI chain OK")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()


if __name__ == "__main__":
    main()