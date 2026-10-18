# -*- coding: utf-8 -*-
# 一句话定位：目标⑥「真实用户视角全流程实测」的执行器——起真实 MySQL 后端 + 正式前端 dist，
#             用 Chromium 从**注册/登录**开始把一个真人能走的路全走一遍，最后再打一轮极限测试。
#
# 做了什么：
#   - `起后端`：以 DB_BACKEND=mysql / FRONTEND_DIST=frontend/dist / AUTH_ENABLED=true 起一份独立
#     uvicorn（端口 8012，避开用户自己占着的 8000），stdout+stderr 落盘到 `.superpowers/e2e报告/backend.log`
#     ——**验证码邮件的 dry-run 兜底会把验证码打到日志里**，这是本脚本能自动化注册的唯一原因。
#   - `抓验证码`：正则扫后端日志 `验证码=(\d{6})`。SMTP 未配置 → `email_service.发送验证码邮件`
#     走 dry-run 分支 `logger.warning(...)`；root logger 无 handler 时 Python 用 `logging.lastResort`
#     把 WARNING 级打到 stderr，所以这段日志确实会出现。
#   - `跑主链路`：注册 → 登录 → 上传 CSV → 画像 → 智能分析（打**真实 LLM**）→ 报表 → 导出三种格式
#     → 分享链接 + 匿名新标签页访问 → 图表看板 + 关系视图 → 账号页导出我的数据 → 登出后受保护页被拒。
#     每步截图落 `scripts/.e2e_real/<时间戳>/`。
#   - `跑极限测试`：大文件 / 超宽表 / 路径穿越文件名 / SQL 注入串 / XSS 串 / 20 并发 / 无 token /
#     越权读别人报表 / 十万字需求 / 伪造 JWT / 重复注册 / 错验证码。
#   - `收尾`：调 `POST /auth/delete-account` 删账号，再直连 MySQL 核对本轮 username 的残留行数。
#   - `出报告`：`.superpowers/e2e报告/<时间戳>-报告.md` + `-报告.json`。
#
# 为什么这么做：
#   - **不复用 `scripts/smoke_e2e_browser.py`**：那个是 demo 模式（临时 SQLite + dist-demo +
#     AUTH_ENABLED=false），它验的是「零基础演示链路能不能走通」，与本脚本要验的
#     「真实用户 + 真实 MySQL + 认证开启」正好互补；改它会把 CI 冒烟的定位弄脏。
#   - **端口用 8012 而不是 8000**：本机 8000 常被用户自己起的实例占着，抢端口会把人家的进程搞挂。
#   - **不新建测试库**：`daa_app` 账号只有 `daa.*` 的权限（`SHOW GRANTS` 实测无 CREATE DATABASE），
#     硬要建库就得动生产账号权限。所以就在真 `daa` 库跑，靠「唯一用户名前缀 + 结束时删干净」保证可复现。
#   - **用网路拦截拿 token 而不是读 localStorage**：登录态存 localStorage 的键名是实现细节，
#     从 `Authorization` 头里拿是公开契约，脚本不会因为改了存储键就失效。
#   - **极限测试单独一轮而不是混在主链路里**：主链路是「正常用户该有的体验」，极限测试是
#     「不该挂的时候别挂」，两者失败原因不同，分开报才不会把一次 LLM 抖动误判成安全缺陷。
#
# 关键约定与坑：
#   - `--keep` 只影响**要不要删本轮测试账号**，默认删；加 `--keep` 是为了出问题时能现场复看数据。
#   - MySQL 的 `sql_mode` 含 `ONLY_FULL_GROUP_BY` + `STRICT_TRANS_TABLES`（8.0.23 实测），这是本脚本
#     选真库而不是 SQLite 的真正价值：SQLite 放过的脏 SQL 在这里会真报错。
#   - 脚本**不打印任何密码**：`MYSQL_PASSWORD` 只在子进程环境与 pymysql 连接里用，不进 stdout。
#   - 分析那一步要真打 LLM，可能慢也可能失败；失败**不中断**后续步骤（记 FAIL 继续跑），
#     否则一次额度抖动就只剩一条报错，失去全链路体检的意义。
#   - 本脚本会往真 `daa` 库写数据（users/datasets/reports/audit_log…）并在结束时清理，
#     但**不会碰**用户已有的任何一行。
import argparse
import io
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = 8012
BASE = f"http://127.0.0.1:{PORT}"
REPORT_DIR = ROOT / ".superpowers" / "e2e报告"
RUN_ID = time.strftime("%m%d-%H%M%S")
SHOT_DIR = ROOT / "scripts" / ".e2e_real" / RUN_ID
BACKEND_LOG = REPORT_DIR / "backend.log"

FAIL: list[str] = []
PASSED: list[str] = []
NOTES: list[str] = []
# 每项：{"名称","组","通过","细节","耗时秒"}
CASES: list[dict] = []


def check(name, ok, extra="", group="主链路", cost=0.0):
    """记录一条断言。失败会进 FAIL 清单，但**永不中断**后续步骤。"""
    ok = bool(ok)
    CASES.append({
        "名称": name, "组": group, "通过": ok,
        "细节": str(extra)[:400], "耗时秒": round(float(cost), 2),
    })
    (PASSED if ok else FAIL).append(name)
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" -- {str(extra)[:160]}" if extra else ""))
    return ok


def note(msg):
    NOTES.append(str(msg))
    print(f"  [注  ] {msg}")


def 点(page, 选择器, 超时=15000):
    """永不抛异常的点击。真实用户视角的 E2E 里，「元素被遮罩挡住/按钮还没渲染出来」
    是**待记录的观测结果**，不是脚本自己的异常——让它炸掉会连带后面所有步骤都不跑，
    一轮只能得到一条错误。返回是否点成了。"""
    try:
        loc = page.locator(选择器).first
        loc.click(timeout=超时)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [点不动] {选择器} -- {type(e).__name__}")
        return False


# --------------------------------------------------------------------------- HTTP
def http(method, path, body=None, token=None, timeout=60, raw=False):
    """薄薄一层 urllib。返回 (status, payload_text)。非 2xx 不抛异常——失败也要看到状态码。"""
    url = path if path.startswith("http") else BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            if raw:
                return r.status, payload
            return r.status, payload.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        payload = e.read()
        if raw:
            return e.code, payload
        return e.code, payload.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def wait_health(timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BASE + "/healthz", timeout=3) as r:
                if r.status == 200:
                    return json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            time.sleep(1)
    return None


def 起后端(keep_chroma=False):
    env = os.environ.copy()
    env["DB_BACKEND"] = "mysql"
    env["FRONTEND_DIST"] = str(ROOT / "frontend" / "dist")
    env["AUTH_ENABLED"] = "true"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # 阶段六十九：P14 判「断开有没有传到应用层」靠 orchestrator 里那句
    # `logger.info("第 N 轮后收到取消信号…")`。api/main.py 按 LOG_LEVEL 配应用日志，
    # 不设就是 warning（跟打包桌面端同口径），INFO 会被丢掉 —— 这里显式开 info。
    env["LOG_LEVEL"] = "info"
    if not keep_chroma:
        # 真库是硬的，但记忆库不跟着真库走：每轮用独立 chroma 目录，免得把用户的记忆库
        # 搅进测试（记忆条数/指纹/清理水位都会飘）。要连记忆一起验就加 --keep-chroma。
        env["DAA_CHROMA_PATH"] = str(ROOT / "scripts" / ".e2e_real" / RUN_ID / "chroma")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    logfh = open(BACKEND_LOG, "wb")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1",
         "--port", str(PORT), "--workers", "1"],
        cwd=str(ROOT), env=env, stdout=logfh, stderr=subprocess.STDOUT,
    )
    return proc, logfh


def 抓验证码(email, timeout=30):
    """从后端日志里捞 dry-run 打出来的验证码；没有就是没发出去。"""
    pat = re.compile(re.escape(email) + r".*?验证码=(\d{6})")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if BACKEND_LOG.exists():
            txt = BACKEND_LOG.read_text(encoding="utf-8", errors="replace")
            m = pat.search(txt)
            if m:
                return m.group(1)
        time.sleep(0.5)
    return ""


def 等日志(pattern, timeout=60, 起点=0):
    """在后面端日志的 [起点:] 里等某条正则出现，返回匹配到的整行文本（"" = 超时）。

    为什么把日志当证据：阶段六十七的取消发生在 worker 线程里，而客户端这时候**已经断开**——
    它恰恰是问不到的那一方，SSE 上也再不会有帧回来。所以「取消真的发生了吗」只能靠服务端
    自己的记录来判。起点用来只认本次操作之后新写的行，避免把上一组用例留下的行当成自己的证据。
    """
    pat = re.compile(pattern)
    截止 = time.time() + timeout
    while True:
        if BACKEND_LOG.exists():
            try:
                尾部 = BACKEND_LOG.read_text(encoding="utf-8", errors="replace")[起点:]
            except Exception:  # noqa: BLE001
                尾部 = ""
            m = pat.search(尾部)
            if m:
                return m.group(0)
        if time.time() >= 截止:
            return ""
        time.sleep(1)


def 日志游标():
    """当前后端日志长度（按字符），配合 等日志(起点=…) 只看新写入的部分。"""
    if not BACKEND_LOG.exists():
        return 0
    try:
        return len(BACKEND_LOG.read_text(encoding="utf-8", errors="replace"))
    except Exception:  # noqa: BLE001
        return 0


