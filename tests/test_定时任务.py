"""阶段 30 · 定时生成测试：cron 解析 + API + 作业执行，不依赖网络与 LLM key。

覆盖目标
========
- ``cron匹配``：* / 固定值 / 列表 / 范围 / 步进 / 周字段（0=周日）归一化
- ``下次执行时间``：返回未来首次命中
- API：创建（合法/非法 cron 400/模板不存在 404）/ 列出（附下次执行）/ 删除 / 401
- ``执行作业``：模板 + 最新数据 → 新报表入库（报表历史 +1）
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SENT_CODES: dict = {}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("schedule_test")
    os.environ["DAA_SQLITE_PATH"] = str(tmp_dir / "test.db")
    from config import settings
    settings.EnvConfig.SQLITE_PATH = str(tmp_dir / "test.db")
    settings.EnvConfig.AUTH_ENABLED = True
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


def _register(client, username) -> str:
    email = f"{username}@test.com"
    assert client.post("/auth/send-code", json={"email": email}).status_code == 200
    code = _SENT_CODES.get(email)
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _setup_template(client, token) -> str:
    """上传数据集 + 保存模板，返回模板 ID。"""
    r = client.post(
        "/datasets/upload",
        files={"file": ("t.csv", "地区,销售额\n华东,100\n华南,200\n", "text/csv")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    ds = r.json()["数据集ID"]
    payload = {"数据集ID": ds, "分析需求": "按地区统计销售额", "图表类型": "自动推荐"}
    r = client.post("/templates", json={"名称": "定时模板", "payload": payload},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["模板ID"]


# ============================================================================
# 1. cron 解析
# ============================================================================

class TestCron匹配:
    def test_每分钟(self):
        from services.scheduler import cron匹配
        assert cron匹配("* * * * *", datetime(2026, 1, 1, 10, 30))
        assert cron匹配("* * * * *", datetime(2026, 6, 15, 23, 59))

    def test_固定值(self):
        from services.scheduler import cron匹配
        assert cron匹配("15 9 * * *", datetime(2026, 1, 1, 9, 15))
        assert not cron匹配("15 9 * * *", datetime(2026, 1, 1, 9, 16))

    def test_列表与范围(self):
        from services.scheduler import cron匹配
        assert cron匹配("0,30 * * * *", datetime(2026, 1, 1, 10, 30))
        assert cron匹配("0 9-11 * * *", datetime(2026, 1, 1, 10, 0))
        assert not cron匹配("0 9-11 * * *", datetime(2026, 1, 1, 12, 0))

    def test_步进(self):
        from services.scheduler import cron匹配
        assert cron匹配("*/15 * * * *", datetime(2026, 1, 1, 10, 45))
        assert not cron匹配("*/15 * * * *", datetime(2026, 1, 1, 10, 50))

    def test_周字段归一化(self):
        from services.scheduler import cron匹配
        # 2026-08-10 是周一 → cron 周 1 命中；周 0（周日）不命中
        monday = datetime(2026, 8, 10, 9, 0)
        sunday = datetime(2026, 8, 16, 9, 0)
        assert cron匹配("0 9 * * 1", monday)
        assert not cron匹配("0 9 * * 1", sunday)
        assert cron匹配("0 9 * * 0", sunday)

    def test_非法表达式(self):
        from services.scheduler import cron匹配
        assert not cron匹配("0 9 * *")  # 4 字段
        assert not cron匹配("a b c d e")  # 非数字

    def test_下次执行时间(self):
        from services.scheduler import 下次执行时间
        nxt = 下次执行时间("30 9 * * *", datetime(2026, 8, 10, 9, 0))
        assert nxt == "2026-08-10T09:30:00"


# ============================================================================
# 2. API
# ============================================================================

class Test定时任务API:
    def test_创建_列出_删除全流程(self, client):
        token = _register(client, "scheduser")
        tid = _setup_template(client, token)
        h = {"Authorization": f"Bearer {token}"}
        # 创建
        r = client.post("/schedules", json={"模板ID": tid, "cron": "0 9 * * 1"}, headers=h)
        assert r.status_code == 200, r.text
        jid = r.json()["任务ID"]
        # 列出（含下次执行时间）
        r = client.get("/schedules", headers=h)
        assert r.status_code == 200
        jobs = r.json()["任务列表"]
        job = next(j for j in jobs if j["任务ID"] == jid)
        assert job["cron"] == "0 9 * * 1"
        assert job["启用"] is True
        assert job["下次执行"]  # 非空
        # 删除
        r = client.delete(f"/schedules/{jid}", headers=h)
        assert r.status_code == 200
        assert not any(j["任务ID"] == jid for j in client.get("/schedules", headers=h).json()["任务列表"])

    def test_非法cron_400(self, client):
        token = _register(client, "schedbad")
        tid = _setup_template(client, token)
        r = client.post("/schedules", json={"模板ID": tid, "cron": "not-a-cron"},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400

    def test_模板不存在_404(self, client):
        token = _register(client, "sched404")
        r = client.post("/schedules", json={"模板ID": "nope", "cron": "0 9 * * 1"},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404

    def test_未登录401(self, client):
        assert client.post("/schedules", json={}).status_code == 401
        assert client.get("/schedules").status_code == 401

    def test_他人定时任务不可删(self, client):
        token_a = _register(client, "scheda")
        token_b = _register(client, "schedb")
        tid = _setup_template(client, token_a)
        r = client.post("/schedules", json={"模板ID": tid, "cron": "0 9 * * 1"},
                        headers={"Authorization": f"Bearer {token_a}"})
        jid = r.json()["任务ID"]
        assert client.delete(f"/schedules/{jid}", headers={"Authorization": f"Bearer {token_b}"}).status_code == 404


# ============================================================================
# 3. 作业执行（手动触发调度逻辑）
# ============================================================================

class Test执行作业:
    def test_作业生成报表入库(self, client):
        token = _register(client, "schedrun")
        tid = _setup_template(client, token)
        h = {"Authorization": f"Bearer {token}"}
        r = client.post("/schedules", json={"模板ID": tid, "cron": "0 9 * * 1"}, headers=h)
        jid = r.json()["任务ID"]

        from repositories import schedule_repo
        # 用"查启用的任务"拿到含 用户ID 的作业视图（模拟调度线程的输入）
        jobs = schedule_repo.查启用的任务()
        job_view = next(j for j in jobs if j["任务ID"] == jid)

        from services.scheduler import 执行作业
        result = 执行作业(job_view)
        assert result == "ok"

        # 报表历史 +1（调度生成的报表对用户可见）
        r = client.get("/reports/", headers=h)
        assert r.status_code == 200
        reports = r.json()["报表列表"] if isinstance(r.json(), dict) and "报表列表" in r.json() else r.json()
        assert len(reports) >= 1
        # 任务状态已更新为成功
        fresh = schedule_repo.读取任务(job_view["用户ID"], jid)
        assert fresh["上次状态"] == "成功"
        assert fresh["上次执行"]

    def test_模板删除后作业失败不崩(self, client):
        token = _register(client, "schedfail")
        tid = _setup_template(client, token)
        h = {"Authorization": f"Bearer {token}"}
        r = client.post("/schedules", json={"模板ID": tid, "cron": "0 9 * * 1"}, headers=h)
        jid = r.json()["任务ID"]
        assert client.delete(f"/templates/{tid}", headers=h).status_code == 200

        from repositories import schedule_repo
        job_view = next(j for j in schedule_repo.查启用的任务() if j["任务ID"] == jid)

        from services.scheduler import 执行作业
        result = 执行作业(job_view)
        assert result != "ok"  # 模板不存在 → 返回失败原因，不抛异常
        fresh = schedule_repo.读取任务(job_view["用户ID"], jid)
        assert fresh["上次状态"].startswith("失败")