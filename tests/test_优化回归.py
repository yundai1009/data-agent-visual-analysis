# -*- coding: utf-8 -*-
"""优化功能回归测试：merge / rows 分页 / 分享浏览次数 / 清洗另存 / 定时失败查询。"""
from __future__ import annotations

import os
import sys
import time

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

os.environ.setdefault("AUTH_ENABLED", "true")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("SEED_ADMIN_PASSWORD", "test-admin-password")

from fastapi.testclient import TestClient

from api.main import app

_SENT: dict = {}


@pytest.fixture
def client(monkeypatch):
    from services import email_service
    monkeypatch.setattr(email_service, "发送验证码邮件", lambda mail, code: _SENT.__setitem__(mail, code))
    with TestClient(app) as c:
        yield c


def _register(client: TestClient, tag: str) -> str:
    uname = f"{tag}{int(time.time()) % 100000}"
    email = f"{uname}@test.com"
    assert client.post("/auth/send-code", json={"email": email}).status_code == 200
    code = _SENT.get(email)
    assert code
    r = client.post("/auth/register", json={"username": uname, "email": email, "code": code, "password": "secret123"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _upload(client: TestClient, tok: str, name: str, content: str) -> str:
    r = client.post("/datasets/upload", headers={"Authorization": f"Bearer {tok}"},
                    files={"file": (name, content.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["上传成功"][0]["数据集ID"]


def _gen_report(client: TestClient, tok: str, did: str) -> str:
    r = client.post("/reports/generate", headers={"Authorization": f"Bearer {tok}"}, json={
        "数据集ID": did, "分析需求": "统计", "图表类型": "饼图", "x轴": "地区",
        "y轴": ["销售额"], "分组字段": None, "聚合方式": "求和", "agent_mode": "single",
    })
    assert r.status_code == 200, r.text
    return r.json()["报表ID"]


def test_merge_正常合并_列并集行追加(client):
    tok = _register(client, "mrg1")
    a = _upload(client, tok, "a.csv", "地区,销售额\n华东,100\n")
    b = _upload(client, tok, "b.csv", "地区,销量\n华南,200\n")
    r = client.post("/datasets/merge", headers={"Authorization": f"Bearer {tok}"},
                    json={"数据集ID列表": [a, b], "文件名": "合并测试"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["行数"] == 2 and body["列数"] == 3, body  # 地区/销售额/销量 并集
    assert set(body["字段列表"]) >= {"地区", "销售额", "销量"}
    # 新数据集可读取
    assert client.get(f"/datasets/{body['数据集ID']}", headers={"Authorization": f"Bearer {tok}"}).status_code == 200


def test_merge_单数据集_400(client):
    tok = _register(client, "mrg2")
    a = _upload(client, tok, "a.csv", "地区,销售额\n华东,100\n")
    r = client.post("/datasets/merge", headers={"Authorization": f"Bearer {tok}"},
                    json={"数据集ID列表": [a]})
    assert r.status_code == 400


def test_merge_无权访问_404(client):
    tok_a = _register(client, "mrg3a")
    tok_b = _register(client, "mrg3b")
    a = _upload(client, tok_a, "a.csv", "地区,销售额\n华东,100\n")
    b = _upload(client, tok_a, "b.csv", "地区,销量\n华南,200\n")
    # B 用户尝试合并 A 的数据集
    r = client.post("/datasets/merge", headers={"Authorization": f"Bearer {tok_b}"},
                    json={"数据集ID列表": [a, b]})
    assert r.status_code == 404


def test_rows_分页与limit上限(client):
    tok = _register(client, "rows1")
    csv = "地区,销售额\n" + "".join(f"区{i},100\n" for i in range(25))
    did = _upload(client, tok, "big.csv", csv)
    h = {"Authorization": f"Bearer {tok}"}
    r1 = client.get(f"/datasets/{did}/rows?offset=0&limit=20", headers=h)
    r2 = client.get(f"/datasets/{did}/rows?offset=20&limit=20", headers=h)
    assert r1.json()["总行数"] == 25 and r1.json()["返回行数"] == 20
    assert r2.json()["返回行数"] == 5 and r2.json()["偏移"] == 20
    # limit 超上限 → 422
    assert client.get(f"/datasets/{did}/rows?limit=999", headers=h).status_code == 422
    # 匿名 → 401
    assert client.get(f"/datasets/{did}/rows").status_code == 401


def test_分享浏览次数_成功访问计数(client):
    tok = _register(client, "view1")
    did = _upload(client, tok, "a.csv", "地区,销售额\n华东,100\n")
    rid = _gen_report(client, tok, did)
    r = client.post(f"/reports/{rid}/share?有效小时数=24", headers={"Authorization": f"Bearer {tok}"})
    sid = None
    for v in r.json().values():
        if isinstance(v, str) and len(v) == 32:
            sid = v
            break
    assert sid
    # 匿名访问 2 次
    assert client.get(f"/share-data/{sid}").status_code == 200
    assert client.get(f"/share-data/{sid}").status_code == 200
    # 创建者列表可见浏览次数
    r = client.get(f"/reports/{rid}/shares", headers={"Authorization": f"Bearer {tok}"})
    item = next(s for s in r.json()["分享列表"] if s["链接ID"] == sid)
    assert item["浏览次数"] == 2, item


def test_清洗另存为新版本_保留原数据集(client):
    tok = _register(client, "cleanv")
    did = _upload(client, tok, "a.csv", "地区,销售额\n华东,100\n华东,100\n")
    h = {"Authorization": f"Bearer {tok}"}
    # 另存为新数据集（去重后 1 行）
    r = client.post(f"/datasets/{did}/clean", headers=h,
                    params={"deduplicate": "true", "新文件名": "去重版"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["数据集ID"] != did  # 新 id
    assert body["清洗后行数"] == 1
    # 原数据集仍存在（3 行？原 2 行）
    r = client.get(f"/datasets/{did}", headers=h)
    assert r.status_code == 200
    assert r.json()["数据画像"]["行数"] == 2
    # 新数据集在列表
    r = client.get("/datasets/", headers=h)
    names = [d["文件名"] for d in r.json()["数据集列表"]]
    assert "去重版" in names


def test_定时失败任务查询(client):
    tok = _register(client, "schedf")
    h = {"Authorization": f"Bearer {tok}"}
    # 创建模板 + 定时任务
    did = _upload(client, tok, "a.csv", "地区,销售额\n华东,100\n")
    r = client.post("/templates", headers=h, json={"名称": "t", "payload": {
        "数据集ID": did, "分析需求": "x", "图表类型": "自动推荐", "x轴": None, "y轴": [],
        "分组字段": None, "聚合方式": "求和", "agent_mode": "single"}})
    tid = r.json()["模板ID"]
    r = client.post("/schedules", headers=h, json={"模板ID": tid, "cron": "0 9 * * 1"})
    job = r.json()["任务ID"]
    # 手动记录一次失败结果（用当前用户 id：从 /auth/me 拿）
    from repositories import schedule_repo
    me = client.get("/auth/me", headers=h).json()
    schedule_repo.记录执行结果(me["user_id"], job, "失败: 模拟异常")
    r = client.get("/schedules/failed", headers=h)
    assert r.status_code == 200
    fails = r.json()["失败任务"]
    assert any(f["任务ID"] == job for f in fails), fails
    assert fails[0]["失败原因"].startswith("失败:")