def 端口空闲(port):
    s = socket.socket()
    s.settimeout(0.4)
    busy = s.connect_ex(("127.0.0.1", port)) == 0
    s.close()
    return not busy


def http_带头(method, path, token=None, timeout=60):
    """带上响应头返回 (status, headers, text)——测 Content-Disposition 这类只能看头的东西。

    头的键统一转小写：HTTP 头名大小写不敏感，服务端（Starlette/uvicorn）实际下发的是
    小写 `content-disposition`；早先按 `dict(...).get("Content-Disposition")` 取，永远
    取到空串，误判成「阶段六十一修的 RFC5987 bug 没生效」。
    """
    url = BASE + path
    h = {"Accept": "*/*"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, {}, f"{type(e).__name__}: {e}"


def 清理残留(用户名):
    """兜底清理：脚本中途崩了也把本轮测试账号连同其数据删掉。

    走的是后端自己的 `user_repo.删除用户及数据(user_id)`（级联覆盖 datasets/reports/
    share_links/favorites/…），而不是自己拼一串 DELETE —— 拼 DELETE 必然漏表，
    还会踩外键顺序问题。要点：DB_BACKEND 必须在 import repositories **之前** 置成 mysql，
    否则父进程（.env 里是 sqlite）会连错库，删了个寂寞。返回被删的用户名或空串。
    """
    if not 用户名:
        return ""
    os.environ["DB_BACKEND"] = "mysql"
    conn = mysql_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE username = %s", (用户名,))
        行 = cur.fetchall()
    conn.close()
    if not 行:
        return ""
    from repositories import user_repo
    for (uid,) in 行:
        user_repo.删除用户及数据(uid)
    return 用户名


def mysql_conn():
    """连真 MySQL。

    `autocommit=True` 是**必须的**：InnoDB 默认 REPEATABLE READ，连接不自动提交时第一句
    SELECT 就把事务快照定死了，后面别人（HTTP 删号 / 后端进程）提交的行，本连接再也看不见——
    早先清理脚本就因为这个把「已删干净」误报成「还剩 2 行」。
    """
    from config import settings
    import pymysql
    c = settings.EnvConfig
    return pymysql.connect(
        host=c.MYSQL_HOST, port=int(c.MYSQL_PORT), user=c.MYSQL_USER,
        password=c.MYSQL_PASSWORD, database=c.MYSQL_DATABASE,
        charset="utf8mb4", connect_timeout=5, autocommit=True,
    )


# --------------------------------------------------------------------------- 测试数据
CSV_正常 = """地区,月份,产品线,销售额,订单量
华东,2026-01,基础版,120000,320
华东,2026-02,基础版,135000,351
华南,2026-01,专业版,210000,180
华南,2026-02,专业版,198500,171
华北,2026-01,基础版,98000,260
华北,2026-02,旗舰版,312000,95
华中,2026-01,专业版,76000,132
华中,2026-02,基础版,143200,377
西南,2026-01,旗舰版,265000,88
西南,2026-02,旗舰版,271400,90
"""

# 脏数据：空值 / 负数 / 千分位字符串 / 多种日期写法 / 超长文本 / 全角字符 / 重复行 / BOM 风险
CSV_脏 = """编号,下单日期,金额,客户,备注,渠道
D-001,2026/01/05,"1,234.56",张三,"正常",线上
D-002,2026-02-29,"2,000",李四,"金额带千分位",线下
D-003,2026年3月1日,-500,王五,"负数退款",线上
D-004,,,赵六,"金额与日期全空",线上
D-005,2026-03-10,880.5,"张三","重复客户",线上
D-006,2026-03-10,880.5,"张三","重复客户",线上
D-007,2026/03/12,"１２３",钱七,"全角数字",线下
D-008,2026-03-15,,"这条备注特别长""" + "很长" * 120 + """"",线上
"""


def 造大CSV(行数=100000):
    """10 万行 / 6 列，约 6MB。"""
    buf = io.StringIO()
    buf.write("id,日期,地区,产品线,销售额,订单量\n")
    地区 = ["华东", "华南", "华北", "华中", "西南", "东北"]
    产品 = ["基础版", "专业版", "旗舰版"]
    for i in range(行数):
        buf.write(f"{i},2026-{(i % 12) + 1:02d}-{i % 28 + 1:02d},{地区[i % 6]},{产品[i % 3]},{i * 7 % 99999},{i % 97}\n")
    return buf.getvalue().encode("utf-8")


def 造宽CSV(列数=200, 行数=50):
    buf = io.StringIO()
    buf.write(",".join(f"字段{i}列" for i in range(列数)) + "\n")
    for r in range(行数):
        buf.write(",".join(str(r * 100 + c) for c in range(列数)) + "\n")
    return buf.getvalue().encode("utf-8")


# --------------------------------------------------------------------------- 报告
def 出报告():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md = REPORT_DIR / f"{RUN_ID}-报告.md"
    js = REPORT_DIR / f"{RUN_ID}-报告.json"
    总数 = len(CASES)
    通过 = sum(1 for c in CASES if c["通过"])
    分组: dict[str, list[dict]] = {}
    for c in CASES:
        分组.setdefault(c["组"], []).append(c)
    行 = [
        f"# 目标⑥ 真实用户全流程实测报告（{RUN_ID}）",
        "",
        f"- 汇总：**{通过}/{总数} 通过**，{总数 - 通过} 失败",
        f"- 失败项：{FAIL if FAIL else '无'}",
        f"- 截图目录：`scripts/.e2e_real/{RUN_ID}/`",
        "- 后端日志：`.superpowers/e2e报告/backend.log`",
        "",
    ]
    for 组, 项s in 分组.items():
        行.append(f"## {组}")
        行.append("")
        行.append("| 结果 | 用例 | 耗时(s) | 细节 |")
        行.append("|---|---|---|---|")
        for c in 项s:
            细节 = c["细节"].replace("|", "/").replace("\n", " ")
            行.append(f"| {'✅' if c['通过'] else '❌'} | {c['名称']} | {c['耗时秒']} | {细节} |")
        行.append("")
    if NOTES:
        行.append("## 备注")
        行.append("")
        for n in NOTES:
            行.append(f"- {n}")
        行.append("")
    md.write_text("\n".join(行), encoding="utf-8")
    js.write_text(json.dumps({
        "run_id": RUN_ID, "通过": 通过, "总数": 总数,
        "失败": FAIL, "用例": CASES, "备注": NOTES,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return md, js


# --------------------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="目标⑥ 真实用户全流程端到端实测（真实 MySQL + 正式前端）")
    ap.add_argument("--keep", action="store_true", help="保留本轮测试账号（默认结束时删除）")
    ap.add_argument("--keep-chroma", action="store_true", help="沿用真实 data/chroma_db 而不另起临时记忆库")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    用户名 = f"e2e_{RUN_ID.replace('-', '')}"
    邮箱 = f"{用户名}@e2e.test"
    密码 = "E2e@2026Pass"

    print(f"== 阶段六十二 · 目标⑥ 真实用户全流程实测（run={RUN_ID}）==")
    print(f"   账号：{用户名} / {邮箱}")
    print(f"   目标：{BASE}（真实 MySQL + frontend/dist + AUTH_ENABLED=true）")
    print(f"   截图：{SHOT_DIR}")

    if not 端口空闲(PORT):
        print(f"端口 {PORT} 被占用，先关掉占用进程再跑（本机 8000 是你自己的实例，本脚本刻意不用）")
        sys.exit(2)

    proc, logfh = 起后端(keep_chroma=args.keep_chroma)
    token = ""
    try:
        # ---------------- P0 前置
        print("\n== P0 前置自检 ==")
        t0 = time.time()
        health = wait_health()
        check("后端在真实 MySQL 上启动成功", health is not None, group="P0 前置")
        if health is None:
            txt = BACKEND_LOG.read_text(encoding="utf-8", errors="replace")
            print("\n".join(txt.splitlines()[-40:]))
            sys.exit(1)
        check("后端确认 db_backend=mysql", health.get("db_backend") == "mysql", health.get("db_backend"), group="P0 前置")
        check("后端确认 db_ok=true", health.get("db_ok") is True, group="P0 前置")
        mem = health.get("memory") or {}
        check("healthz 暴露记忆块且不拖累总状态",
              health.get("status") == "ok" and "memory" in health,
              f"memory.ok={mem.get('ok')} 模型={mem.get('模型')}", group="P0 前置", cost=time.time() - t0)
        # 这条不记成 check（失败项），因为它不是「功能坏了」，而是「当前 .env 的配置
        # 组合注定调不通」——配置错时 embedding 请求 400 且被 llm_client 静默吞掉，
        # 于是 memory.ok 仍然是 true，属于**假绿灯**。记成备注是为了不把配置问题
        # 混进功能通过率里，但必须用 ⚠ 顶在最前面，不能埋在报告角落。
        # 阶段六十五：这里原来写死的是 F1 的结论（「向量记忆当前根本没在工作」）。
        # 把 .env 配成同源之后那句话就变成假话了，所以改成按 /healthz 实际字段分支。
        check("healthz.memory 暴露「嵌入配置同源」字段（阶段六十三 新增契约）",
              "嵌入配置同源" in mem, f"memory 字段={sorted(mem)}", group="P0 前置")
        同源 = mem.get("嵌入配置同源")
        if 同源 is True:
            note(f"✅ /healthz.memory 嵌入配置同源：模型=`{mem.get('模型')}` 端点=`{mem.get('端点')}` "
                 f"条数=`{mem.get('条数')}` 指纹一致=`{mem.get('指纹一致')}` 说明=`{mem.get('嵌入配置说明')}`；"
                 f"真实写入是否发生见 P13「向量记忆端到端」。")
        else:
            note(f"⚠ /healthz.memory 嵌入配置同源=`{同源}`，模型名=`{mem.get('模型')}`，端点=`{mem.get('端点')}`，"
                 f"说明=`{mem.get('嵌入配置说明')}`：不同源时 embed_text() 拿到 400 后返回 None，"
                 f"memory.ok 仍然是 true —— 向量记忆实际一次都没写进去。"
                 f"修法：三项 LLM_EMBEDDING_* 配成同源（智谱端点用 LLM_EMBEDDING_MODEL=embedding-3），"
                 f"配好后用 `python scripts/自检记忆库.py` 一次性验通；详见 docs/工程文档/LLM接入说明.md。")
        check("前端正式产物 dist 存在且已构建", (ROOT / "frontend" / "dist" / "index.html").exists(),
              group="P0 前置")
        check("Chromium 已安装", bool(os.environ.get("PLAYWRIGHT_BROWSERS_PATH")) or
              os.path.isdir(os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")),
              group="P0 前置")

        # ---------------- P1 未登录被守卫拦下
        print("\n== P1 未登录访问受保护页 ==")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            # 无头 Chromium 里若 window.showSaveFilePicker 存在，导出会走系统「另存为」对话框，
            # Playwright 就永远收不到 download 事件（测试假失败）。这里删掉它，让
            # Report.jsx:202 的 saveWithPicker 走 a[download] 回退分支——只改测试环境，
            # 不碰产品代码；页面上仍然是「点导出 → 选格式 → 确认下载」的真实交互。
            ctx.add_init_script("delete window.showSaveFilePicker;")
            抓到 = {}

            def _记录头(req):
                # Playwright 的 req.headers 键一律小写，所以要按小写取；
                # 早先写成 req.headers.get("Authorization") 拿到空串，token 永远是空的。
                h = {k.lower(): v for k, v in req.headers.items()}
                if h.get("authorization"):
                    抓到["token"] = h["authorization"].replace("Bearer ", "").strip()

            page.on("request", _记录头)

            # 记录页面上弹出的任何对话框（alert/confirm/prompt）。
            # 用途：XSS 校验不能只看「后端原样存下了 <script>」，真正要证的是
            # **浏览器没有执行它**——执行了必然会弹 alert。不注册 handler 的话
            # Playwright 会自动 dismiss 掉，证据就没了。
            弹窗记录 = []

            def _记弹窗(dlg):
                弹窗记录.append(dlg.type + ":" + (dlg.message or "")[:60])
                try:
                    dlg.dismiss()
                except Exception:  # noqa: BLE001
                    pass

            page.on("dialog", _记弹窗)

            page.goto(BASE + "/data", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector("text=去注册", timeout=15000)
                check("未登录访问 /data 被路由守卫弹到登录页", True)
            except Exception as e:  # noqa: BLE001
                check("未登录访问 /data 被路由守卫弹到登录页", False, type(e).__name__)
            page.screenshot(path=str(SHOT_DIR / "01-未登录被拦.png"))

            # ---------------- P2 注册（验证码从后端日志抓）
            print("\n== P2 邮箱验证码注册 ==")
            page.click("button:has-text('去注册')")
            page.wait_for_selector("input[type=email]", timeout=10000)
            page.fill("input[placeholder='输入用户名']", 用户名)
            page.fill("input[type=email]", 邮箱)
            page.click("button:has-text('获取验证码')")
            code = 抓验证码(邮箱)
            check("后端 dry-run 日志里拿到邮箱验证码", bool(code), f"code={'已拿到' if code else '超时未出现'}", group="P2 注册")
            page.fill("input[placeholder='6 位验证码']", code)
            page.fill("input[type=password]", 密码)
            page.screenshot(path=str(SHOT_DIR / "02-注册填表.png"))
            t0 = time.time()
            page.click("button:has-text('注册')")
            try:
                page.wait_for_url("**/data", timeout=25000)
                check("注册成功并自动登录落 /data", True, group="P2 注册", cost=time.time() - t0)
            except Exception as e:  # noqa: BLE001
                err = page.locator("text=/失败|错误|已存在|不正确/").first.inner_text() if page.locator("text=/失败|错误|已存在/").count() else ""
                check("注册成功并自动登录落 /data", False, f"{type(e).__name__} {err[:80]}", group="P2 注册")
            page.screenshot(path=str(SHOT_DIR / "03-注册后首页.png"))

            # ---------------- P3 上传脏数据 CSV
            print("\n== P3 上传数据集（中文表头 + 脏数据）==")
            csv_path = SHOT_DIR / "真实用户脏数据.csv"
            csv_path.write_text(CSV_脏, encoding="utf-8")
            t0 = time.time()
            page.set_input_files("#file-input", str(csv_path))
            try:
                page.wait_for_selector("text=真实用户脏数据.csv", timeout=60000)
                check("脏数据 CSV 上传并出现在数据集列表", True, group="P3 上传", cost=time.time() - t0)
            except Exception:  # noqa: BLE001
                check("脏数据 CSV 上传并出现在数据集列表", False, "60s 内没等到文件名", group="P3 上传", cost=time.time() - t0)
            page.screenshot(path=str(SHOT_DIR / "04-上传后.png"), full_page=True)
            # 顺带上传一份干净的（分析用干净数据更稳）
            净 = SHOT_DIR / "真实用户销售数据.csv"
            净.write_text(CSV_正常, encoding="utf-8")
            page.set_input_files("#file-input", str(净))
            try:
                page.wait_for_selector("text=真实用户销售数据.csv", timeout=60000)
                check("干净 CSV 上传成功", True, group="P3 上传")
            except Exception:  # noqa: BLE001
                check("干净 CSV 上传成功", False, "60s 超时", group="P3 上传")

            # ---------------- P4 登录（显式走一次登录页，验证真实登录路径）
            print("\n== P4 登出后重新登录 ==")
            page.goto(BASE + "/account", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            if page.locator("text=退出登录").count():
                page.click("text=退出登录")
                page.wait_for_timeout(2000)

            def 关引导():
                """新用户首次登录会被 Onboarding 全屏遮罩挡住所有点击（z-[70]），
                不关掉的话 P5 点「开始分析」会被遮罩拦截并 30s 超时。"""
                try:
                    if page.locator("button[title='跳过引导']").count():
                        page.click("button[title='跳过引导']")
                        page.wait_for_timeout(600)
                        return True
                except Exception:  # noqa: BLE001
                    pass
                return False

            关引导()
            page.goto(BASE + "/login", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_selector("input[type=password]", timeout=15000)
            page.fill("input[placeholder='输入用户名或邮箱']", 用户名)
            page.fill("input[type=password]", 密码)
            t0 = time.time()
            page.click("button:has-text('登录')")
            try:
                page.wait_for_url("**/data", timeout=25000)
                check("用户名+密码登录成功", True, group="P4 登录", cost=time.time() - t0)
            except Exception as e:  # noqa: BLE001
                check("用户名+密码登录成功", False, type(e).__name__, group="P4 登录")
            page.wait_for_timeout(1000)
            check("新用户首次登录的引导遮罩可一键关掉", 关引导() or page.locator("button[title='跳过引导']").count() == 0,
                  group="P4 登录")
            page.screenshot(path=str(SHOT_DIR / "05-登录后.png"))

            token = 抓到.get("token", "")
            check("已从请求头抓到 JWT（供后续 API 级极限测试用）", bool(token),
                  f"len={len(token)}", group="P4 登录")

            # ---------------- P5 智能分析（真实 LLM）
            print("\n== P5 智能分析（真实 LLM 调用）==")
            page.goto(BASE + "/analysis", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
            # 阶段 63：把「真的走 LLM」变成可断言的事实，而不是靠耗时猜。
            # orchestrator.py:261-284 有个规则快速通道（阶段 35/39 的省 3-4s 优化），
            # 命中它的话意图来源是「规则-受控语句 / 规则-快速路由」，一样几秒就出报表，
            # 但**LLM 一次都没被调用**——只测「出没出报表」会把这个洞盖过去。
            #
            # 为什么不拦响应体：前端走的是 SSE（upload.js:102 `POST /reports/generate-stream`），
            # run9 试过 page.on("response") 直接取 text()，取到的是一条永不结束的流，
            # 结果 意图来源='' 恒失败。改成从 HTTP 侧读回刚生成的报表：
            # GET /reports/ 列表（report_repo.py:137 按 created_at 倒序）→ GET /reports/{id}
            # → report_json 里的 意图来源 / LLM失败原因（写入点 report_generator.py:205-217）。
            #
            # 需求文本选「按地区统计销售额」：实测这一句会绕过规则快速通道真调 LLM
            # （探针 .superpowers/_probe_llm_path.py：耗时 10.94s、意图来源='LLM'、图表类型='柱状图'），
            # 而「帮我看看销售额的构成情况」会命中规则通道（0.00s / '规则-受控语句'）。
            page.fill("textarea", "按地区统计销售额")
            关引导()
            t0 = time.time()
            点(page, "button:has-text('开始分析')")
            # 阶段六十八：生成成功会**自动跳到报表页**，所以「分析完成」的页面信号已经不是
            # 追问条，而是报表页本身（Report.jsx 的「报表查看」标题）。这里先钉跳转，
            # 下一段再钉追问条还能不能回来。
            跳到报表 = False
            try:
                page.wait_for_selector("text=报表查看", timeout=180000)
                跳到报表 = True
            except Exception:  # noqa: BLE001
                pass
            分析用时 = time.time() - t0
            body = page.inner_text("body")[:300]
            check("分析完成（阶段六十八：自动跳到报表页）", 跳到报表,
                  f"{分析用时:.1f}s 跳到报表={跳到报表}；页面文本={body!r}",
                  group="P5 分析", cost=分析用时)
            page.screenshot(path=str(SHOT_DIR / "06-分析完成.png"), full_page=True)

            # 阶段六十九回归（真机 E2E 抓到的那一个）：自动跳转把分析页卸载了，
            # liveDone 随之丢失，追问条（查看报表 / 存为模板 / 推荐追问，阶段 52/53 的入口）
            # 在主导流程里再也没机会出现——旧断言在这里等 180s 也是白等。
            # 修复是报表页「继续分析」把上一份报表用 router state 带回来。
            追问条 = False
            回跳说明 = ""
            try:
                if not page.locator("button:has-text('继续分析')").count():
                    回跳说明 = "报表页没找到『继续分析』按钮"
                else:
                    点(page, "button:has-text('继续分析')")
                    page.wait_for_selector("text=继续追问", timeout=20000)
                    追问条 = True
            except Exception as e:  # noqa: BLE001
                回跳说明 = f"{type(e).__name__}"
            if not 追问条:
                note(f"回跳后未见追问条：{回跳说明}；页面文本={page.inner_text('body')[:200]!r}")
            check("报表页『继续分析』回跳后追问条重新出现（阶段六十九回归）", 追问条,
                  f"回跳说明={回跳说明 or '点到了'}", group="P5 分析")

            意图来源 = ""
            失败原因 = ""
            步骤数 = 0
            P5报表ID = ""
            抓取说明 = ""
            st5, body5 = http("GET", "/reports/", token=token)
            if st5 == 200:
                try:
                    报表列表 = json.loads(body5).get("报表列表") or []
                except Exception as e:  # noqa: BLE001
                    报表列表 = []
                    抓取说明 = f"列表解析失败 {type(e).__name__}"
                # 按标题挑本轮那条；挑不到就退回列表第一条（列表按创建时间倒序）
                本轮 = next((r for r in 报表列表 if str(r.get("标题", "")).startswith("按地区统计销售额")), None)
                本轮 = 本轮 or (报表列表[0] if 报表列表 else None)
                if 本轮:
                    P5报表ID = 本轮.get("报表ID", "")
                    st6, body6 = http("GET", f"/reports/{P5报表ID}", token=token)
                    if st6 == 200:
                        明细 = json.loads(body6).get("报表") or {}
                        意图来源 = str(明细.get("意图来源", ""))
                        失败原因 = str(明细.get("LLM失败原因", "") or "")
                        步骤数 = len(明细.get("Agent Trace", []) or [])
                    else:
                        抓取说明 = f"详情 {st6}"
                else:
                    抓取说明 = "报表列表为空"
            else:
                抓取说明 = f"列表 {st5}"
            check("本轮需求绕过规则快速通道、真的调用了 LLM",
                  意图来源 == "LLM",
                  f"意图来源={意图来源!r} LLM失败原因={失败原因!r} 报表ID={P5报表ID or '未取到'} "
                  f"Agent步骤={步骤数} {抓取说明}",
                  group="P5 分析")

            # ---------------- P6 报表页 + 导出
            print("\n== P6 报表查看与导出 ==")
            if page.locator("button:has-text('查看报表')").count():
                点(page, "button:has-text('查看报表')")
            try:
                page.wait_for_selector("text=报表查看", timeout=30000)
                check("报表页打开", True, group="P6 报表")
            except Exception as e:  # noqa: BLE001
                check("报表页打开", False, type(e).__name__, group="P6 报表")
            page.wait_for_timeout(3000)  # echarts 懒渲染
            有图 = page.locator("canvas").count()
            check("报表图表已渲染出 canvas", 有图 > 0, f"canvas×{有图}", group="P6 报表")
            page.screenshot(path=str(SHOT_DIR / "07-报表.png"), full_page=True)
            # 阶段 53 起导出被统一收进「导出」弹窗（Report.jsx:673 → ExportDialog），
            # 页面顶层不再有 Excel/CSV/PDF 按钮；重跑入口的文案是「用最新数据重跑」。
            for label in ("分享", "导出", "用最新数据重跑"):
                check(f"报表页按钮「{label}」存在",
                      page.locator(f"button:has-text('{label}')").count() > 0, group="P6 报表")
            # 用 :text-is 精确定位「导出」：页面上还有「导出全部」（Report.jsx:530），
            # has-text 是子串匹配会把两个都选上。
            if page.locator("button:text-is('导出')").count():
                t0 = time.time()
                try:
                    # 「确认下载」只存在于 ExportDialog（ExportDialog.jsx:73），是弹窗是否打开的
                    # 最准哨兵；用「导出报表」标题做哨兵时，只要标题文字渲染方式一变就误判超时。
                    点(page, "button:text-is('导出')")
                    首击后 = []
                    try:
                        page.wait_for_selector("text=确认下载", timeout=8000)
                        首击后.append("首击即开")
                    except Exception:  # noqa: BLE001
                        # 兜底再点一次：首击点得到（Playwright 不报错）但弹窗没出现，
                        # 像是点击落在了首帧的旧 DOM 上、React 没收到这次事件。
                        # 这里把「首击后弹窗是否曾经出现」采样出来，免得只能看到最终状态。
                        首击后.append("首击未开")
                        点(page, "button:text-is('导出')")
                        page.wait_for_selector("text=确认下载", timeout=15000)
                        首击后.append("再击已开")
                    可见格式 = [名 for 名 in ("Excel 表格", "CSV 数据", "PDF 报告", "图表图片")
                              if page.locator(f"button:has-text('{名}')").count()]
                    check("导出弹窗列出可选格式", len(可见格式) >= 3,
                          f"可见={可见格式} {'/'.join(首击后)}", group="P6 报表")
                    点(page, "button:has-text('Excel 表格')")
                    with page.expect_download(timeout=60000) as 下载信息:
                        点(page, "button:has-text('确认下载')")
                    d = 下载信息.value
                    名 = d.suggested_filename
                    # 注意：Playwright Python 里 download.path() 是**方法**，JS 里才是属性；
                    # 写成 os.path.exists(d.path) 会拿方法对象去问路径 → TypeError。
                    路径 = d.path()
                    字节 = os.path.getsize(路径) if 路径 and os.path.exists(路径) else -1
                    check("「导出」弹窗里能下出 xlsx 且文件名非空", bool(名) and 字节 > 0,
                          f"{名}（{字节} 字节）{'/'.join(首击后)}", group="P6 报表", cost=time.time() - t0)
                except Exception as e:  # noqa: BLE001
                    # 失败时把页面上真实存在的按钮文案打出来，下一轮不用猜就能定位卡在哪一步
                    按钮 = page.eval_on_selector_all(
                        "button", "els => els.map(e => (e.innerText||'').trim()).filter(Boolean).slice(0, 30)")
                    check("「导出」弹窗里能下出 xlsx 且文件名非空", False,
                          f"{type(e).__name__}（{time.time() - t0:.1f}s）弹窗已开="
                          f"{page.locator('text=确认下载').count() > 0} 页面按钮={按钮}",
                          group="P6 报表")

            # ---------------- P6b XSS 标题在浏览器里到底被当文本还是当 HTML
            print("\n== P6b XSS 标题的真实渲染路径 ==")
            # 后端把 <script> 原样存进标题是**对的**（用户数据不该被后端悄悄改写），
            # 风险全在前端怎么把它放进 DOM。这里用真实报表页验四件事：
            # ①报表页确实渲染出来了（正向对照，防止「啥都没渲染所以看着安全」）
            # ②没有 alert() 弹窗（脚本没被执行）③页面里没有注入出来的 <script> 节点
            # ④标题以**纯文本**出现在可见文本里——注意 Report.jsx:388 的 <h1> 是写死的
            #   「报表查看」，报表标题只在「对比」面板（Report.jsx:460-472）里作为文本渲染，
            #   所以要先把面板点开才看得到标题，否则会误判成「标题没渲染 = 不安全」。
            XSS报表ID = ""
            XSS生成 = {}
            st, body = http("GET", "/datasets/?limit=1", token=token)
            if st == 200:
                try:
                    数据集列表 = json.loads(body).get("数据集列表") or []
                    XSS数据集ID = (数据集列表[0].get("数据集ID", "") if 数据集列表 else "")
                except Exception:  # noqa: BLE001
                    XSS数据集ID = ""
                if XSS数据集ID:
                    st, body = http("POST", "/reports/generate",
                                    {"数据集ID": XSS数据集ID,
                                     "分析需求": "<script>alert('xss')</script> 按地区统计销售额"},
                                    token=token, timeout=300)
                    if st == 200:
                        try:
                            XSS生成 = json.loads(body)
                            XSS报表ID = XSS生成.get("报表ID", "")
                        except Exception:  # noqa: BLE001
                            XSS报表ID = ""
            # 记下后端是「真调了 LLM」还是「降级到规则」——XSS 需求带尖括号，
            # LLM 大概率产不出可用意图而走降级（report_generator.py:206-217），
            # 这属于优雅降级不是漏洞，但得把「降级原因有没有透传」看进报告里。
            XSS意图来源 = str(XSS生成.get("意图来源", "") or "")
            XSS失败原因 = str(XSS生成.get("LLM失败原因", "") or "")
            弹窗数 = len(弹窗记录)
            if XSS报表ID:
                原URL = page.url
                page.goto(BASE + "/report/" + XSS报表ID, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(4000)
                见标题 = page.locator("h1:has-text('报表查看')").count() > 0
                # 「页面渲染成功」的判据不能绑死在 canvas 上：图表类型是表格时渲染 <table>，
                # 而 kpi/文本类图表两者都不是（早先就是这里误判的）。所以用
                # Report.jsx:669 那个**无条件渲染**的「导出」按钮当哨兵——它和标题在同一次
                # render 里，标题在 + 按钮在 = 这张报表确实被加载出来了。
                有导出按钮 = page.locator("button:text-is('导出')").count() > 0
                页面有效 = 见标题 and 有导出按钮
                有canvas = page.locator("canvas").count() > 0
                有表格 = page.locator("table").count() > 0
                try:
                    头部文案 = page.locator("h1:has-text('报表查看')").first.evaluate(
                        "el => el.parentElement.parentElement.innerText").replace("\n", " ")[:110]
                except Exception:  # noqa: BLE001
                    头部文案 = ""
                注入脚本数 = page.eval_on_selector_all(
                    "script",
                    "els => els.map(e => e.textContent || '').filter(t => t.includes(\"alert('xss')\")).length")
                # 打开「对比」面板，让报表标题以文本形式真正进入 DOM（这是页面上唯一
                # 会渲染标题文本的地方）；然后再看那段文本在不在、有没有被执行。
                点(page, "button:text-is('对比')")
                page.wait_for_timeout(1200)
                面板文本 = page.evaluate("() => document.body.innerText")
                标题为纯文本 = "alert('xss')" in 面板文本
                check("XSS 串标题在真实报表页被当纯文本渲染（无脚本执行、无 alert）",
                      页面有效 and 注入脚本数 == 0 and len(弹窗记录) == 弹窗数 and 标题为纯文本,
                      f"页面已渲染={页面有效}(标题={见标题} 导出按钮={有导出按钮} canvas={有canvas} 表格={有表格}) "
                      f"头部={头部文案!r} 注入script={注入脚本数} 新弹窗={len(弹窗记录) - 弹窗数} "
                      f"标题当文本可见={标题为纯文本} 意图来源={XSS意图来源!r} LLM失败原因={XSS失败原因!r}",
                      group="P6b XSS")
                page.screenshot(path=str(SHOT_DIR / "07b-XSS标题渲染.png"), full_page=True)
                page.goto(原URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
            else:
                note("P6b 跳过：没能造出 XSS 标题的报表")

            # ---------------- P7 分享 + 匿名访问
            print("\n== P7 分享链接与匿名访问 ==")
            分享链接 = ""
            分享异常 = ""
            if page.locator("button:has-text('分享')").count():
                点(page, "button:has-text('分享')")
                try:
                    page.wait_for_selector("text=生成分享链接", timeout=10000)
                    点(page, "button:has-text('生成分享链接')")
                    page.wait_for_timeout(2500)
                    分享链接 = page.locator(".font-mono").first.inner_text(timeout=5000).strip()
                except Exception as e:  # noqa: BLE001
                    分享异常 = type(e).__name__
            check("分享链接生成", "/s/" in 分享链接,
                  (分享链接[:80] or 分享异常 or "分享按钮不存在"), group="P7 分享")
            page.screenshot(path=str(SHOT_DIR / "08-分享.png"))
            if "/s/" in 分享链接:
                匿名 = ctx.browser.new_context()  # 独立上下文 = 无 localStorage 无 token
                apage = 匿名.new_page()
                apage.goto(分享链接, wait_until="domcontentloaded", timeout=30000)
                try:
                    apage.wait_for_selector("text=分享的报表", timeout=20000)
                    check("匿名新标签页能看分享报表（无需登录）", True, group="P7 分享")
                except Exception:  # noqa: BLE001
                    check("匿名新标签页能看分享报表（无需登录）", False, group="P7 分享")
                apage.screenshot(path=str(SHOT_DIR / "09-匿名分享页.png"))
                匿名.close()

            # ---------------- P8 看板 + 关系视图（阶段六十）
            print("\n== P8 图表看板与关系视图 ==")
            page.goto(BASE + "/dashboard", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector("text=图表看板", timeout=20000)
                check("看板页打开", True, group="P8 看板")
            except Exception as e:  # noqa: BLE001
                check("看板页打开", False, type(e).__name__, group="P8 看板")
            page.wait_for_timeout(2000)
            page.screenshot(path=str(SHOT_DIR / "10-看板-网格.png"), full_page=True)
            # 新用户还没有任何看板 → Dashboard.jsx:315 的 {detail && (...)} 工具条整块不渲染，
            # 「关系视图」按钮也就不存在。所以先走一遍真实的新建看板流程（勾报表 → 创建），
            # 再验血缘视图——这才是新用户第一次用关系视图时的真实路径。
            if not page.locator("[title='关系视图']").count() and page.locator("button:has-text('新建看板')").count():
                点(page, "button:has-text('新建看板')")
                try:
                    # 等输入框而不是标题文字：标题「新建看板」和触发按钮同名，等文字会立刻命中
                    page.wait_for_selector("input[placeholder^='看板名称']", timeout=10000)
                    page.fill("input[placeholder^='看板名称']", "E2E 血缘看板")
                    勾 = page.locator("input[type='checkbox']")
                    if 勾.count():
                        勾.first.check()
                    点(page, "button:has-text('创建')")
                    page.wait_for_timeout(3000)
                    check("从零新建看板（含勾选报表）", page.locator("[title='关系视图']").count() > 0,
                          group="P8 看板")
                except Exception as e:  # noqa: BLE001
                    check("从零新建看板（含勾选报表）", False, type(e).__name__, group="P8 看板")
            if page.locator("[title='关系视图']").count():
                点(page, "[title='关系视图']")
                page.wait_for_timeout(4000)
                有血缘画布 = page.locator("canvas").count()
                空态 = page.locator("[data-testid='血缘图空态']").count()
                check("关系视图切出来后画布已渲染（或明确空态）", 有血缘画布 > 0 or 空态 > 0,
                      f"canvas×{有血缘画布} 空态×{空态}", group="P8 看板")
                page.screenshot(path=str(SHOT_DIR / "11-看板-关系视图.png"), full_page=True)
            else:
                check("关系视图切换按钮存在", False, "新无看板用户也拿不到 title='关系视图'", group="P8 看板")

            # ---------------- P9 账号页：导出我的数据（验阶段六十一修的 RFC5987 bug 在真浏览器里生效）
            print("\n== P9 账号页 + 导出我的数据 ==")
            page.goto(BASE + "/account", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            page.screenshot(path=str(SHOT_DIR / "12-账号页.png"), full_page=True)
            st, body = http("GET", "/auth/export", token=token)
            check("GET /auth/export 返回 200", st == 200, f"{st} {body[:80]}", group="P9 账号")
            if st == 200:
                状态, 头, 正文 = http_带头("GET", "/auth/export", token=token)
                cd = 头.get("content-disposition", "")
                # 阶段六十一修的就是这里：RFC 5987 的 filename* 必须真的出现，
                # 且百分号编码解回来是中文名，否则浏览器只会用 ASCII 兜底名 export.json。
                编码名 = ""
                m = re.search(r"filename\*=UTF-8''([^;]+)", cd)
                if m:
                    import urllib.parse
                    编码名 = urllib.parse.unquote(m.group(1))
                check("「导出我的数据」的响应头带 RFC 5987 中文文件名",
                      bool(m) and 编码名.endswith(".json") and any(ord(c) > 127 for c in 编码名),
                      f"Content-Disposition={cd[:150]!r} 解回={编码名!r}", group="P9 账号")
                try:
                    顶层键 = list(json.loads(正文).keys())
                except Exception:  # noqa: BLE001
                    顶层键 = []
                # 早先这里用 `'用户名' in 正文` 判断「字段名含中文」，但导出体里的字段是
                # `username`（英文键 + 个人资料/数据集 这类中文分组名），于是永远判成「否」，
                # 与同一条日志里肉眼可见的 `个人资料` 自相矛盾。直接列顶层键，让事实自己说话。
                note(f"/auth/export 响应体 {len(正文)} 字节，顶层键={顶层键[:6]}")
            st, body = http("GET", "/auth/export")
            check("未带 token 访问 /auth/export 被拒", st in (401, 403), f"{st}", group="P9 账号")

            # ---------------- P10 登出后受保护页被拒
            print("\n== P10 登出 ==")
            page.goto(BASE + "/account", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
            # 「退出登录」是 Sidebar.jsx:242 的 title 属性，可见文案只有「退出」两个字；
            # 账号页（Account.jsx）只有「注销账号」，没有退出按钮——按文案找必然找不到。
            if page.locator("[title='退出登录']").count():
                点(page, "[title='退出登录']")
                page.wait_for_timeout(2500)
                check("点侧边栏「退出登录」后回到登录页", page.locator("button:has-text('去注册')").count() > 0,
                      page.url, group="P10 登出")
            else:
                check("侧边栏有「退出登录」按钮", False, group="P10 登出")
            page.goto(BASE + "/dashboard", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            check("登出后再访问 /dashboard 被守卫弹回登录页",
                  "/login" in page.url or page.locator("button:has-text('去注册')").count() > 0,
                  page.url, group="P10 登出")
            page.screenshot(path=str(SHOT_DIR / "13-登出后.png"))

            browser.close()

        # ---------------- P11 极限测试（API 层为主）
        st, body = http("GET", "/datasets/", token=token)
        数据集ID = ""
        if st == 200:
            try:
                数据 = json.loads(body)
                # /datasets/ 的返回体键是「数据集列表」（api/routes/datasets.py:293），
                # 与 /reports/ 的「报表列表」一致，都不是 items。
                条目 = 数据.get("数据集列表") or 数据.get("items") or (数据 if isinstance(数据, list) else [])
                for it in 条目:
                    if "真实用户销售数据" in str(it.get("文件名", "")):
                        数据集ID = it.get("id") or it.get("数据集ID") or ""
                        break
                if not 数据集ID and 条目:
                    数据集ID = 条目[0].get("id") or 条目[0].get("数据集ID") or ""
            except Exception as e:  # noqa: BLE001
                note(f"取数据集 ID 失败：{type(e).__name__}")
        check("能取到本轮数据集 ID（供极限测试用）", bool(数据集ID), 数据集ID, group="P11 极限")

        st, body = http("GET", "/auth/me", token=token)
        我的ID = ""
        if st == 200:
            try:
                我的ID = json.loads(body).get("user_id") or json.loads(body).get("id") or ""
            except Exception:  # noqa: BLE001
                我的ID = ""
        跑极限测试(token, 用户名, 数据集ID)

        # ---------------- P13 向量记忆端到端（阶段六十五）
        # 放在 P11 之后、P12 删号之前：此时 token 仍然有效、数据集还在，
        # 而且 P12 的删号会把记忆一起级联清掉（user_repo.py:313 删除用户记忆），
        # 所以这是「本轮账号的记忆还在库里」的最后一个观察窗口。
        跑向量记忆(token, 数据集ID)

        # ---------------- P14 取消/中断令牌端到端（阶段六十七）
        # 与 P13 同一窗口：token 有效、数据集还在、P12 还没删号。
        跑取消令牌(token, 数据集ID)

        # ---------------- P12 收尾：删账号 + MySQL 残留核对
        print("\n== P12 清理与残留核对 ==")
        if args.keep:
            note(f"--keep 已指定，账号 {用户名} 保留在真库里，需要时手动删")
        else:
            st, body = http("POST", "/auth/delete-account", {"password": 密码}, token=token)
            check("POST /auth/delete-account 删号成功", st == 200, f"{st} {str(body)[:100]}", group="P12 清理")
        conn = mysql_conn()
        with conn.cursor() as cur:
            残留 = {}
            if 我的ID:
                for 表 in ("datasets", "reports", "share_links", "favorites", "scheduled_jobs"):
                    try:
                        cur.execute(f"SELECT COUNT(*) FROM {表} WHERE user_id = %s", (我的ID,))
                        残留[表] = cur.fetchone()[0]
                    except Exception as e:  # noqa: BLE001
                        残留[表] = f"查询失败 {type(e).__name__}"
            try:
                cur.execute("SELECT COUNT(*) FROM users WHERE username = %s", (用户名,))
                残留["users"] = cur.fetchone()[0]
            except Exception as e:  # noqa: BLE001
                残留["users"] = f"查询失败 {type(e).__name__}"
            check("真库里本轮测试数据已清干净",
                  all(v == 0 for v in 残留.values()),
                  残留, group="P12 清理")
            cur.execute("SELECT COUNT(*) FROM users")
            note(f"真库 users 总行数（清理后）= {cur.fetchone()[0]}")
            cur.execute("SELECT COUNT(*) FROM datasets")
            note(f"真库 datasets 总行数（清理后）= {cur.fetchone()[0]}")
        conn.close()

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        logfh.close()
        # 崩溃也要收尾：早先脚本在 P5 抛异常直接退出，测试账号和 2 个数据集就留在真库里了。
        # 这里用后端自己的级联删除（user_repo.删除用户及数据），不手写 DELETE 以免漏表/踩外键。
        if not args.keep:
            try:
                删 = 清理残留(用户名)
                if 删:
                    print(f"  [清理] 兜底删除了残留账号 {用户名}（{删}）")
            except Exception as e:  # noqa: BLE001
                print(f"  [清理] 兜底清理失败：{type(e).__name__}: {e}")

    md, js = 出报告()
    print()
    print(f"汇总：{len(PASSED)}/{len(CASES)} 通过")
    if FAIL:
        print(f"失败 {len(FAIL)} 项 -> {FAIL}")
    print(f"报告：{md}")
    print(f"截图：{SHOT_DIR}")
    sys.exit(1 if FAIL else 0)


# --------------------------------------------------------------------------- 向量记忆
def 跑向量记忆(token, 数据集ID):
    """P13 向量记忆端到端（阶段六十五）。

    为什么要有这一组：F1 修配置之后，「记忆真的能用」这件事一直只有
    `scripts/自检记忆库.py` 的**独立进程**证据——服务进程里到底有没有把向量写进 chroma、
    读的时候拿不拿得到 few-shot 提示，谁都没验过。这组用真实 HTTP 链路自证：

      1. `/healthz.memory.嵌入配置同源` 是**配置闸门**，不是功能判据。不同源 → 记 note
         直接跳过（配置问题不能混进功能通过率；同 F1 时期 P0 的处理口径）。
      2. `条数 >= 1`：P5 那次**在浏览器里点的**分析（需求「按地区统计销售额」，实测绕过
         规则快速通道真走 LLM）在服务进程里落了一条记忆——真实 embedding 调用 + 真实
         chroma 写入 + 真实 HTTP 栈，三段一起过才算数。
      3. `指纹一致`：写入用的是当前配置的指纹，没往旧语义空间里混。
      4. 复用同一需求再生成一张报表（`POST /reports/generate` 与前端 SSE 端点
         `POST /reports/generate-stream` 走同一个生成器）：这一轮 `检索相似记忆` 会命中
         刚才那条（few-shot 提示真的进了 system prompt），随后 `保存记忆` 再写一条 →
         条数自增。**读 + 写两段一起验**，且断言 `意图来源 == 'LLM'`，证明注入了记忆提示
         之后 LLM 路径没有被破坏（提示污染 system prompt 会让 JSON 提取失败并降级成规则）。

    已知边界（别当成通过）：语义召回（换一种问法还能捞到）由 `scripts/自检记忆库.py`
    第 5 步用完全不同的问句验证（实测 Top1 命中，得分 1.1256194114685059）；这里复用
    同一句需求，只能证明「按需求文本检索」这一段通，不能证明向量语义质量。
    """
    G = "P13 记忆"
    print("\n== P13 向量记忆端到端 ==")
    if not token:
        check("P13 前提：有可用 JWT", False, "P4 没抓到 token，整组跳过", group=G)
        return

    st, body = http("GET", "/healthz", timeout=30)
    mem: dict = {}
    if st == 200:
        try:
            mem = json.loads(body).get("memory") or {}
        except Exception as e:  # noqa: BLE001
            note(f"P13 /healthz 解析失败：{type(e).__name__}")
    同源 = mem.get("嵌入配置同源")
    check("P13 healthz.memory 报告了嵌入配置是否同源", 同源 in (True, False, "未知"),
          f"嵌入配置同源={同源!r} 说明={mem.get('嵌入配置说明')!r} "
          f"模型={mem.get('模型')!r} 端点={mem.get('端点')!r}", group=G)
    if 同源 is not True:
        # 不算失败：embedding 调不通时记忆本来就不该写入，这是**配置**问题。
        # 但必须显式说出来，否则报告里「P13 一条没跑」会被读成「记忆验过了」。
        note(f"P13 自增验证跳过：嵌入配置同源={同源!r}（说明={mem.get('嵌入配置说明')!r}）——"
             f"不同源时写入注定不发生。修法见 P0 的 ⚠ 备注与 docs/工程文档/LLM接入说明.md；"
             f"配好后重跑本脚本即可验到条数自增。")
        return

    基线 = int(mem.get("条数") or 0)
    check("P5 浏览器分析在服务进程里真的落了一条长期记忆", 基线 >= 1,
          f"条数={基线} 库={mem.get('库')!r} 模型={mem.get('模型')!r}", group=G)
    check("记忆库指纹与当前 embedding 配置一致（没混语义空间）", mem.get("指纹一致") is True,
          f"指纹一致={mem.get('指纹一致')!r} 原因={mem.get('原因')!r}", group=G)

    if not 数据集ID:
        note("P13 自增验证跳过：没有数据集 ID")
        return

    # 与 P5 同一句需求：既验证「检索命中刚写的那条 few-shot」，也验证记忆提示不会
    # 把 LLM 路径带崩（意图来源必须仍是 LLM 而不是被污染成降级规则）。
    需求 = "按地区统计销售额"
    t0 = time.time()
    st, body = http("POST", "/reports/generate",
                    {"数据集ID": 数据集ID, "分析需求": 需求}, token=token, timeout=300)
    意图来源 = ""
    if st == 200:
        try:
            意图来源 = str(json.loads(body).get("意图来源", ""))
        except Exception:  # noqa: BLE001
            意图来源 = ""
    check("带 few-shot 记忆提示再走一次 LLM 路径仍成功且未被带偏",
          st == 200 and 意图来源 == "LLM",
          f"{st} 意图来源={意图来源!r} {str(body)[:140]}", group=G, cost=time.time() - t0)

    st, body = http("GET", "/healthz", timeout=30)
    后: dict = {}
    if st == 200:
        try:
            后 = json.loads(body).get("memory") or {}
        except Exception:  # noqa: BLE001
            后 = {}
    后条数 = int(后.get("条数") or 0)
    check("记忆条数自增（检索+保存的读与写两段都跑通）", 后条数 > 基线,
          f"{基线} → {后条数}", group=G)


# --------------------------------------------------------------------------- 取消令牌
def 跑取消令牌(token, 数据集ID):
    """P14 取消/中断令牌端到端（阶段六十七）。

    为什么要有这一组：`tests/backend/test_阶段67_取消令牌.py` 证明了「令牌一旦置位就不再
    发起新的 LLM 调用」，但那是**直接把 threading.Event 塞进函数**——真正可疑的一环恰好
    被跳过：真机上是谁、在什么时机把令牌置位的？答案是 Starlette 在客户端断连时 aclose()
    掉 SSE 生成器 → `event_stream()` 的 finally → `cancel.set()`。这条链路只有真机能验：

      1. 用真实 HTTP 长连接 POST `/reports/generate-stream`（前端的 SSE 端点），
         读到第一帧就**立刻关闭 socket**——等价于用户看到直播面板后直接关掉标签页。
         （必须自己 urlopen：脚本里的 `http()` 是 urllib 一次性读全的薄封装，读不了流。）
      2. **主证据是后端日志里的「第 N 轮后收到取消信号，跳过后续 LLM 调用」**。
         阶段六十九真机探针（`scripts/probe_sse_断连传导.py`）证明：`event_stream` 是同步
         生成器时断连**根本传导不进去**，要等 worker 自己跑完推哨兵（实测 8.5s vs 4.5s）；
         改成 async generator 后断连当刻就 aclose() 到生成器 → `finally: cancel.set()`。
         而「取消发生了」这件事只有日志看得见：客户端这时候已经断开，SSE 上再没有帧回来。
      3. 断开后服务端应该：置位令牌 → 后续轮次不再发 LLM 请求 → **但报表照常算完落库**。
         所以这里轮询报表列表等它出现：取消的是「继续推理」，不是「这次分析」。
      4. 那一份报表会落到规则降级版（`意图来源` 以「规则」开头），trace 里写明断开原因、
         状态记为「需关注」——「需关注」而不是「失败」是刻意的：用户自己关的页面不是系统错。
         注意「意图来源=规则」**单独不构成取消证据**：含糊需求本来也会落到规则降级，
         它只作辅助断言。

    已知边界（别当成通过）：这一组只证明**断开真的传到了应用层**并改变了后续轮次的行为；
    它不测「已飞出去的那一个 LLM 请求」是否被中断（HTTP 请求没有取消语义，阶段六十七
    的设计本就不拦它，收益在后续轮次）。也不测并发：同一进程里另一个用户的 SSE 不受影响
    这件事由 per-request 令牌的设计保证，真机并发验证未做。
    """
    G = "P14 取消"
    print("\n== P14 取消/中断令牌端到端 ==")
    if not token or not 数据集ID:
        check("P14 前提：有可用 JWT 和数据集 ID", False, "缺 token 或数据集，整组跳过", group=G)
        return

    # 断开前先给「已有报表」拍全量快照：断开后靠**差集**定位本次新报表。
    # 这一版是踩过坑改的：旧写法取「列表中第一个 ≠ 断前最新的 ID」，而 worker 还没落库时
    # 列表是 [断前最新, 更旧的一份, …]，于是它抓到的是**上一轮 E2E 用例留下的旧报表**
    # （run=1018-122322 实测抓到 P13 之前就存好的 58b572f6…），trace 里当然没有取消记录
    # ——「落库」「规则降级」「trace 需关注」三条一起变成假绿。
    st, body = http("GET", "/reports/?limit=50", token=token)
    断前最新 = ""
    断前集合: set = set()
    if st == 200:
        try:
            列表 = json.loads(body).get("报表列表") or []
            断前最新 = 列表[0].get("报表ID", "") if 列表 else ""
            断前集合 = {x.get("报表ID") for x in 列表 if x.get("报表ID")}
        except Exception as e:  # noqa: BLE001
            note(f"P14 断开前报表列表解析失败：{type(e).__name__}")
    note(f"P14 断开前快照：最新={断前最新!r} 已知报表={len(断前集合)} 份")

    需求 = "帮我分析一下销售情况"  # 实测这两句都会真走 LLM 多轮（含糊需求最后仍可能落规则降级）
    首条 = b""
    断因 = ""
    # 断开前记日志游标：只认这次断开之后新写的取消日志，别把同一次 E2E 里前几组
    # （比如 P5）留下的行当成自己的证据。
    游标 = 日志游标()
    try:
        请求 = urllib.request.Request(
            BASE + "/reports/generate-stream",
            data=json.dumps({"数据集ID": 数据集ID, "分析需求": 需求},
                            ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        t0 = time.time()
        with urllib.request.urlopen(请求, timeout=180) as r:
            首条 = r.readline()  # 只读一帧：读完就退出 with，socket 随即关闭
        首帧耗时 = time.time() - t0
    except Exception as e:  # noqa: BLE001
        断因 = f"{type(e).__name__}: {e}"
        首帧耗时 = 0.0
    check("P14 连上 SSE 读到第一帧后立刻断开（等价于用户关掉页面）",
          首条.startswith(b"data:") and not 断因,
          f"首条={首条[:70]!r} 断因={断因!r} 耗时={首帧耗时:.1f}s", group=G, cost=首帧耗时)

    # ★ 主证据：断开必须真的传到应用层。worker 在下一轮开头读令牌，所以这条日志会
    # 在断开后一两轮之内出现（单轮 LLM ~1.5s）；30s 还没出现就说明取消机制没生效。
    取消日志 = 等日志(r"第 \d 轮后收到取消信号[^\n]*", timeout=30, 起点=游标)
    check("P14 断开传导到应用层：后端日志出现「收到取消信号，跳过后续 LLM 调用」",
          bool(取消日志),
          f"命中={取消日志!r}（没命中＝event_stream 又被改回同步生成器，或令牌没被置位）",
          group=G)
    # 润色结论是流程里最后一个 LLM 调用（编排结束之后、报表落库之前）。它也必须被令牌拦下，
    # 否则「断开后不再发起新的 LLM 调用」在真机上仍然不成立。没有这条日志行 = 润色没被拦。
    润色日志 = 等日志(r"客户端已断开，跳过结论润色 LLM 调用[^\n]*", timeout=10, 起点=游标)
    check("P14 断开后结论润色也不再发 LLM 请求（最后一个 LLM 调用同样看令牌）",
          bool(润色日志),
          f"命中={润色日志!r}（没命中＝_生成结论_含来源 的 cancel 参数又被摘掉了）",
          group=G)

    # 断开后 worker 还在跑：轮询等报表落库（这是「报表照常生成」的证据）。
    # 判据 = 列表头（最新一份）的 ID 不在断开前的快照集合里 —— 只有真正新落库的那份才算。
    新报表ID = ""
    截止 = time.time() + 180
    while time.time() < 截止 and not 新报表ID:
        time.sleep(3)
        st, body = http("GET", "/reports/?limit=5", token=token, timeout=30)
        if st != 200:
            continue
        try:
            列表 = json.loads(body).get("报表列表") or []
        except Exception:  # noqa: BLE001
            continue
        if 列表:
            头部 = 列表[0].get("报表ID", "")
            if 头部 and 头部 not in 断前集合:
                新报表ID = 头部
    check("P14 客户端断开后报表仍然生成并落库（取消的是继续推理，不是这次分析）",
          bool(新报表ID),
          f"新报表ID={新报表ID!r} 断开前最新={断前最新!r} 断开前已知={len(断前集合)} 份"
          f"（判据=列表头不在断开前快照里；旧写法抓过旧报表导致假绿）",
          group=G)
    if not 新报表ID:
        return

    st, body = http("GET", f"/reports/{新报表ID}", token=token, timeout=60)
    意图来源 = ""
    轨迹: list = []
    内: dict = {}
    if st == 200:
        try:
            报 = json.loads(body)
            内 = 报.get("报表") or 报
            意图来源 = str(内.get("意图来源", ""))
            轨迹 = 内.get("Agent Trace") or 内.get("Agent_Trace") or []
        except Exception as e:  # noqa: BLE001
            note(f"P14 报表详情解析失败：{type(e).__name__}")
    说明集 = [str(x.get("说明", "")) for x in 轨迹 if isinstance(x, dict)]
    理由集 = [str(x.get("理由", "")) for x in 轨迹 if isinstance(x, dict)]
    状态集 = [str(x.get("状态", "")) for x in 轨迹 if isinstance(x, dict)]
    check("P14 断开的这一份落到规则降级（意图来源以「规则」开头，仅作辅助证据）",
          意图来源.startswith("规则"), f"意图来源={意图来源!r} 图表类型={内.get('图表类型')!r}" if st == 200 else f"{st} {str(body)[:140]}",
          group=G)
    # 说明落在「说明」还是「理由」键上取决于取消发生在哪一步（轮次开头 vs 重试前），两个都认。
    痕迹 = 说明集 + 理由集
    check("P14 trace 写明「客户端已断开」且状态记为「需关注」（不是「失败」）",
          any("断开" in s for s in 痕迹) and "需关注" in 状态集,
          f"说明尾部={说明集[-3:]} 理由尾部={理由集[-3:]} 状态尾部={状态集[-3:]}", group=G)


# --------------------------------------------------------------------------- 极限测试
def 跑极限测试(token, 用户名, 数据集ID):
    G = "P11 极限"
    print("\n== P11 极限测试 ==")
    if not token:
        check("极限测试前提：有可用 JWT", False, "P4 没抓到 token，整组跳过", group=G)
        return

    # E1a 16MB 应当放行：单文件上限是 50MB（api/routes/datasets.py:54 _MAX_UPLOAD_BYTES），
    # 早先这里断言「16MB 应被拒」是脚本把预期写错了——16MB 远在 50MB 之内，200 才是正确行为。
    超大 = b"a,b\n" + b"1,2\n" * 4_000_000  # ≈16 MB
    st, body = 上传字节(超大, "极限大文件.csv", token)
    check("E1a 16MB CSV 在 50MB 单文件上限内正常入库", st == 200 and "成功" in str(body),
          f"{st} {str(body)[:120]}", group=G)
    # E1b 越界：中间件按「整个请求体」的 Content-Length 拦（api/middleware.py:34-43，
    # MAX_BODY_BYTES=51MB），所以只要头里声明 60MB 就该在读 body 之前秒回 413——
    # 用裸 socket 声明超大 Content-Length 而不发真实 body，既测到拦截又不占 60MB 内存。
    st, 说明 = 裸发超大声明(60 * 1024 * 1024, token)
    check("E1b 声明 60MB 的请求体被中间件 413 拦下（防 DoS）", st == 413 and "PAYLOAD_TOO_LARGE" in 说明,
          f"{st} {说明[:120]}", group=G)

    # E2 超宽表 200 列
    宽 = 造宽CSV(200, 50)
    st, body = 上传字节(宽, "极限宽表200列.csv", token)
    check("E2 超宽表（200 列）上传后能被解析入库",
          st == 200 and "成功" in str(body), f"{st} {str(body)[:120]}", group=G)

    # E3 路径穿越文件名
    st, body = 上传字节(CSV_正常.encode("utf-8"), "../../../etc/passwd.csv", token)
    收敛 = ".." not in str(body)[:600]
    check("E3 路径穿越文件名：后端收敛掉路径分隔符", st == 200 and 收敛, f"{st} {str(body)[:160]}", group=G)

    # E4 SQL 注入串
    注入 = "e2e_x' OR '1'='1"
    st, body = http("POST", "/auth/send-code", {"email": f"{注入}@e2e.test"})
    check("E4 SQL 注入串进注册接口：报 4xx 而非 500", 400 <= st < 500, f"{st} {str(body)[:120]}", group=G)
    conn = mysql_conn()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users")
        用户数 = cur.fetchone()[0]
    conn.close()
    note(f"E4 之后 users 表仍可查（行数={用户数}）——注入串没把表打穿")

    # E5 XSS 串
    if 数据集ID:
        st, body = http("POST", "/reports/generate",
                        {"数据集ID": 数据集ID, "分析需求": "<script>alert('xss')</script> 按地区统计销售额"},
                        token=token, timeout=300)
        check("E5 XSS 串进分析需求：不 500", st < 500, f"{st} {str(body)[:140]}", group=G)
        # 存原文不是漏洞（用户数据不该被后端改写）；漏洞会出现在「前端怎么渲染它」。
        # 那一半在 P6b 用真实浏览器验过了，这里只留个路标。
        note("E5 只验到存储层（后端原样存 <script>）；是否被执行见 P6b「XSS 标题的真实渲染路径」")
    else:
        note("E5 跳过：没拿到数据集 ID")

    # E6 并发 20
    import threading
    结果 = []

    def _打():
        s, _b = http("GET", "/healthz", timeout=30)
        结果.append(s)
    线程 = [threading.Thread(target=_打) for _ in range(20)]
    t0 = time.time()
    [t.start() for t in 线程]
    [t.join() for t in 线程]
    check("E6 并发 20 次 /healthz 全部 200", 结果.count(200) == 20,
          f"200×{结果.count(200)} 其他={sorted(set(结果) - {200})}", group=G, cost=time.time() - t0)

    # E7 无 token
    for 路径 in ("/datasets/", "/reports/", "/auth/me", "/dashboards/"):
        st, _ = http("GET", 路径)
        check(f"E7 无 token 访问 {路径} 被拒", st in (401, 403), f"{st}", group=G)

    # E8 越权：用本轮 token 读报表列表首条（列表只应含自己的）
    st, body = http("GET", "/reports/?limit=50", token=token)
    条目 = []
    if st == 200:
        try:
            数据 = json.loads(body)
            # /reports/ 返回的键是中文 `报表列表`（api/routes/reports.py），不是 items。
            # 之前这里只认 items，于是 条目 恒为空、E8 的三条越权子用例被静默跳过。
            条目 = 数据.get("报表列表") or 数据.get("items") or (数据 if isinstance(数据, list) else [])
        except Exception:  # noqa: BLE001
            条目 = []
    check("E8 带 token 读报表列表返回 200", st == 200, f"{st} {str(body)[:100]}", group=G)
    if 条目:
        rid = 条目[0].get("id") or 条目[0].get("报表ID")
        s1, _ = http("GET", f"/reports/{rid}", token=token)
        check("E8 带 token 读自己的报表不 5xx", s1 < 500, f"{s1}", group=G)
        s2, b2 = http("GET", f"/reports/{rid}")
        check("E8 无 token 读该报表被拒（不是泄露）", s2 in (401, 403), f"{s2}", group=G)
        s3, b3 = http("GET", f"/reports/{rid}/export?format=csv")
        check("E8 无 token 导出该报表被拒", s3 in (401, 403), f"{s3}", group=G)
    else:
        note(f"E8 只验到列表层：{st} 但一条报表都没解析到，E8 的三条越权子用例没跑")

    # E9 十万字需求
    if 数据集ID:
        st, body = http("POST", "/reports/generate",
                        {"数据集ID": 数据集ID, "分析需求": "分析" + "很" * 100000},
                        token=token, timeout=300)
        check("E9 十万字需求被 max_length=2000 挡住（422 而非 500）", st in (422, 400), f"{st} {str(body)[:140]}", group=G)
    else:
        note("E9 跳过：没拿到数据集 ID")

    # E10 伪造 / 垃圾 JWT
    st, _ = http("GET", "/auth/me", token=token[:-3] + "xyz")
    check("E10 篡改 JWT 被拒", st in (401, 403), f"{st}", group=G)
    st, _ = http("GET", "/auth/me", token="not.a.jwt")
    check("E10 垃圾字符串当 JWT 被拒", st in (401, 403), f"{st}", group=G)
    st, _ = http("GET", "/auth/me", token="")
    check("E10 空 token 被拒", st in (401, 403), f"{st}", group=G)

    # E11 重复注册同一用户名 → 400/409/422，不是 500
    st, body = http("POST", "/auth/register",
                    {"username": 用户名, "email": f"{用户名}@e2e.test",
                     "code": "123456", "password": "E2e@2026Pass"})
    check("E11 重复注册同名用户：报 4xx 而非 500", 400 <= st < 500, f"{st} {str(body)[:120]}", group=G)

    # E12 错验证码
    st, body = http("POST", "/auth/register",
                    {"username": f"{用户名}_x", "email": f"{用户名}_x@e2e.test",
                     "code": "000000", "password": "E2e@2026Pass"})
    check("E12 错验证码注册：报 4xx 而非 500", 400 <= st < 500, f"{st} {str(body)[:120]}", group=G)

    # E13 密码超长（PBKDF2 DoS 防护）
    st, body = http("POST", "/auth/login", {"username": 用户名, "password": "x" * 500})
    check("E13 超长密码登录被 max_length=128 挡住", st in (422, 400), f"{st}", group=G)


def 裸发超大声明(声明字节, token, 路径="/datasets/upload"):
    """裸 socket 发一个「声明 Content-Length 巨大但实际不发 body」的请求。

    为什么能这么干：RequestBodyLimitMiddleware.dispatch（api/middleware.py:34-43）只看
    `request.headers["content-length"]` 就直接回 413，根本不读 body。所以真发 60MB 是
    浪费——声明足够大就能命中同一条拦截路径，返回 (状态码, 响应体首段)。
    """
    import socket
    主机, 端口 = "127.0.0.1", PORT
    请求 = (
        f"POST {路径} HTTP/1.1\r\n"
        f"Host: {主机}:{端口}\r\n"
        f"Authorization: Bearer {token}\r\n"
        "Content-Type: multipart/form-data; boundary=----e2e\r\n"
        f"Content-Length: {声明字节}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    try:
        with socket.create_connection((主机, 端口), timeout=20) as s:
            s.sendall(请求)
            chunks = []
            总 = 0
            while 总 < 65536:
                b = s.recv(4096)
                if not b:
                    break
                chunks.append(b)
                总 += len(b)
        原始 = b"".join(chunks).decode("utf-8", "replace")
        头, _, 体 = 原始.partition("\r\n\r\n")
        码 = int(头.split()[1]) if len(头.split()) > 1 else 0
        return 码, 体
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def 上传字节(数据, 文件名, token, content_type="text/csv", timeout=300):
    """multipart/form-data 上传（urllib 手写），字段名 file，与 POST /datasets/upload 对齐。"""
    边界 = "----e2e" + RUN_ID.replace("-", "")
    头 = (
        f"--{边界}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{文件名}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    体 = 头 + 数据 + f"\r\n--{边界}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        BASE + "/datasets/upload", data=体, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={边界}",
                 "Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    main()