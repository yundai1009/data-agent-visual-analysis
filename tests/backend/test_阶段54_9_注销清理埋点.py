# -*- coding: utf-8 -*-
"""阶段 54-9 · Fix E4（多用户 P3-1）· 注销清理 event_* 埋点表：

`删除用户及数据` 原删除清单不含 event_register/event_gen/event_payment/event_paywall/
favorites/llm_usage/report_templates/scheduled_jobs（走查实测注销后 event_register
残留 1 行）。本批补全 8 张含 user_id 的表，注销后该用户行数必须为 0。

测试（隔离库）：注册（落 event_register）→ 生成报表（落 event_gen）→ 手工造
favorites/llm_usage/report_templates/scheduled_jobs/event_payment/event_paywall
→ 注销 → 断言 8 表该用户行数 = 0、他人数据不受影响。
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SENT_CODES: dict = {}

# 注销后必须清零的含 user_id 表（E4 补全清单）
_应清空表 = [
    "event_register", "event_gen", "event_payment", "event_paywall",
    "favorites", "llm_usage", "report_templates", "scheduled_jobs",
]


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("fix549_e4_del")
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


def _注册登录(client, username) -> str:
    """注册并返回 token（注册 API 会落 event_register 埋点）。"""
    email = f"{username}@test.com"
    r = client.post("/auth/send-code", json={"email": email})
    assert r.status_code == 200, r.text
    code = _SENT_CODES.get(email)
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _生成报表(client, token):
    """上传 + 生成报表（落 reports + event_gen）。返回 report_id。"""
    r = client.post(
        "/datasets/upload",
        files={"file": ("t.csv", "地区,销售额\n华东,100\n华南,200\n", "text/csv")},
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


def _造全量业务数据(client, token, user_id):
    """把 8 张待清表全部造出至少 1 行该用户数据。"""
    from repositories import event_repo, favorite_repo, schedule_repo, template_repo, usage_repo

    rid = _生成报表(client, token)
    favorite_repo.切换收藏(user_id, rid)                     # favorites
    usage_repo.记录用量(user_id, "deepseek", "deepseek-chat", 10, 5)  # llm_usage（规则路径不自动落，手工造）
    template_repo.保存模板(user_id, "我的模板", {"分析需求": "x"})    # report_templates
    tid = template_repo.保存模板(user_id, "定时模板", {"分析需求": "y"})
    schedule_repo.创建任务(user_id, tid, "0 9 * * *")        # scheduled_jobs
    event_repo.记录支付事件(f"o_{user_id}", user_id, "月卡", 29.9)   # event_payment
    event_repo.记录拦截事件(user_id, "重试", shown_price=29.9)       # event_paywall


def _该用户行数(user_id, table) -> int:
    from 后端_核心.存储.连接 import _get_conn
    with _get_conn() as conn:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE user_id = ?", (user_id,)).fetchone()
    return int(row["n"])


def test_注销后_8张含user_id表全部清零(client):
    """E4 红→绿：注销后 event_*/favorites/llm_usage/report_templates/scheduled_jobs 全清零。"""
    from repositories import user_repo
    token = _注册登录(client, "e4user")
    user_id = user_repo.按用户名查询("e4user")["user_id"]
    _造全量业务数据(client, token, user_id)

    # 注销前：8 表该用户都有数据（防"空断言假绿"）
    for table in _应清空表:
        assert _该用户行数(user_id, table) >= 1, f"前置：{table} 应有该用户数据（当前 0 行）"

    # 注销（密码正确）
    r = client.post("/auth/delete-account", json={"password": "secret123"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text

    # 断言：8 表该用户行数全部 = 0；users 表用户也没了
    for table in _应清空表:
        n = _该用户行数(user_id, table)
        assert n == 0, f"注销后 {table} 仍有该用户 {n} 行残留"
    assert user_repo.按用户ID查询(user_id) is None, "注销后 users 表该用户应删除"


def test_注销_他人埋点数据不受影响(client):
    """E4：只删本人，他人 event_gen 行保留（删除键 user_id 精准）。"""
    from repositories import event_repo, user_repo
    token_a = _注册登录(client, "e4a")
    user_a = user_repo.按用户名查询("e4a")["user_id"]
    _生成报表(client, token_a)  # user_a 的 event_gen 行
    他人_id = "u_other999999999999"  # 独立假用户 id，仅验证删除范围精准
    event_repo.记录生成事件(他人_id, analysis_type="折线图")
    assert _该用户行数(他人_id, "event_gen") == 1

    r = client.post("/auth/delete-account", json={"password": "secret123"},
                    headers={"Authorization": f"Bearer {token_a}"})
    assert r.status_code == 200, r.text

    assert _该用户行数(user_a, "event_gen") == 0, "本人 event_gen 应清零"
    assert _该用户行数(他人_id, "event_gen") == 1, "他人 event_gen 不受影响"
