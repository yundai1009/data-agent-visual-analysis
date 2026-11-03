# -*- coding: utf-8 -*-
"""产品定义 v1 §5 验收标准 · 可判定测试（把文档阈值固化成 CI 断言）。

对应 `docs/产品文档/产品定义-v1.md` §5 的三项（其余各项已有既有测试覆盖，见 §7 参考资料）：
  §5.1 上传成功率   —— 宽表（200 列）上传：HTTP 200、列数保真、0 个 500（50MB 边界/路径
                       穿越/无残留 已在 test_修复上传边界与文件名.py、test_api_integration.py 覆盖）
  §5.2 一句话出图   —— 30 条黄金样本（18 种图表矩阵 + 12 条高频口语/变体）在**规则路径**
                      命中率 ≥90%（文档阈值；阶段九十R? 实测 30/30=100%）
  §5.6 分享/导出    —— 分享密码失败限频：10 分钟 10 次失败 → 第 11 次 429，且按 share
                      维度生效（正确密码在超限后仍 429）
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

_SENT: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("v1_acceptance")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True

    from services import email_service

    def _fake_send(email: str, code: str) -> bool:
        _SENT[email] = code
        return True

    _orig = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake_send
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            yield c
    finally:
        email_service.发送验证码邮件 = _orig


def _register(client, username, password="secret123", email=None):
    email = email or f"{username}@test.com"
    client.post("/auth/send-code", json={"email": email})
    code = _SENT.get(email)
    assert code, f"未捕获 {email} 验证码"
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


def _generate(client, token, did, 需求, **over):
    payload = {
        "数据集ID": did, "分析需求": 需求, "图表类型": "自动推荐",
        "x轴": None, "y轴": [], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    }
    payload.update(over)
    return client.post("/reports/generate", json=payload, headers={"Authorization": f"Bearer {token}"})


# ═══ §5.1 宽表（200 列）上传 ═══


def test_验收51_宽表200列_上传成功且列数保真(client):
    """20 个不同结构文件之一：200 列宽表。上传应 200、列数保真、0 个 500。"""
    tok = _register(client, "v1wide")
    列 = [f"指标{i}" for i in range(199)] + ["地区"]
    行 = ["华东", "华南", "华北"]
    csv = ",".join(列) + "\n" + "\n".join(
        ",".join([str(i * 3 + j) for i in range(199)] + [行[j]]) for j in range(3)
    )
    r = _upload(client, tok, "宽表.csv", csv)
    assert r.status_code == 200, r.text[:300]
    项 = r.json()["上传成功"][0]
    assert 项["列数"] == 200, f"列数应保真 200，实际 {项['列数']}"
    assert 项["行数"] == 3
    画像 = 项["数据画像"]
    assert "地区" in 画像.get("分类字段", []), 画像.get("分类字段")
    assert len(画像.get("数值字段", [])) == 199, len(画像.get("数值字段", []))
    # 无 500：再次确认列表可读
    lst = client.get("/datasets", headers={"Authorization": f"Bearer {tok}"})
    assert lst.status_code == 200


# ═══ §5.2 30 条黄金样本 ≥90% ═══

# 18 种图表矩阵（与 test_api_integration._18图表矩阵 同源）+ 12 条高频口语/变体。
# 期望 = 规则路径实际产出（阶段九十R? 实测 30/30，已核对字段语义）。
_黄金30 = [
    # (语句, 图表类型, x轴(可为None), y轴含(可为None), 分组(可为None))
    ("生成柱状图", "柱状图", "地区", "销售额", None),
    ("按地区用柱状图", "柱状图", "地区", "销售额", None),
    ("折线图看趋势", "折线图", "日期", "销售额", None),
    ("销售额的变化情况", "折线图", "日期", "销售额", None),
    ("面积图", "面积图", "日期", "销售额", None),
    ("饼图占比", "饼图", "地区", "销售额", None),
    ("各渠道销售额构成", "饼图", "渠道", "销售额", None),
    ("地区销售额占比", "饼图", "地区", "销售额", None),
    ("环形图", "环形图", "地区", "销售额", None),
    ("甜甜圈图", "环形图", "地区", "销售额", None),
    ("直方图看分布", "直方图", "销售额", "记录数", None),
    ("销售额分布情况", "直方图", "销售额", "记录数", None),
    ("散点图看关系", "散点图", "销售额", "订单数", None),
    ("销售额和订单数的相关性", "散点图", "销售额", "订单数", None),
    ("箱线图看异常", "箱线图", "地区", "销售额", None),
    ("K线图看行情", "K线图", "日期", "销售额", None),
    ("雷达图", "雷达图", "地区", "销售额", None),
    ("热力图看交叉", "热力图", "地区", "销售额", "渠道"),
    ("堆积柱状图", "堆积柱状图", "地区", "销售额", "渠道"),
    ("漏斗图看转化", "漏斗图", "地区", "销售额", None),
    ("瀑布图", "瀑布图", "地区", "销售额", None),
    ("桑基图看流向", "桑基图", "地区", None, "渠道"),
    ("旭日图", "旭日图", "地区", None, "渠道"),
    ("生成词云图", "词云图", "评论", None, None),
    # —— 12 条高频口语/变体（0 基础用户真实句法，非显式图表名）——
    ("按地区统计销售额", "柱状图", "地区", "销售额", None),
    ("各地区销售额比较", "柱状图", "地区", "销售额", None),
    ("对比各渠道销售额", "柱状图", "渠道", "销售额", None),
    ("按地区统计订单数量", "柱状图", "地区", "订单数", None),
    ("地区之间的销售额差异", "柱状图", "地区", "销售额", None),
    ("销售额趋势", "折线图", "日期", "销售额", None),
]

# 文档 §5.2 通过线：30 条中命中 ≥90%（≥27 条），且 0 个 HTTP 500。
_验收52_通过线 = 27


def test_验收52_黄金样本30条_命中率不低于90(client):
    """§5.2：30 条代表性语句在规则路径命中「正确图表类型+正确字段」≥90%。"""
    tok = _register(client, "v1golden")
    内容 = (
        "地区,渠道,销售额,订单数,日期,评论\n"
        "华东,线上,100,10,2024-01-01,这个产品非常好用强烈推荐\n"
        "华东,线下,200,20,2024-01-02,产品性价比很高很好用\n"
        "华南,线上,300,30,2024-01-03,推荐给朋友都说好\n"
        "华南,线下,150,15,2024-01-04,包装很精美质量很好\n"
        "华北,线上,80,8,2024-01-05,客服态度很好解决问题快\n"
    )
    r = _upload(client, tok, "golden.csv", 内容)
    assert r.status_code == 200, r.text[:300]
    did = r.json()["上传成功"][0]["数据集ID"]

    命中, 失败 = 0, []
    for 语句, ct, x, y, grp in _黄金30:
        r = _generate(client, tok, did, 语句)
        if r.status_code != 200:
            失败.append(f"{语句}: HTTP {r.status_code} {r.text[:120]}")
            continue
        body = r.json()
        配置 = body.get("图表配置") or {}
        if body["图表类型"] != ct:
            失败.append(f"{语句}: 图表类型 {body['图表类型']} != {ct}")
            continue
        if x and 配置.get("X轴") != x:
            失败.append(f"{语句}: X轴 {配置.get('X轴')} != {x}")
            continue
        if y and y not in (配置.get("Y轴") or []):
            失败.append(f"{语句}: Y轴 {配置.get('Y轴')} 不含 {y}")
            continue
        if grp and (配置.get("颜色") or 配置.get("分组字段")) != grp:
            失败.append(f"{语句}: 分组 {配置.get('颜色') or 配置.get('分组字段')} != {grp}")
            continue
        命中 += 1

    断言 = f"§5.2 黄金样本命中 {命中}/{len(_黄金30)}（通过线 ≥{_验收52_通过线}）"
    断言 += ("\n" + "\n".join(失败)) if 失败 else ""
    assert 命中 >= _验收52_通过线, 断言


# ═══ §5.6 分享密码失败限频 ═══


@pytest.fixture(autouse=True)
def _清空分享限频():
    """每个用例前清空模块级 _pwd_fails，避免跨用例污染（限频是进程内固定窗口）。"""
    from api.routes import shares as _shares
    _shares._pwd_fails.clear()
    yield
    _shares._pwd_fails.clear()


def test_验收56_分享密码失败限频_第11次429且按share生效(client):
    """§5.6：10 次错密码 401 → 第 11 次 429；超限后即使密码正确仍 429（按 share 维度）。"""
    tok = _register(client, "v1share")
    did = _upload(client, tok).json()["上传成功"][0]["数据集ID"]
    h = {"Authorization": f"Bearer {tok}"}
    r = _generate(client, tok, did, "按地区统计")
    rid = r.json()["报表ID"]
    r = client.post(f"/reports/{rid}/share?密码=pw123456", headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["链接ID"]

    状态 = [client.get(f"/share-data/{sid}", headers={"X-Share-Password": "wrongpw"}).status_code for _ in range(11)]
    assert 状态[:10] == [401] * 10, f"前 10 次应 401（密码错误），实际 {状态[:10]}"
    assert 状态[10] == 429, f"第 11 次应 429（限频），实际 {状态[10]}"

    # 超限后正确密码也应 429（窗口内按 share 维度锁定）
    r = client.get(f"/share-data/{sid}?password=pw123456")
    assert r.status_code == 429, r.text

    # 另一个无密码分享不受影响（限频按 share_id 隔离）
    r2 = client.post(f"/reports/{rid}/share", headers=h)
    sid2 = r2.json()["链接ID"]
    assert client.get(f"/share-data/{sid2}").status_code == 200
