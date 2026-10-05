# -*- coding: utf-8 -*-
"""阶段 54-6 · Fix 4：导出日期 ISO 字符串 + 浮点噪声修复。

走查证据
========
- 银行-金额趋势折线（366 行）导出 xlsx/csv：
  A2='2024-01-01T00:00:00'（openpyxl data_type='s'，非 Excel 日期格式）；
  金额带浮点尾巴 6933736.7700000005。

本文件覆盖
==========
1. 单元级：_导出值格式化（ISO 日期截取、浮点去噪）
2. API 级：单份导出 csv/xlsx —— 无 "T00:00:00"、无长浮点尾巴
3. API 级：导出全部 ZIP 的 csv/xlsx 分支同样生效
"""

from __future__ import annotations

import io
import os
import sys
import zipfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"

_SENT_CODES: dict = {}

# 含日期 + 浮点噪声的走查同构数据：0.1+0.2 求和产生二进制尾巴 0.30000000000000004
# （与走查 6933736.77 求和出现 .7700000005 尾巴同源）
_F4_CSV = (
    "日期,金额\n"
    "2024-01-01,0.1\n"
    "2024-01-01,0.2\n"
    "2024-01-02,100\n"
    "2024-01-03,200.5\n"
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix_export_format")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True

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


def _注册(client, username):
    email = f"{username}@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code, f"未捕获到 {email} 的验证码"
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _生成趋势报表(client, token) -> str:
    """上传日期+金额 CSV → 生成折线图报表（日期 ISO 化 + 浮点尾巴进入报表数据）。"""
    h = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/datasets/upload",
        files={"file": ("bank.csv", _F4_CSV.encode("utf-8"), "text/csv")},
        headers=h,
    )
    assert r.status_code == 200, r.text
    ds_id = r.json()["上传成功"][0]["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": ds_id,
        "分析需求": "看金额趋势",
        "图表类型": "折线图",
        "x轴": "日期",
        "y轴": ["金额"],
        "分组字段": None,
        "聚合方式": "求和",
        "agent_mode": "single",
    }, headers=h)
    assert r.status_code == 200, r.text
    report = r.json()
    # 前置校验：报表数据确实带 ISO 日期 + 浮点尾巴（测试针对真实缺陷形态）
    assert any("T00:00:00" in str(row) for row in report["报表数据"]), report["报表数据"]
    return report["报表ID"]


def _zip文本(content: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return {n: z.read(n).decode("utf-8", errors="replace") for n in z.namelist()}


def _xlsx单元格值(content: bytes) -> list:
    """用 openpyxl 读 xlsx，返回 (行, 列, 值) 列表——断言单元格真实写入值。"""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    return [(cell.row, cell.column, cell.value) for row in ws.iter_rows() for cell in row]


# ============================================================================
# 1. 单元级：_导出值格式化
# ============================================================================

class Test导出值格式化:
    def test_ISO日期零点截取为日期(self):
        from api.routes.reports import _导出值格式化
        assert _导出值格式化("2024-01-01T00:00:00") == "2024-01-01"

    def test_ISO日期带时分保留(self):
        from api.routes.reports import _导出值格式化
        assert _导出值格式化("2024-01-01T08:30:00") == "2024-01-01 08:30"

    def test_浮点噪声去噪(self):
        from api.routes.reports import _导出值格式化
        assert _导出值格式化(6933736.7700000005) == 6933736.77
        assert _导出值格式化(200.5) == 200.5  # 非噪声浮点保持业务精度

    def test_整数化浮点(self):
        from api.routes.reports import _导出值格式化
        assert _导出值格式化(100.0) == 100

    def test_其余值原样(self):
        from api.routes.reports import _导出值格式化
        assert _导出值格式化("普通文本") == "普通文本"
        assert _导出值格式化(None) is None
        assert _导出值格式化(123) == 123


# ============================================================================
# 2. API 级：单份导出 csv / xlsx
# ============================================================================

class Test单份导出格式化:
    def test_导出csv_无ISO无浮点尾巴(self, client):
        token = _注册(client, "fmt1")
        rid = _生成趋势报表(client, token)
        r = client.get(f"/reports/{rid}/export?format=csv", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        text = r.content[3:].decode("utf-8")  # 跳过 UTF-8 BOM
        assert "T00:00:00" not in text, text
        assert "2024-01-01T" not in text, text
        assert "30000000000000004" not in text, text
        # 日期以 YYYY-MM-DD 出现（00:00 截断为纯日期）；浮点尾巴已去噪到业务精度
        assert "2024-01-01" in text, text
        assert "0.3" in text, text

    def test_导出xlsx_单元格为日期串且无浮点尾巴(self, client):
        token = _注册(client, "fmt2")
        rid = _生成趋势报表(client, token)
        r = client.get(f"/reports/{rid}/export?format=xlsx", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        cells = _xlsx单元格值(r.content)
        values = [v for _, _, v in cells if v is not None]
        assert not any("T00:00:00" in str(v) for v in values), values
        assert not any("30000000000000004" in str(v) for v in values), values
        # 日期单元格应为纯日期串 "2024-01-01"（data_type='s'，非 datetime/ISO）
        assert any(v == "2024-01-01" for v in values), values
        assert any(v == 0.3 for v in values), values


# ============================================================================
# 3. API 级：导出全部 ZIP 的 csv/xlsx 分支
# ============================================================================

class Test导出全部ZIP格式化:
    def test_导出全部csv分支无ISO无浮点尾巴(self, client):
        token = _注册(client, "fmt3")
        _生成趋势报表(client, token)
        r = client.get("/reports/export-all?format=csv", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            csv_names = [n for n in z.namelist() if n.endswith(".csv")]
        assert csv_names, "zip 内应有 csv"
        joined = ""
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in csv_names:
                joined += z.read(n)[3:].decode("utf-8", errors="replace")
        assert "T00:00:00" not in joined, joined
        assert "30000000000000004" not in joined, joined
        assert "2024-01-01" in joined, joined

    def test_导出全部xlsx分支单元格已格式化(self, client):
        token = _注册(client, "fmt4")
        _生成趋势报表(client, token)
        r = client.get("/reports/export-all?format=xlsx", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            xlsx_names = [n for n in z.namelist() if n.endswith(".xlsx")]
        assert xlsx_names, "zip 内应有 xlsx"
        checked = False
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in xlsx_names:
                cells = _xlsx单元格值(z.read(n))
                values = [v for _, _, v in cells if v is not None]
                assert not any("T00:00:00" in str(v) for v in values), (n, values)
                assert not any("30000000000000004" in str(v) for v in values), (n, values)
                checked = True
        assert checked
