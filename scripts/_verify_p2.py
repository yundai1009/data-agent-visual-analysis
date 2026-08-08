# -*- coding: utf-8 -*-
"""模拟 CI 关键链路（TestClient）：注册/登录/生成/导出/删除/改密吊销/重置/审计。"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"
tmp_db = Path(tempfile.gettempdir()) / "verify_p2.db"
os.environ["DAA_SQLITE_PATH"] = str(tmp_db)
if tmp_db.exists():
    tmp_db.unlink()

from config import settings
settings.EnvConfig.SQLITE_PATH = str(tmp_db)
settings.EnvConfig.AUTH_ENABLED = True

from fastapi.testclient import TestClient
from api.main import app

SENT = {}


def run():
    from services import email_service
    SENT.clear()
    _orig = email_service.发送验证码邮件
    email_service.发送验证码邮件 = lambda email, code: (SENT.__setitem__(email, code) or True)
    try:
        with TestClient(app) as c:
            email = "u1@t.com"
            c.post("/auth/send-code", json={"email": email})
            r = c.post("/auth/register", json={"username": "u1", "email": email, "code": SENT[email], "password": "secret123"})
            assert r.status_code == 200, r.text
            h = {"Authorization": f"Bearer {r.json()['access_token']}"}

            csv = "地区,销售额\n华东,1\n华南,2\n"
            r = c.post("/datasets/upload", files={"file": ("t.csv", csv.encode(), "text/csv")}, headers=h)
            assert r.status_code == 200, r.text
            did = r.json()["数据集ID"]
            r = c.post("/reports/generate", json={"数据集ID": did, "分析需求": "各区域统计"}, headers=h)
            assert r.status_code == 200, r.text
            rid = r.json()["报表ID"]

            r = c.get(f"/reports/{rid}/export?format=csv", headers=h)
            assert r.status_code == 200, r.text
            r = c.delete(f"/datasets/{did}", headers=h)
            assert r.status_code == 200, r.text

            r = c.post("/auth/change-password", json={"old_password": "secret123", "new_password": "secret456"}, headers=h)
            assert r.status_code == 200, r.text
            r = c.get("/datasets/", headers=h)
            assert r.status_code == 401, f"旧 token 应失效: {r.status_code}"

            r = c.post("/auth/login", json={"username": "u1", "password": "secret456"})
            assert r.status_code == 200, r.text
            # 快进验证码冷却（真实场景不会注册后立即重置）
            from 后端_核心.存储.sqlite_repo import _get_conn
            _past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
            with _get_conn() as _conn:
                _conn.execute("UPDATE email_codes SET last_sent_at = ? WHERE email = ?", (_past, email))
            r = c.post("/auth/reset-code", json={"email": email})
            assert r.status_code == 200, r.text
            r = c.post("/auth/reset-password", json={"email": email, "code": SENT[email], "password": "secret789"})
            assert r.status_code == 200, r.text

            r = c.post("/auth/login", json={"username": "admin", "password": os.environ["SEED_ADMIN_PASSWORD"]})
            assert r.status_code == 200, r.text
            ah = {"Authorization": f"Bearer {r.json()['access_token']}"}
            r = c.get("/admin/audit?limit=20", headers=ah)
            assert r.status_code == 200, r.text
            logs = r.json().get("审计列表", [])
            assert logs, "审计列表为空"
            assert any(x["操作"] == "登录成功" for x in logs)
            assert any(x["操作"] == "导出报表" for x in logs)
            print("审计条目:", len(logs))
        print("SMOKE PASSED: 全链路 OK")
    finally:
        email_service.发送验证码邮件 = _orig
        tmp_db.unlink(missing_ok=True)


if __name__ == "__main__":
    run()