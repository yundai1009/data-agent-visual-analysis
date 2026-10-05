# -*- coding: utf-8 -*-
"""阶段 54-5 · Fix 1/2：XLSX/CSV 导出公式注入转义（含表头 + 前导空白绕过）。

走查证据
========
- 上传含 =SUM(A1:A2) / =HYPERLINK(...) 的 CSV → 生成报表 → 导出 xlsx →
  sheet1.xml 出现真实 <f> 公式标签，Excel 打开即执行公式；
- CSV 分支已有转义但正则 ^[=+@-] 不覆盖前导空白（TAB/空格绕过），且列名
  （DataFrame 表头）未转义。

本文件覆盖
==========
1. 共享转义函数 _公式注入转义 / _公式注入转义行 单测
   （str 且以 ^[\\s]*[=+@-] 开头 → 加 ' 前缀；非 str 原样；key 同样转义）
2. API 级：上传 inject.csv → 生成表格报表 → csv 导出断言危险值与表头全部转义
3. API 级：同报表 xlsx 导出 → zip 内无 <f> 公式标签、危险值以 ' 开头
4. 导出全部 ZIP：含公式报表在 zip 内 csv / xlsx 分支均被转义
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

# 危险数据注入 CSV：列名 =值 也要被转义（表头来自 dict key）
_INJECT_CSV = (
    "=值,地区,数量\n"
    "=SUM(A1:A2),华东,100\n"
    "@cmd,华南,200\n"
    "\t=cmd,华东,300\n"
)


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix_export_inject")
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


def _生成注入报表(client, token) -> str:
    """上传 inject.csv → 生成表格报表（原始明细进报表数据），返回 report_id。"""
    h = {"Authorization": f"Bearer {token}"}
    r = client.post(
        "/datasets/upload",
        files={"file": ("inject.csv", _INJECT_CSV.encode("utf-8"), "text/csv")},
        headers=h,
    )
    assert r.status_code == 200, r.text
    ds_id = r.json()["上传成功"][0]["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": ds_id,
        "分析需求": "查看全部数据",
        "图表类型": "表格",  # 表格 = df.head(200) 原始明细，危险值原样进入报表数据
    }, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["报表ID"]


def _zip文本(content: bytes) -> dict:
    """解包 xlsx/zip 字节，返回 {内部文件路径: 解码文本}。"""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        return {n: z.read(n).decode("utf-8", errors="replace") for n in z.namelist()}


# ============================================================================
# 1. 共享转义函数单测（红：函数尚不存在）
# ============================================================================

class Test共享转义函数:
    def test_等号开头加前缀(self):
        from api.routes.reports import _公式注入转义
        assert _公式注入转义("=SUM(A1:A2)") == "'=SUM(A1:A2)"

    def test_at符号开头加前缀(self):
        from api.routes.reports import _公式注入转义
        assert _公式注入转义("@cmd") == "'@cmd"

    def test_加减号开头加前缀(self):
        from api.routes.reports import _公式注入转义
        assert _公式注入转义("+1") == "'+1"
        assert _公式注入转义("-1") == "'-1"

    def test_前导空格绕过被堵(self):
        from api.routes.reports import _公式注入转义
        assert _公式注入转义("  =1") == "'  =1"

    def test_前导TAB绕过被堵(self):
        from api.routes.reports import _公式注入转义
        assert _公式注入转义("\t=cmd") == "'\t=cmd"

    def test_普通值与非str不动(self):
        from api.routes.reports import _公式注入转义
        assert _公式注入转义("正常值") == "正常值"
        assert _公式注入转义(123) == 123
        assert _公式注入转义(None) is None

    def test_整行转义_含表头key(self):
        from api.routes.reports import _公式注入转义行
        row = {"=值": "=SUM(A1:A2)", "地区": "@cmd", "数量": 100}
        assert _公式注入转义行(row) == {"'=值": "'=SUM(A1:A2)", "地区": "'@cmd", "数量": 100}


# ============================================================================
# 2. API 级：单份导出 csv / xlsx
# ============================================================================

class Test单份导出转义:
    def test_导出csv_危险值与表头全部转义(self, client):
        token = _注册(client, "inj1")
        rid = _生成注入报表(client, token)
        r = client.get(f"/reports/{rid}/export?format=csv", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        text = r.text
        # 值转义（含 TAB 绕过）
        assert "'=SUM(A1:A2)" in text, text
        assert "'@cmd" in text, text
        assert "'\t=cmd" in text, text
        # 表头转义（Fix 2：dict key 是注入源）
        assert "'=值" in text, text

    def test_导出xlsx_无公式标签且危险值带前缀(self, client):
        token = _注册(client, "inj2")
        rid = _生成注入报表(client, token)
        r = client.get(f"/reports/{rid}/export?format=xlsx", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        texts = _zip文本(r.content)
        sheet1 = texts.get("xl/worksheets/sheet1.xml", "")
        # Critical：绝不能出现真实公式标签
        assert "<f>" not in sheet1, sheet1
        # 危险值以 ' 开头（sharedStrings / inlineStr 任一位置）
        assert any("'=SUM(A1:A2)" in t for t in texts.values()), texts.keys()
        assert any("'@cmd" in t for t in texts.values()), texts.keys()

    def test_导出全部zip_csv分支转义(self, client):
        token = _注册(client, "inj3")
        _生成注入报表(client, token)
        r = client.get("/reports/export-all?format=csv", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            csv_texts = [z.read(n).decode("utf-8", errors="replace") for n in z.namelist() if n.endswith(".csv")]
        assert csv_texts, "zip 内应有 csv"
        joined = "\n".join(csv_texts)
        assert "'=SUM(A1:A2)" in joined, joined
        assert "'=值" in joined, joined  # 表头同样转义

    def test_导出全部zip_xlsx分支无公式(self, client):
        token = _注册(client, "inj4")
        _生成注入报表(client, token)
        r = client.get("/reports/export-all?format=xlsx", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in z.namelist():
                if not n.endswith(".xlsx"):
                    continue
                sub = _zip文本(z.read(n))
                sheet1 = sub.get("xl/worksheets/sheet1.xml", "")
                assert "<f>" not in sheet1, f"{n} 含公式标签"
                assert any("'=SUM(A1:A2)" in t for t in sub.values()), f"{n} 未转义"


# ============================================================================
# 3. CSV 导出 BOM（真实走查 F2：无 BOM 时中文 Windows Excel 打开乱码）
# ============================================================================

class Test导出CSV带BOM:
    def test_单份导出csv_带UTF8BOM(self, client):
        """导出内容含中文（表头 '地区' 等），首字节必须是 UTF-8 BOM（EF BB BF）。"""
        token = _注册(client, "bom1")
        rid = _生成注入报表(client, token)  # 报表数据含中文（华东/华南）
        r = client.get(f"/reports/{rid}/export?format=csv", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        raw = r.content
        assert raw[:3] == b"\xef\xbb\xbf", (
            f"CSV 导出缺少 UTF-8 BOM（前 3 字节 {raw[:3]!r}），中文 Windows Excel 打开会乱码"
        )
        # BOM 之后内容仍可正常 UTF-8 解码且含中文
        text = raw[3:].decode("utf-8")
        assert "华东" in text, text

    def test_导出全部zip_csv分支带BOM(self, client):
        token = _注册(client, "bom2")
        _生成注入报表(client, token)
        r = client.get("/reports/export-all?format=csv", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            csv_files = [n for n in z.namelist() if n.endswith(".csv")]
        assert csv_files, "zip 内应有 csv"
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            for n in csv_files:
                raw = z.read(n)
                assert raw[:3] == b"\xef\xbb\xbf", f"{n} 缺 BOM（前 3 字节 {raw[:3]!r}）"
                text = raw[3:].decode("utf-8")
                assert "华东" in text, f"{n} 内容异常: {text[:50]}"