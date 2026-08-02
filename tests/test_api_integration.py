"""API 集成测试：认证、上传、隔离、报表、LLM 安全、错误响应。

用 FastAPI TestClient + 临时 SQLite，不依赖真实网络和 LLM Key。
注册走邮箱验证码：测试内 monkeypatch 邮件发送函数捕获验证码。
运行：
    python -m pytest tests/test_api_integration.py -v
"""

from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 测试环境：开启认证、用临时数据库
os.environ["AUTH_ENABLED"] = "true"

# 捕获 dry-run 验证码：monkeypatch 邮件发送函数
_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """TestClient + 临时 SQLite + 验证码捕获。"""
    tmp_dir = tmp_path_factory.mktemp("api_test")
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
    """调 send-code 并返回捕获的验证码。"""
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code, f"未捕获到 {email} 的验证码"
    return code


def _register(client, username, password="secret123", email=None):
    """发送验证码 → 取码 → 注册（固定 analyst 角色）。"""
    email = email or f"{username}@test.com"
    code = _send_and_get_code(client, email)
    r = client.post("/auth/register", json={
        "username": username,
        "email": email,
        "code": code,
        "password": password,
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


# ---- 8.1 认证 ----

def test_注册_登录_流程(client):
    tok = _register(client, "alice")
    r = client.post("/auth/login", json={"username": "alice", "password": "secret123"})
    assert r.status_code == 200
    assert r.json()["user"]["username"] == "alice"

def test_错误密码_401(client):
    _register(client, "bob")
    r = client.post("/auth/login", json={"username": "bob", "password": "wrong"})
    assert r.status_code == 401

def test_伪造token_401(client):
    r = client.get("/datasets/", headers={"Authorization": "Bearer fake_token_12345678"})
    assert r.status_code == 401

def test_无token_401(client):
    r = client.get("/datasets/")
    assert r.status_code == 401

def test_普通用户访问admin_403(client):
    tok = _register(client, "carol")
    r = client.get("/admin/golden-set", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


# ---- 8.1.5 阶段十三：种子管理员 + 邮箱验证码注册 ----

def test_种子admin登录_并访问admin(client):
    # lifespan 启动时幂等创建 admin / admin123
    r = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200
    tok = r.json()["access_token"]
    r = client.get("/admin/golden-set", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200


def test_注册带role字段_422(client):
    email = "role_hack@test.com"
    code = _send_and_get_code(client, email)
    # extra="forbid"：携带 role 等多余字段直接 422，杜绝自注册提权
    r = client.post("/auth/register", json={
        "username": "hacker", "email": email, "code": code,
        "password": "secret123", "role": "admin",
    })
    assert r.status_code == 422
    # 注册被拒 → 账号未创建（登录失败），且邮箱未被占用
    r3 = client.post("/auth/login", json={"username": "hacker", "password": "secret123"})
    assert r3.status_code == 401


def test_注册成功固定analyst(client):
    tok = _register(client, "molly")
    r = client.get("/admin/golden-set", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403  # 普通注册用户无 admin 权限


def test_验证码错误_400(client):
    email = "wrong_code@test.com"
    _send_and_get_code(client, email)
    r = client.post("/auth/register", json={
        "username": "wrongcode", "email": email, "code": "000000", "password": "secret123",
    })
    assert r.status_code == 400
    assert "验证码错误" in r.json()["message"]


def test_验证码过期_400(client):
    from repositories import email_code_repo
    email = "expired_code@test.com"
    _send_and_get_code(client, email)
    # 直接把过期时间改为过去，模拟验证码过期
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    email_code_repo.保存验证码(email, "stale-hash", past)
    r = client.post("/auth/register", json={
        "username": "expired", "email": email, "code": "123456", "password": "secret123",
    })
    assert r.status_code == 400
    assert "过期" in r.json()["message"]


def test_验证码重放_400(client):
    email = "replay@test.com"
    code = _send_and_get_code(client, email)
    r = client.post("/auth/register", json={
        "username": "replay1", "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200
    # 同一验证码再次注册 → 已使用
    r2 = client.post("/auth/register", json={
        "username": "replay2", "email": email, "code": code, "password": "secret123",
    })
    assert r2.status_code == 400
    assert "已使用" in r2.json()["message"]


def test_邮箱重复注册_400(client):
    email = "dup@test.com"
    _register(client, "dupa", email=email)
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 400
    assert "已被注册" in r.json()["message"]


def test_邮箱格式非法_422(client):
    r = client.post("/auth/send-code", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_用户名含at_422(client):
    email = "at_user@test.com"
    _send_and_get_code(client, email)
    r = client.post("/auth/register", json={
        "username": "bad@name", "email": email, "code": "123456", "password": "secret123",
    })
    assert r.status_code == 422  # 用户名禁止 @，避免与邮箱登录歧义


def test_邮箱登录_200(client):
    email = "maillogin@test.com"
    _register(client, "mailuser", email=email)
    r = client.post("/auth/login", json={"username": email, "password": "secret123"})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == email


def test_sendcode限频_429(client):
    email = "ratelimit@test.com"
    r1 = client.post("/auth/send-code", json={"email": email})
    assert r1.status_code == 200
    r2 = client.post("/auth/send-code", json={"email": email})
    assert r2.status_code == 429
    assert "频繁" in r2.json()["message"]


# ---- 8.2 上传 ----

def test_上传合法CSV(client):
    tok = _register(client, "dave")
    r = _upload(client, tok)
    assert r.status_code == 200
    body = r.json()
    assert body["数据集ID"]
    assert body["行数"] == 2
    assert "地区" in body["字段列表"]


def test_生成词云图(client):
    """文本字段 → 词云图：jieba 分词统计词频，返回 name/value 数据。"""
    tok = _register(client, "cloud")
    content = "评论\n这个产品非常好用强烈推荐\n产品性价比很高很好用\n推荐给朋友都说好\n这个产品一般般还可以\n强烈推荐这个产品\n性价比一般但好用\n"
    r = _upload(client, tok, filename="reviews.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "生成词云图", "图表类型": "词云图",
        "x轴": "评论", "y轴": [], "分组字段": None, "聚合方式": "计数", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["图表类型"] == "词云图"
    assert body["图表配置"]["类型"] == "wordcloud"
    rows = body["报表数据"]
    assert len(rows) > 0, "词云数据不应为空"
    assert all("name" in row and "value" in row for row in rows)
    # 词频最高的应是"产品"
    assert rows[0]["name"] == "产品"


def test_七种新增图表生成(client):
    """漏斗/桑基/箱线/环形/瀑布/旭日/K线 均可生成且类型映射正确。"""
    tok = _register(client, "chart7")
    content = ("地区,渠道,销售额,日期\n"
               "华东,线上,100,2024-01-01\n华东,线下,200,2024-01-02\n"
               "华南,线上,300,2024-01-03\n华南,线下,150,2024-01-04\n"
               "华北,线上,80,2024-01-05\n华北,线下,250,2024-01-06\n")
    r = _upload(client, tok, filename="sales.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    cases = [
        ("漏斗图", "funnel", "地区", ["销售额"], None, "求和"),
        ("桑基图", "sankey", "地区", ["销售额"], "渠道", "求和"),
        ("箱线图", "boxplot", "地区", ["销售额"], None, "求和"),
        ("环形图", "donut", "地区", ["销售额"], None, "求和"),
        ("瀑布图", "waterfall", "地区", ["销售额"], None, "求和"),
        ("旭日图", "sunburst", "地区", ["记录数"], "渠道", "计数"),
        ("K线图", "candlestick", "日期", ["销售额"], None, "求和"),
    ]
    for label, ctype, x, y, group, agg in cases:
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": "", "图表类型": label,
            "x轴": x, "y轴": y, "分组字段": group, "聚合方式": agg, "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, f"{label}: {r.text[:200]}"
        body = r.json()
        assert body["图表类型"] == label
        assert body["图表配置"]["类型"] == ctype
        assert len(body["报表数据"]) > 0, f"{label} 数据为空"


def test_图表数据不满足时返回400而非500(client):
    """词云数值列 / 桑基缺分组字段：应 400 明确提示，而非 500。"""
    tok = _register(client, "chart400")
    content = ("地区,销售额,备注\n华东,100,优质客户\n华南,200,普通客户\n华北,150,优质客户\n")
    r = _upload(client, tok, filename="s.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]

    # 词云图 + 数值列 → 400
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "", "图表类型": "词云图",
        "x轴": "销售额", "y轴": [], "分组字段": None, "聚合方式": "计数", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400, r.text[:200]
    assert "有效词" in r.json()["message"]

    # 桑基图 + 无分组字段 → 400
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "", "图表类型": "桑基图",
        "x轴": "地区", "y轴": ["销售额"], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400, r.text[:200]
    assert "两个分类字段" in r.json()["message"]


def test_箱线图K线图_XY同列返回400(client):
    """X 轴与 Y 轴为同一字段（单列/纯数值数据）：应 400 而非 500（重复列会触发 pandas 异常）。"""
    tok = _register(client, "xy400")
    content = "销售额\n100\n200\n300\n400\n"
    r = _upload(client, tok, filename="one.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    for ct in ("箱线图", "K线图"):
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": "", "图表类型": ct,
            "x轴": "销售额", "y轴": ["销售额"], "分组字段": None,
            "聚合方式": "求和", "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 400, f"{ct}: {r.text[:200]}"
        assert "不同字段" in r.json()["message"]

def test_上传非法后缀_400(client):
    tok = _register(client, "erin")
    r = _upload(client, tok, filename="evil.txt", content="a,b\n1,2\n")
    assert r.status_code == 400

def test_上传空文件_400(client):
    tok = _register(client, "frank")
    r = _upload(client, tok, filename="empty.csv", content="")
    assert r.status_code == 400

def test_上传非法内容_400且不残留(client):
    tok = _register(client, "grace")
    # 真正损坏的 .xlsx（非法二进制，非合法 zip/xlsx）→ 解析必然失败 → 400
    r = _upload(client, tok, filename="broken.xlsx", content=b"\x00\x01\x02PK\x03\x04this-is-not-an-xlsx")
    assert r.status_code == 400
    # 不残留：上传失败的数据集不应出现在列表中
    lst = client.get("/datasets/", headers={"Authorization": f"Bearer {tok}"})
    assert lst.status_code == 200
    assert lst.json()["数据集列表"] == []


# ---- 8.3 用户隔离 ----

def test_数据集隔离(client):
    tok_a = _register(client, "alice2")
    tok_b = _register(client, "bob2")
    r = _upload(client, tok_a)
    did = r.json()["数据集ID"]

    # B 读 A 的数据集 → 404
    r = client.get(f"/datasets/{did}", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 404
    # A 自己读 → 200
    r = client.get(f"/datasets/{did}", headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200
    # 列表隔离
    r_a = client.get("/datasets/", headers={"Authorization": f"Bearer {tok_a}"})
    r_b = client.get("/datasets/", headers={"Authorization": f"Bearer {tok_b}"})
    assert len(r_a.json()["数据集列表"]) == 1
    assert len(r_b.json()["数据集列表"]) == 0

def test_报表隔离(client):
    tok_a = _register(client, "alice3")
    tok_b = _register(client, "bob3")
    did = _upload(client, tok_a).json()["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "按地区统计"},
                    headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200
    rid = r.json()["报表ID"]

    r = client.get(f"/reports/{rid}", headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 404
    r = client.get(f"/reports/{rid}", headers={"Authorization": f"Bearer {tok_a}"})
    assert r.status_code == 200


# ---- 8.5 LLM 安全 ----

def test_非法provider_400(client):
    tok = _register(client, "hugo")
    did = _upload(client, tok).json()["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "x"},
                    headers={"Authorization": f"Bearer {tok}", "X-LLM-Provider": "evil"})
    assert r.status_code == 400

def test_非法model_400(client):
    tok = _register(client, "ivan")
    did = _upload(client, tok).json()["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "x"},
                    headers={"Authorization": f"Bearer {tok}",
                             "X-LLM-Provider": "deepseek", "X-LLM-Model": "gpt-999"})
    assert r.status_code == 400


# ---- 2. 错误响应 ----

def test_统一错误格式(client):
    # 非法参数（limit=0）→ 422 + 统一格式
    tok = _register(client, "judy")
    r = client.get("/datasets/?limit=0", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422
    body = r.json()
    assert "code" in body and "message" in body and "request_id" in body
