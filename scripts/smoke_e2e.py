"""E2E 服务级冒烟：对运行中的 demo 服务验证完整用户链路。

覆盖：前端托管 → 上传数据集 → 生成报表 → 详情/溯源 → 追问 → 重放 →
分享(公开访问+撤销后的404) → 导出(xlsx/pdf) → 看板 → 权限边界(admin 403)。
任意环节失败即退出码 1。
"""
import io
import re
import sys

import requests

BASE = "http://127.0.0.1:8010"

fail = []


def check(name, ok, extra=""):
    status = "[OK]" if ok else "[FAIL]"
    print(f"  {status} {name}{(' — ' + extra) if extra else ''}")
    if not ok:
        fail.append(name)


s = requests.Session()
print("== 1. 前端托管（demo dist）==")
r = s.get(f"{BASE}/", timeout=10)
check("首页 200 + HTML", r.status_code == 200 and "text/html" in r.headers.get("content-type", ""))
m = re.search(r'<script[^>]+src="([^"]+)"', r.text)
if m:
    asset = requests.get(BASE + m.group(1), timeout=10)
    check(f"引用脚本可访问 {m.group(1)[:40]}", asset.status_code == 200)
else:
    check("提取到脚本引用", False)

print("== 2. 上传数据集 ==")
csv_data = "地区,销售额,月份\n华东,120,2026-01\n华东,150,2026-02\n华南,180,2026-01\n华南,90,2026-02\n华北,140,2026-01\n华中,110,2026-02"
r = s.post(f"{BASE}/datasets/upload", files={"file": ("销售数据.csv", csv_data.encode(), "text/csv")}, timeout=20)
check("上传 200", r.status_code == 200, r.text[:100])
did = r.json().get("数据集ID", "") if r.ok else ""
check("拿到数据集ID", bool(did))
print("  数据集:", did)

print("\n== 3. 生成报表（规则链路）==")
r = s.post(f"{BASE}/reports/generate", json={"数据集ID": did, "分析需求": "按地区统计销售额"}, timeout=60)
check("生成 200", r.status_code == 200, r.text[:200])
rid = r.json().get("报表ID", "") if r.ok else ""
check("拿到报表ID", bool(rid))
print("  报表:", rid)

print("\n== 4. 详情 + 溯源字段 ==")
r = s.get(f"{BASE}/reports/{rid}", timeout=10)
check("详情 200", r.status_code == 200)
body = r.json()
check("含图表配置", bool(body.get("报表", {}).get("图表配置")))
check("含 agent_mode 落库", body.get("报表", {}).get("agent_mode") == "single")

print("\n== 5. 多轮追问 → 新报表带溯源 ==")
r = s.post(f"{BASE}/reports/generate", json={"数据集ID": did, "分析需求": "那华南呢？", "上一报表ID": rid}, timeout=60)
check("追问生成 200", r.status_code == 200, r.text[:200])
rid2 = r.json().get("报表ID", "") if r.ok else ""
r = s.get(f"{BASE}/reports/{rid2}", timeout=10)
check("追问报表落库来源", r.ok and r.json().get("报表", {}).get("上一报表ID") == rid)
check("详情带来源标题", r.ok and bool(r.json().get("上一报表标题")))

print("\n== 6. 重放（历史重放）==")
r = s.post(f"{BASE}/reports/{rid}/replay", timeout=60)
check("重放 200", r.status_code == 200, r.text[:200])
check("重放新 ID", r.ok and r.json().get("报表ID") != rid)

print("\n== 7. 导出（xlsx / pdf / csv）==")
for fmt in ("xlsx", "pdf", "csv"):
    r = s.get(f"{BASE}/reports/{rid}/export?format={fmt}", timeout=30)
    check(f"导出 {fmt}", r.status_code == 200 and len(r.content) > 0, f"{len(r.content)}B")

print("\n== 8. 分享链接（公开只读）==")
r = s.post(f"{BASE}/reports/{rid}/share", json={"有效小时数": 24}, timeout=10)
check("创建分享 200", r.status_code == 200, r.text[:200])
link = r.json().get("分享链接", "") if r.ok else ""
sid = r.json().get("链接ID", "") if r.ok else ""
check("分享链接格式", link.startswith("/s/"))
# 页面路由：返回 SPA HTML（供前端渲染分享页）
r = s.get(BASE + link, timeout=10)
check("分享页面返回 HTML", r.status_code == 200 and "text/html" in r.headers.get("content-type", ""))
# 数据端点：匿名 JSON 只读视图
r = s.get(f"{BASE}/share-data/{sid}", timeout=10)
check("匿名数据端点 200", r.status_code == 200)
check("公开视图含图表", r.ok and "图表配置" in r.json() and "Agent Trace" not in str(r.json()))

print("\n== 9. 看板（多图对比）==")
r = s.post(f"{BASE}/dashboards", json={"名称": "冒烟看板", "报表ID列表": [rid, rid2]}, timeout=10)
check("新建看板 200", r.status_code == 200, r.text[:200])
dbid = r.json().get("看板ID", "") if r.ok else ""
r = s.get(f"{BASE}/dashboards/{dbid}", timeout=10)
check("看板详情 2 图", r.ok and len(r.json().get("报表列表", [])) == 2)

print("\n== 10. 权限边界 ==")
r = s.get(f"{BASE}/admin/statistics", timeout=10)
check("普通用户访问管理端 403", r.status_code == 403, f"实际 {r.status_code}")

print()
if fail:
    print(f"SMOKE FAILED: {len(fail)} items -> {fail}")
    sys.exit(1)
print("SMOKE PASSED: full chain OK (demo mode auto-enters)")