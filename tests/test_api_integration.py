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


def test_文本字段识别与词云自然语言自动选字段(client):
    """画像识别文本字段；输入"生成词云图"自动选文本字段，零手动。"""
    tok = _register(client, "nlauto")
    content = ("地区,销售额,评论\n"
               "华东,100,这个产品非常好用强烈推荐\n"
               "华南,200,产品性价比很高很好用\n"
               "华北,150,推荐给朋友都说好\n")
    r = _upload(client, tok, filename="d.csv", content=content)
    assert r.status_code == 200, r.text
    profile = r.json()["数据画像"]
    assert "评论" in profile.get("文本字段", []), profile.get("文本字段")
    did = r.json()["数据集ID"]
    # 自然语言生成词云 → 自动选"评论"
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "生成词云图", "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "计数", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["图表类型"] == "词云图"
    assert body["图表配置"]["X轴"] == "评论"
    assert len(body["报表数据"]) > 0


def test_旭日不被占比关键词抢先(client):
    """"多层占比旭日图" 含"占比"也应命中旭日图（具体图表词优先）。"""
    tok = _register(client, "sunburstnl")
    content = ("地区,渠道,销售额\n华东,线上,100\n华东,线下,200\n华南,线上,300\n华南,线下,150\n华北,线上,80\n")
    r = _upload(client, tok, filename="d.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "多层占比旭日图", "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "计数", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text[:200]
    assert r.json()["图表类型"] == "旭日图"


def test_折线K线自然语言自动用日期(client):
    """趋势/K线类自然语言需求：X 轴自动选日期字段。"""
    tok = _register(client, "datenl")
    content = ("地区,销售额,日期\n华东,100,2024-01-01\n华南,200,2024-01-02\n"
               "华北,150,2024-01-03\n华东,120,2024-01-04\n")
    r = _upload(client, tok, filename="d.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    for req, expected_ct, expected_x in [
        ("按日期看销售额趋势", "折线图", "日期"),
        ("按日期看销售额K线", "K线图", "日期"),
    ]:
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": req, "图表类型": "自动推荐",
            "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, f"{req}: {r.text[:200]}"
        body = r.json()
        assert body["图表类型"] == expected_ct, req
        assert body["图表配置"]["X轴"] == expected_x, req


def test_词云单列数值_400提示(client):
    """仅数值列的数据集生成词云：400 明确提示（换文本字段），而非 500。"""
    tok = _register(client, "notext")
    content = "销售额\n100\n200\n300\n"
    r = _upload(client, tok, filename="one.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "", "图表类型": "词云图",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "计数", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400, r.text[:200]
    assert "文本字段" in r.json()["message"]


def test_字段模板不误设分组(client):
    """【字段】显式指定时：非分组类图表（饼图）不应把第二个字段设成分组，避免 pandas 列冲突 400。"""
    tok = _register(client, "tplate")
    content = ("地区,渠道,销售额,日期\n"
               "华东,线上,100,2024-01-01\n"
               "华南,线下,200,2024-01-02\n"
               "华北,线上,150,2024-01-03\n")
    r = _upload(client, tok, filename="d.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    # 占比 → 饼图：y=销售额，分组必须为 None（否则 groupby 重复列报错）
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "按【地区】看【销售额】占比", "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text[:200]
    assert r.json()["图表类型"] == "饼图"
    # 交叉分析 → 热力图：第二个字段（分类）作分组字段
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "按【地区】和【渠道】做【销售额】交叉分析", "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text[:200]
    assert r.json()["图表类型"] == "热力图"


def test_BYOK用户Key优先于服务端(client):
    """服务端 Key 为占位符时，用户传 X-LLM-API-Key 仍能启用 LLM，且用用户 Key。"""
    import 后端_核心.agent.编排器 as orc_mod
    captured = {}
    orig_cc = orc_mod.chat_completion

    def fake_chat(messages, **kw):
        captured["llm_config"] = kw.get("llm_config")
        return None  # LLM 失败 → 规则兜底，报表仍生成

    orc_mod.chat_completion = fake_chat
    try:
        tok = _register(client, "byok")
        content = "地区,销售额\n华东,100\n华南,200\n华北,150\n"
        r = _upload(client, tok, filename="d.csv", content=content)
        assert r.status_code == 200, r.text
        did = r.json()["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": "各地区销售额对比", "图表类型": "自动推荐",
            "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {tok}", "X-LLM-API-Key": "sk-user-123"})
        assert r.status_code == 200, r.text[:200]
        # 修复前此处 captured 为空（服务端 Key 占位符时 LLM 不启用）；修复后用户 Key 有效 → 启用
        assert captured.get("llm_config") is not None
        assert captured["llm_config"].api_key == "sk-user-123"
    finally:
        orc_mod.chat_completion = orig_cc


def test_BYOK不填Key回退服务端(client):
    """不带 X-LLM-API-Key → 用服务端 Key（模拟服务端已配真 Key）。"""
    import 后端_核心.agent.编排器 as orc_mod
    from config.settings import EnvConfig
    captured = {}
    orig_cc = orc_mod.chat_completion
    orig_key = EnvConfig.LLM_API_KEY
    EnvConfig.LLM_API_KEY = "sk-server-real"  # 模拟服务端配置了真 Key

    def fake_chat(messages, **kw):
        captured["llm_config"] = kw.get("llm_config")
        return None

    orc_mod.chat_completion = fake_chat
    try:
        tok = _register(client, "byok2")
        content = "地区,销售额\n华东,100\n华南,200\n"
        r = _upload(client, tok, filename="d.csv", content=content)
        did = r.json()["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": "各地区销售额对比", "图表类型": "自动推荐",
            "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text[:200]
        assert captured.get("llm_config") is not None
        assert captured["llm_config"].api_key == "sk-server-real"
    finally:
        orc_mod.chat_completion = orig_cc
        EnvConfig.LLM_API_KEY = orig_key

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


def test_报表导出(client):
    """导出端点：xlsx / csv / pdf 均返回附件流，非法 format 422，跨用户 404。"""
    tok = _register(client, "exporter1")
    did = _upload(client, tok).json()["数据集ID"]
    r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "按地区统计"},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    rid = r.json()["报表ID"]
    h = {"Authorization": f"Bearer {tok}"}

    for fmt, ctype in [("xlsx", "spreadsheetml"), ("csv", "text/csv"), ("pdf", "application/pdf")]:
        r = client.get(f"/reports/{rid}/export?format={fmt}", headers=h)
        assert r.status_code == 200, f"{fmt}: {r.text[:200]}"
        assert ctype in r.headers["content-type"], f"{fmt}: {r.headers['content-type']}"
        assert r.content, f"{fmt}: 导出内容为空"
        assert "filename" in r.headers["content-disposition"]

    # 非法 format → 422
    r = client.get(f"/reports/{rid}/export?format=docx", headers=h)
    assert r.status_code == 422

    # 跨用户导出 → 404（走报表归属校验）
    tok_b = _register(client, "exporter2")
    r = client.get(f"/reports/{rid}/export?format=xlsx",
                   headers={"Authorization": f"Bearer {tok_b}"})
    assert r.status_code == 404


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


# ---- 10. 账号级 LLM Key（BYOK 后端存储）----

def test_账号key_保存与状态(client):
    """PUT /auth/llm-key 保存 → GET 返回 has_key + 脱敏 masked（不回明文）。"""
    tok = _register(client, "keyacct1")
    h = {"Authorization": f"Bearer {tok}"}
    r = client.put("/auth/llm-key", json={"api_key": "sk-account-12345678"}, headers=h)
    assert r.status_code == 200, r.text
    r = client.get("/auth/llm-key", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["has_key"] is True
    assert body["masked"] == "sk-…5678"
    assert "sk-account" not in str(body), "不应返回明文 key"


def test_账号key_空值400(client):
    tok = _register(client, "keyacct2")
    r = client.put("/auth/llm-key", json={"api_key": "  "}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 400


def test_账号key_报表生成自动回退(client):
    """无 X-LLM-API-Key 请求头时，报表生成自动使用账号绑定的 key。"""
    import 后端_核心.agent.编排器 as orc_mod
    captured = {}
    orig_cc = orc_mod.chat_completion

    def fake_chat(messages, **kw):
        captured["llm_config"] = kw.get("llm_config")
        return None

    orc_mod.chat_completion = fake_chat
    try:
        tok = _register(client, "keyacct3")
        client.put("/auth/llm-key", json={"api_key": "sk-account-abcdef"}, headers={"Authorization": f"Bearer {tok}"})
        did = _upload(client, tok).json()["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": "各地区销售额对比", "图表类型": "自动推荐",
            "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {tok}"})  # 不带 X-LLM-API-Key
        assert r.status_code == 200, r.text[:200]
        assert captured.get("llm_config") is not None, "应触发 LLM 链路"
        assert captured["llm_config"].api_key == "sk-account-abcdef", "应使用账号绑定的 key"
    finally:
        orc_mod.chat_completion = orig_cc


def test_账号key_请求头优先于账号(client):
    """显式 X-LLM-API-Key 优先于账号绑定的 key。"""
    import 后端_核心.agent.编排器 as orc_mod
    captured = {}
    orig_cc = orc_mod.chat_completion

    def fake_chat(messages, **kw):
        captured["llm_config"] = kw.get("llm_config")
        return None

    orc_mod.chat_completion = fake_chat
    try:
        tok = _register(client, "keyacct4")
        client.put("/auth/llm-key", json={"api_key": "sk-account-111111"}, headers={"Authorization": f"Bearer {tok}"})
        did = _upload(client, tok).json()["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": "各地区销售额对比", "图表类型": "自动推荐",
            "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {tok}", "X-LLM-API-Key": "sk-browser-222222"})
        assert r.status_code == 200, r.text[:200]
        assert captured["llm_config"].api_key == "sk-browser-222222", "请求头 key 应优先"
    finally:
        orc_mod.chat_completion = orig_cc


def test_账号key_清除与用户隔离(client):
    """DELETE 清除后回退服务端；A 的 key 不影响 B。"""
    import 后端_核心.agent.编排器 as orc_mod
    captured = {}
    orig_cc = orc_mod.chat_completion

    def fake_chat(messages, **kw):
        captured["llm_config"] = kw.get("llm_config")
        return None

    orc_mod.chat_completion = fake_chat
    try:
        tok_a = _register(client, "keyacct5")
        tok_b = _register(client, "keyacct6")
        client.put("/auth/llm-key", json={"api_key": "sk-account-333333"}, headers={"Authorization": f"Bearer {tok_a}"})
        # A 清除后回退服务端 .env（空 → 无 key）
        r = client.delete("/auth/llm-key", headers={"Authorization": f"Bearer {tok_a}"})
        assert r.status_code == 200
        r = client.get("/auth/llm-key", headers={"Authorization": f"Bearer {tok_a}"})
        assert r.json()["has_key"] is False
        # B 未配置 → has_key False（隔离）
        r = client.get("/auth/llm-key", headers={"Authorization": f"Bearer {tok_b}"})
        assert r.json()["has_key"] is False
    finally:
        orc_mod.chat_completion = orig_cc


# ---- 11. 字段意图自动选择（时间类需求）----

def test_工作时间占比_自动选中时间字段(client):
    """需求含"工作时间"时，规则匹配应选中工作时间字段而非默认首个分类字段。"""
    tok = _register(client, "wt1")
    content = "地点,工作时间,职位ID\n武汉,8,101\n上海,10,102\n北京,6,103\n"
    r = _upload(client, tok, filename="wt.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "工作时间占比", "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["图表类型"] == "饼图", f"应选饼图，实际 {body['图表类型']}"
    assert body["图表配置"]["X轴"] == "工作时间", f"X 轴应为工作时间，实际 {body['图表配置']['X轴']}"


def test_数据画像摘要_含字段示例值():
    """治本：喂给 LLM 的画像摘要必须含字段真实示例值（LLM 据此理解字段语义）。"""
    import pandas as pd
    from 后端_核心.agent.执行器注册 import _可读画像摘要
    df = pd.DataFrame({"地点": ["武汉", "上海", "北京"], "工作时间": [8, 10, 6], "职位ID": [101, 102, 103]})
    画像 = {
        "行数": 3, "列数": 3,
        "字段列表": ["地点", "工作时间", "职位ID"],
        "数值字段": ["工作时间", "职位ID"],
        "日期字段": [], "分类字段": ["地点"],
        "数据质量": {"评级": "良好", "等级说明": ""},
    }
    summary = _可读画像摘要(画像, df)
    assert "工作时间: 8, 10, 6" in summary, f"画像应含工作时间示例值: {summary}"
    assert "地点: 武汉, 上海, 北京" in summary, f"画像应含地点示例值: {summary}"


def test_工作经验占比_优先经验字段而非时间(client):
    """需求"工作经验要求占比图"且数据同时含工作经验/时间字段时，
    必须选"工作经验"字段（需求文本中明确提到的词优先），而非"时间"。"""
    tok = _register(client, "exp1")
    content = ("工作经验,时间,地点\n"
               "1-2年,2025年09月22日,武汉\n"
               "2-3年,2025年09月21日,上海\n"
               "无经验,2025年09月20日,北京\n")
    r = _upload(client, tok, filename="exp.csv", content=content)
    assert r.status_code == 200, r.text
    did = r.json()["数据集ID"]
    r = client.post("/reports/generate", json={
        "数据集ID": did, "分析需求": "工作经验要求占比图", "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["图表类型"] == "饼图", f"应选饼图，实际 {body['图表类型']}"
    assert body["图表配置"]["X轴"] == "工作经验", f"X 轴应为工作经验，实际 {body['图表配置']['X轴']}"


def test_LLM失败原因_透传到报表(client):
    """LLM 调用失败（如 402 欠费）时，报表响应必须带 LLM失败原因，前端可明示。"""
    import 后端_核心.agent.llm客户端 as llm_mod
    import 后端_核心.agent.编排器 as orc_mod
    orig_cc = orc_mod.chat_completion

    def fake_chat(messages, **kw):
        llm_mod._record_llm_fail("LLM 调用失败：LLM 账号欠费或额度用尽（HTTP 402），请到服务商平台充值")
        return None

    orc_mod.chat_completion = fake_chat
    try:
        tok = _register(client, "llmfail1")
        # 账号配 key（非占位符）→ 触发 LLM 链路 → fake 记录 402 失败 → 降级规则
        client.put("/auth/llm-key", json={"api_key": "sk-llm-fail-12345678"}, headers={"Authorization": f"Bearer {tok}"})
        did = _upload(client, tok).json()["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": "各地区销售额占比", "图表类型": "自动推荐",
            "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
        }, headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        assert body["意图来源"] == "规则", f"LLM 失败应降级规则，实际 {body['意图来源']}"
        assert body["LLM失败原因"], "应透传 LLM 失败原因"
        assert "402" in body["LLM失败原因"], f"失败原因应含 402，实际 {body['LLM失败原因']}"
    finally:
        orc_mod.chat_completion = orig_cc


# ---- 12. 自定义 LLM 供应商（阶段 13.6）----

def test_自定义供应商_保存列表删除(client):
    """POST 保存自定义供应商 → GET 列表含自定义（Key 脱敏）→ DELETE 移除。"""
    tok = _register(client, "custp1")
    h = {"Authorization": f"Bearer {tok}"}
    r = client.post("/auth/llm-providers/custom", json={
        "name": "myproxy", "base_url": "https://api.myproxy.com/v1",
        "api_key": "sk-myproxy-12345678", "models": ["m1", "m2"], "default": "m1",
    }, headers=h)
    assert r.status_code == 200, r.text
    r = client.get("/auth/llm-providers", headers=h)
    assert r.status_code == 200
    body = r.json()
    custom = [p for p in body["providers"] if p.get("custom")]
    assert len(custom) == 1, f"应有 1 个自定义供应商: {custom}"
    assert custom[0]["id"] == "myproxy"
    assert custom[0]["base_url"] == "https://api.myproxy.com/v1"
    assert "sk-myproxy" not in str(body), "不应下发明文 Key"
    # 删除
    r = client.delete("/auth/llm-providers/custom/myproxy", headers=h)
    assert r.status_code == 200
    r = client.get("/auth/llm-providers", headers=h)
    assert len([p for p in r.json()["providers"] if p.get("custom")]) == 0


def test_自定义供应商_生成报表不报400(client):
    """使用自定义供应商生成报表：不再因"不支持的 provider"报 400。"""
    import 后端_核心.agent.编排器 as orc_mod
    orig_cc = orc_mod.chat_completion
    orc_mod.chat_completion = lambda messages, **kw: None  # LLM 失败降级规则
    try:
        tok = _register(client, "custp2")
        h = {"Authorization": f"Bearer {tok}"}
        client.post("/auth/llm-providers/custom", json={
            "name": "myproxy", "base_url": "https://api.myproxy.com/v1",
            "api_key": "sk-myproxy-abcdef", "models": ["m1"], "default": "m1",
        }, headers=h)
        did = _upload(client, tok).json()["数据集ID"]
        r = client.post("/reports/generate", json={
            "数据集ID": did, "分析需求": "各地区销售额占比", "图表类型": "自动推荐",
            "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
        }, headers={**h, "X-LLM-Provider": "myproxy", "X-LLM-Model": "m1"})
        assert r.status_code == 200, f"自定义供应商生成应成功，实际 {r.status_code}: {r.text[:200]}"
    finally:
        orc_mod.chat_completion = orig_cc


# ---- 13. 修改密码 ----

def test_修改密码_成功与旧密码校验(client):
    """改密成功 → 旧密码登录失败、新密码登录成功；旧密码错误 → 400。"""
    tok = _register(client, "pw1")
    h = {"Authorization": f"Bearer {tok}"}
    # 旧密码错误
    r = client.post("/auth/change-password", json={"old_password": "wrong-old", "new_password": "newpass123"}, headers=h)
    assert r.status_code == 400, r.text
    # 正确修改
    r = client.post("/auth/change-password", json={"old_password": "secret123", "new_password": "newpass123"}, headers=h)
    assert r.status_code == 200, r.text
    # 旧密码不能再登录
    r = client.post("/auth/login", json={"username": "pw1", "password": "secret123"})
    assert r.status_code == 401
    # 新密码可登录
    r = client.post("/auth/login", json={"username": "pw1", "password": "newpass123"})
    assert r.status_code == 200


# ---- 14. 数据洞察 + 数据集管理 ----

def test_数据画像_自动洞察存在(client):
    """上传含异常值/相关性/分布的数据 → 画像含自动洞察。"""
    tok = _register(client, "ins1")
    content = ("地区,销售额,利润\n"
               "华东,100,10\n华东,110,12\n华东,95,9\n华东,9999,500\n"  # 9999 为异常值
               "华南,200,20\n华南,210,21\n华北,150,15\n")
    r = _upload(client, tok, filename="ins.csv", content=content)
    assert r.status_code == 200, r.text
    画像 = r.json()["数据画像"]
    assert "自动洞察" in 画像, "画像应含自动洞察"
    assert len(画像["自动洞察"]) > 0, "应至少一条洞察"


def test_数据集_重命名与删除(client):
    """PATCH 重命名 → 列表更新；DELETE 删除 → 列表移除。"""
    tok = _register(client, "ds1")
    h = {"Authorization": f"Bearer {tok}"}
    did = _upload(client, tok).json()["数据集ID"]
    # 重命名
    r = client.patch(f"/datasets/{did}", json={"文件名": "我的销售数据"}, headers=h)
    assert r.status_code == 200, r.text
    r = client.get("/datasets/", headers=h)
    item = next((d for d in r.json()["数据集列表"] if d["数据集ID"] == did), None)
    assert item and item["文件名"] == "我的销售数据", "重命名应生效"
    # 删除
    r = client.delete(f"/datasets/{did}", headers=h)
    assert r.status_code == 200, r.text
    r = client.get("/datasets/", headers=h)
    assert all(d["数据集ID"] != did for d in r.json()["数据集列表"]), "删除后列表应移除"
    # 他人不可删
    tok2 = _register(client, "ds2")
    r = client.delete(f"/datasets/{did}", headers={"Authorization": f"Bearer {tok2}"})
    assert r.status_code == 404


def test_修改用户名_唯一性校验(client):
    """改用户名成功；新用户名可登录；与现有账号冲突 → 400。"""
    tok_a = _register(client, "un_a")
    tok_b = _register(client, "un_b")
    h_b = {"Authorization": f"Bearer {tok_b}"}
    # 与已有账号 un_a 冲突
    r = client.post("/auth/change-username", json={"username": "un_a"}, headers=h_b)
    assert r.status_code == 400, r.text
    # 成功修改
    r = client.post("/auth/change-username", json={"username": "renamed_b"}, headers=h_b)
    assert r.status_code == 200, r.text
    # 新用户名可登录
    r = client.post("/auth/login", json={"username": "renamed_b", "password": "secret123"})
    assert r.status_code == 200
    # 旧用户名不可再用
    r = client.post("/auth/login", json={"username": "un_b", "password": "secret123"})
    assert r.status_code == 401


# ---- 9. 分析直播（SSE） ----

def _parse_sse(body: str):
    """把 SSE 响应体解析为事件 dict 列表。"""
    import json as _json
    events = []
    for line in body.splitlines():
        if line.startswith("data: "):
            events.append(_json.loads(line[6:]))
    return events


def test_generate_stream_事件流与持久化(client):
    """分析直播：SSE 流返回 step 决策事件 + done 事件，报表已持久化可读。"""
    tok = _register(client, "stream1")
    content = "地区,销售额\n华东,100\n华南,200\n华北,150\n"
    r = _upload(client, tok, filename="s.csv", content=content)
    did = r.json()["数据集ID"]
    r = client.post("/reports/generate-stream", json={
        "数据集ID": did, "分析需求": "各地区销售额对比", "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text[:300]
    assert "text/event-stream" in r.headers.get("content-type", "")
    events = _parse_sse(r.text)
    types = [ev["type"] for ev in events]
    assert types[-1] == "done", f"最后一条应为 done，实际: {types}"
    assert "step" in types, f"应至少有一条 step 决策事件，实际: {types}"
    rid = events[-1]["报表ID"]
    # 报表已持久化，可直接读取
    r = client.get(f"/reports/{rid}", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["报表ID"] == rid


def test_generate_stream_未认证401(client):
    r = client.post("/reports/generate-stream", json={"数据集ID": "x", "分析需求": "y"})
    assert r.status_code == 401


def test_generate_stream_非法provider400(client):
    tok = _register(client, "stream2")
    did = _upload(client, tok).json()["数据集ID"]
    r = client.post("/reports/generate-stream", json={"数据集ID": did, "分析需求": "x"},
                    headers={"Authorization": f"Bearer {tok}", "X-LLM-Provider": "evil"})
    assert r.status_code == 400


def test_generate_stream_生成失败走error事件(client):
    """桑基图缺分组字段 → 生成抛 ValueError → SSE error 事件（HTTP 仍 200）。"""
    tok = _register(client, "stream3")
    content = "地区,销售额\n华东,100\n华南,200\n"
    r = _upload(client, tok, filename="s.csv", content=content)
    did = r.json()["数据集ID"]
    r = client.post("/reports/generate-stream", json={
        "数据集ID": did, "分析需求": "", "图表类型": "桑基图",
        "x轴": "地区", "y轴": ["销售额"], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1]["type"] == "error"
    assert events[-1]["message"]
