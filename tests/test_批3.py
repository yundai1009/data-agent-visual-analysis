"""阶段 31 批次 3 测试：协作者分享 + 收藏 + 数据集管理 + 历史归档，不依赖网络与 LLM key。

覆盖目标
========
- 协作者：空白名单=公开；指定协作者=仅名单内登录用户可看
- 收藏：切换（幂等）、is_favorited 列表标记、favorites=1 过滤
- 数据集列表：q 搜索、sort 排序、统计返回
- 报表列表：q 标题搜索、chart_type 过滤、favorites 过滤
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("batch3_test")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True
    from 后端_核心.存储.sqlite_repo import 初始化数据库
    初始化数据库()
    from services import email_service

    def _fake(email, code):
        _SENT_CODES[email] = code

    _orig = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake
    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as c:
            yield c
    finally:
        email_service.发送验证码邮件 = _orig


def _reg(client, uname):
    email = f"{uname}@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200
    code = _SENT_CODES[email]
    r = client.post("/auth/register", json={"username": uname, "email": email, "code": code, "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _upload_and_report(client, tok, name="t.csv"):
    r = client.post("/datasets/upload",
                    files={"file": (name, "地区,销售额\n华东,100\n华南,200\n", "text/csv")},
                    headers=_h(tok))
    assert r.status_code == 200, r.text
    ds = r.json()["数据集ID"]
    r = client.post("/reports/generate",
                    json={"数据集ID": ds, "分析需求": "按地区统计销售额", "图表类型": "柱状图",
                          "x轴": "地区", "y轴": ["销售额"], "聚合方式": "求和"},
                    headers=_h(tok))
    assert r.status_code == 200, r.text
    return r.json()["报表ID"]


class Test协作者分享:
    def test_空白名单_公开(self, client):
        t_a = _reg(client, "share_a")
        rid = _upload_and_report(client, t_a)
        # 无协作者 → 未登录也可看
        r = client.post(f"/reports/{rid}/share", headers=_h(t_a))
        sid = r.json()["链接ID"]
        assert client.get(f"/share-data/{sid}").status_code == 200

    def test_指定协作者_仅名单内(self, client):
        t_a = _reg(client, "share_c")
        t_b = _reg(client, "share_b")
        rid = _upload_and_report(client, t_a)
        r = client.post(f"/reports/{rid}/share?协作者=share_b", headers=_h(t_a))
        sid = r.json()["链接ID"]
        assert r.json()["协作者"] == ["share_b"]
        # 未登录 → 401
        assert client.get(f"/share-data/{sid}").status_code == 401
        # 非协作者（创建者自己，不在白名单）→ 401
        assert client.get(f"/share-data/{sid}", headers=_h(t_a)).status_code == 401
        # 协作者 B → 200
        assert client.get(f"/share-data/{sid}", headers=_h(t_b)).status_code == 200


class Test收藏:
    def test_切换收藏_幂等(self, client):
        t = _reg(client, "fav")
        rid = _upload_and_report(client, t)
        # 收藏
        r = client.put(f"/reports/{rid}/favorite", headers=_h(t))
        assert r.status_code == 200
        assert r.json()["is_favorited"] is True
        # 取消
        r = client.put(f"/reports/{rid}/favorite", headers=_h(t))
        assert r.json()["is_favorited"] is False
        # 再次收藏
        r = client.put(f"/reports/{rid}/favorite", headers=_h(t))
        assert r.json()["is_favorited"] is True

    def test_列表带is_favorited(self, client):
        t = _reg(client, "fav2")
        rid = _upload_and_report(client, t)
        client.put(f"/reports/{rid}/favorite", headers=_h(t))
        r = client.get("/reports/", headers=_h(t))
        items = r.json()["报表列表"]
        assert items[0]["is_favorited"] is True

    def test_favorites过滤(self, client):
        t = _reg(client, "fav3")
        rid = _upload_and_report(client, t)
        r = client.get("/reports/?favorites=1", headers=_h(t))
        assert len(r.json()["报表列表"]) == 0  # 未收藏 → 空
        client.put(f"/reports/{rid}/favorite", headers=_h(t))
        r = client.get("/reports/?favorites=1", headers=_h(t))
        assert len(r.json()["报表列表"]) == 1


class Test数据集管理:
    def test_搜索_排序_统计(self, client):
        t = _reg(client, "dssearch")
        _upload_and_report(client, t, "sales.csv")
        _upload_and_report(client, t, "log.csv")
        h = _h(t)
        # 统计
        r = client.get("/datasets/", headers=h)
        stats = r.json()["统计"]
        assert stats["总数"] >= 2
        assert stats["总行数"] >= 4
        # 搜索
        r = client.get("/datasets/?q=sales", headers=h)
        names = [d["文件名"] for d in r.json()["数据集列表"]]
        assert all("sales" in n for n in names)
        # 排序：行数最多在前
        r = client.get("/datasets/?sort=rows_desc", headers=h)
        rows_list = [d["行数"] for d in r.json()["数据集列表"]]
        assert rows_list == sorted(rows_list, reverse=True)


class Test历史归档:
    def test_搜索_图表类型过滤(self, client):
        t = _reg(client, "hist")
        _upload_and_report(client, t)
        r = client.get("/reports/?q=不存在", headers=_h(t))
        assert len(r.json()["报表列表"]) == 0
        r = client.get("/reports/?chart_type=柱状图", headers=_h(t))
        assert len(r.json()["报表列表"]) >= 1
        r = client.get("/reports/?chart_type=不存在", headers=_h(t))
        assert len(r.json()["报表列表"]) == 0
