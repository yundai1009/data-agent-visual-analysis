# -*- coding: utf-8 -*-
"""阶段 55 · Task5 报表精细化编辑 HTTP 端点测试。

POST /reports/{report_id}/refine
- NL 指令解析 → 校验 → 本地重算 → 另存新报表 → 返回 变更对比
- 标识符/编码字段禁作 Y 轴 → 拒绝并说明（不落库）
- 模糊指令 → 需确认（不修改）
- 无 ReAct：本路径不触发 LLM（无 llm 调用依赖，纯本地）
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("refine_api_test")
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


def _send_and_get_code(client, email: str) -> str:
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code, f"未能获取到 {email} 的验证码"
    return code


def _register(client, username, password="secret123", email=None):
    email = email or f"{username}@test.com"
    code = _send_and_get_code(client, email)
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _upload(client, token, filename="test.csv", content="地区,销售额\n华东,100\n华南,200\n"):
    if isinstance(content, str):
        content = content.encode()
    return client.post(
        "/datasets/upload",
        files={"file": (filename, content, "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )


def _did(j):
    # 兼容 Response 或已解析 dict
    if hasattr(j, "json"):
        j = j.json()
    if "上传成功" in j:
        return j["上传成功"][0]["数据集ID"]
    return j["数据集ID"]


CSV = "地区,销售额\n华东,100\n华南,200\n华北,300\n"


def _生成报表(client, token, did, 需求="各地区销售额对比"):
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": 需求, "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和",
        "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_refine_NL换X轴_另存新报表(client):
    tok = _register(client, "refine1")
    # 两个分类字段，换 X 轴才有实际变化（原需求已选"地区"做 X 轴）
    csv = "地区,城市,销售额\n华东,上海,100\n华南,广州,200\n华北,北京,300\n"
    did = _did(_upload(client, tok, content=csv))
    orig = _生成报表(client, tok, did, 需求="各地区销售额")
    rid = orig["报表ID"]

    r = client.post(f"/reports/{rid}/refine", json={"指令": "把X轴换成城市"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text[:300]
    b = r.json()
    assert b["需确认"] is False
    assert b["拒绝原因"] is None
    assert b["新spec"]["X轴"] == "城市"
    assert b["新报表ID"]
    assert any(it["字段"] == "X轴" for it in b["变更清单"])
    # 原报表未被修改（另存语义）：新报表 ID ≠ 原 ID
    assert b["新报表ID"] != rid


def test_refine_标识符Y轴被拒_不落库(client):
    tok = _register(client, "refine2")
    csv = "订单ID,金额\n1001,5\n1002,7\n1003,9\n"
    did = _did(_upload(client, tok, content=csv))
    orig = _生成报表(client, tok, did, 需求="订单ID")
    rid = orig["报表ID"]

    r = client.post(f"/reports/{rid}/refine", json={"指令": "把Y轴换成订单ID"},
                    headers={"Authorization": f"Bearer {tok}"})
    b = r.json()
    assert b["拒绝原因"], "标识符作 Y 轴应拒绝"
    assert "标识符" in b["拒绝原因"]


def test_refine_模糊指令需确认_不修改(client):
    tok = _register(client, "refine3")
    did = _did(_upload(client, tok, content=CSV))
    orig = _生成报表(client, tok, did)
    rid = orig["报表ID"]

    r = client.post(f"/reports/{rid}/refine", json={"指令": "把图表换个看不懂的样式"},
                    headers={"Authorization": f"Bearer {tok}"})
    b = r.json()
    assert b["需确认"] is True


def test_refine_结构化面板参数_改标题(client):
    tok = _register(client, "refine4")
    did = _did(_upload(client, tok, content=CSV))
    orig = _生成报表(client, tok, did)
    rid = orig["报表ID"]

    r = client.post(f"/reports/{rid}/refine",
                    json={"编辑": {"动作": "改标题", "标题": "【各地区销售额对比】"}},
                    headers={"Authorization": f"Bearer {tok}"})
    b = r.json()
    assert b["新spec"]["标题"] == "【各地区销售额对比】"
    assert any(it["字段"] == "标题" for it in b["变更清单"])


def test_refine_报表不存在404(client):
    tok = _register(client, "refine5")
    r = client.post("/reports/aaaaaaaaaaaaaaaa/refine", json={"指令": "把X轴换成地区"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 404


def test_refine_切饼图_补名称与值(client):
    tok = _register(client, "refine6")
    did = _did(_upload(client, tok, content="地区,销售额\n华东,100\n华南,200\n华北,300\n"))
    orig = _生成报表(client, tok, did)
    rid = orig["报表ID"]

    r = client.post(f"/reports/{rid}/refine", json={"指令": "切换成饼图"},
                    headers={"Authorization": f"Bearer {tok}"})
    b = r.json()
    spec = b["新spec"]
    assert spec["类型"] == "pie"
    assert "名称" in spec and "值" in spec


def test_refine_加筛选_重算行数变化(client):
    tok = _register(client, "refine7")
    did = _did(_upload(client, tok, content=CSV))
    orig = _生成报表(client, tok, did)
    rid = orig["报表ID"]

    r = client.post(f"/reports/{rid}/refine",
                    json={"编辑": {"动作": "加筛选", "筛选": {"字段": "地区", "值": "华东"}}},
                    headers={"Authorization": f"Bearer {tok}"})
    b = r.json()
    assert b["新spec"]["数据"], "筛选后应有数据"
    assert len(b["新spec"]["数据"]) == 1