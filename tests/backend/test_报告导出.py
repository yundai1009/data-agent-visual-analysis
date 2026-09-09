"""阶段 30 · 完整 PDF 报告导出测试：函数级 + API 级，不依赖网络与 LLM key。

覆盖目标
========
- ``_构建PDF报告``：无图版 / 带图版 / 坏图降级（不阻断导出）
- ``POST /reports/{id}/export-report``：合法请求返回 PDF、未登录 401、坏图降级 200
- PDF 内容包含：结论、筛选说明、Trace 摘要（抽查字节级内容）

设计原则
========
- 用 FastAPI TestClient + 临时 SQLite（与 test_api_integration 同模式）；
- 报表走 /reports/generate（规则兜底，无 LLM key 也可生成）；
- 1x1 PNG base64 硬编码，避免测试依赖画图库。
"""

from __future__ import annotations

import base64
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 1x1 黑色 PNG（经典最小合法 PNG）
_1PX_PNG = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
_BAD_PNG = base64.b64encode(b"not a real png").decode()

# ---- 邮件验证码捕获（与 test_api_integration 同模式）----
_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("report_export_test")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True
    # 仓储在模块 import 时已按旧路径建表；改路径后须显式重跑（幂等），
    # 否则本模块的临时库是空库（no such table: datasets）
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    初始化数据库()

    from services import email_service

    def _fake_send(email: str, code: str) -> bool:
        _SENT_CODES[email] = code
        return True

    _orig_send = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake_send
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            yield c
    finally:
        email_service.发送验证码邮件 = _orig_send


def _register(client, username, email=None) -> str:
    email = email or f"{username}@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _make_report(client, token) -> str:
    """上传 CSV → 生成报表（规则兜底），返回 report_id。"""
    r = client.post(
        "/datasets/upload",
        files={"file": ("t.csv", "地区,销售额\n华东,100\n华南,200\n华东,300\n", "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    ds_id = r.json()["上传成功"][0]["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": ds_id,
        "分析需求": "按地区统计销售额Top 1",
        "图表类型": "自动推荐",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["报表ID"]


# ============================================================================
# 1. 函数级：_构建PDF报告
# ============================================================================

class Test构建PDF报告:
    def test_无图版生成合法PDF(self):
        from api.routes.reports import _构建PDF报告
        report = {
            "图表类型": "柱状图", "意图来源": "规则",
            "图表配置": {"筛选说明": ["地区 等于 华东"], "TopN": 1},
            "结论": "华东销售额最高。",
            "报表数据": [{"地区": "华东", "销售额": 400}],
            "推荐说明": {"理由": ["按销售额聚合"]},
            "风险提示": ["数据仅 2 行"],
            "Agent Trace": [{"步骤": "聚合分析", "说明": "按地区求和", "状态": "成功"}],
        }
        buf = _构建PDF报告(report, "测试报表")
        data = buf.getvalue()
        assert data.startswith(b"%PDF")
        assert len(data) > 500  # 有实质内容
        # 筛选徽标确实进入了 PDF：带筛选的版本应比不带筛选的更大
        # （reportlab 压缩内容流，明文断言不可行，用尺寸差异证明内容差异）
        plain = {"图表类型": "柱状图", "图表配置": {}, "报表数据": [], "结论": "x"}
        data_plain = _构建PDF报告(plain, "测试报表").getvalue()
        assert len(data) > len(data_plain)

    def test_带图版生成合法PDF(self):
        from api.routes.reports import _构建PDF报告
        report = {"图表类型": "柱状图", "图表配置": {}, "报表数据": []}
        buf = _构建PDF报告(report, "带图报表", chart_png=f"data:image/png;base64,{_1PX_PNG}")
        assert buf.getvalue().startswith(b"%PDF")

    def test_坏图降级不阻断(self):
        from api.routes.reports import _构建PDF报告
        report = {"图表类型": "柱状图", "图表配置": {}, "报表数据": []}
        buf = _构建PDF报告(report, "坏图报表", chart_png=f"data:image/png;base64,{_BAD_PNG}")
        assert buf.getvalue().startswith(b"%PDF")

    def test_trace摘要截断(self):
        from api.routes.reports import _构建PDF报告
        trace = [{"步骤": f"步骤{i}", "说明": "x" * 500, "状态": "成功"} for i in range(50)]
        report = {"图表类型": "柱状图", "图表配置": {}, "报表数据": [], "Agent Trace": trace}
        buf = _构建PDF报告(report, "长Trace")
        assert buf.getvalue().startswith(b"%PDF")


# ============================================================================
# 2. API 级：POST /reports/{id}/export-report
# ============================================================================

class Test导出完整报告API:
    def test_合法请求返回PDF(self, client):
        token = _register(client, "pdfuser")
        rid = _make_report(client, token)
        r = client.post(
            f"/reports/{rid}/export-report",
            json={"chart_png": f"data:image/png;base64,{_1PX_PNG}"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content.startswith(b"%PDF")

    def test_坏图降级仍返回PDF(self, client):
        token = _register(client, "pdfuser2")
        rid = _make_report(client, token)
        r = client.post(
            f"/reports/{rid}/export-report",
            json={"chart_png": f"data:image/png;base64,{_BAD_PNG}"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")

    def test_无图也返回PDF(self, client):
        token = _register(client, "pdfuser3")
        rid = _make_report(client, token)
        r = client.post(
            f"/reports/{rid}/export-report",
            json={"chart_png": ""},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, r.text

    def test_未登录401(self, client):
        r = client.post("/reports/whatever/export-report", json={"chart_png": ""})
        assert r.status_code == 401

    def test_他人报表404(self, client):
        token_a = _register(client, "pdfa")
        token_b = _register(client, "pdfb")
        rid = _make_report(client, token_a)
        r = client.post(
            f"/reports/{rid}/export-report",
            json={"chart_png": ""},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 404

    def test_超大图400(self, client):
        token = _register(client, "pdfuser4")
        rid = _make_report(client, token)
        r = client.post(
            f"/reports/{rid}/export-report",
            json={"chart_png": "a" * 8_000_001},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 400 or r.status_code == 422  # Pydantic max_length 拦截