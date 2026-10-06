# -*- coding: utf-8 -*-
"""阶段 54-8 · 第二块 Fix D（XSS 走查 Important #1）：rename/merge/清洗另存 复用 _清洗文件名。

走查证据（_stage52_xss/报告.md 发现 #1）：
- 上传路径有 `_清洗文件名`（datasets.py L62，`<>` 等 → `_`），但
  `rename_dataset`(L293) / `merge_datasets`(L174) / clean 另存路径不清洗，
  恶意名 `x<img src=x onerror=alert(4)>.csv` 原样入库。
- 判定：渲染层 PASS（React 默认转义，当前不可执行），属**存储层纵深缺口**——
  任何把文件名拼进 HTML 字符串/邮件/第三方回调的路径都会变成真注入。

修复：rename / merge / clean 另存 的新文件名统一过 `_清洗文件名`（对齐上传路径），
长度/空名校验同上传（作用于清洗后文件名）。

本文件覆盖
==========
1. rename：`<img>` 载荷 → 存库名清洗（响应与列表读取一致）
2. merge：`<script>` 载荷 → 输出名清洗
3. clean 另存：`<img onerror>` 载荷 → 另存名清洗
4. 边界：清洗后为空（".."）→ 400；超长 → 400
5. 回归：正常名（中文/含空格）不受影响
"""

from __future__ import annotations

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
    tmp_dir = tmp_path_factory.mktemp("fix_xss_names")
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
    assert code
    r = client.post("/auth/register", json={
        "username": username, "email": email, "code": code, "password": "secret123",
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _上传(client, token, name="s.csv", content="地区,销售额\n华东,100\n华南,200\n"):
    r = client.post("/datasets/upload", headers={"Authorization": f"Bearer {token}"},
                    files={"file": (name, content.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["上传成功"][0]


def _读名(client, token, did):
    r = client.get(f"/datasets/{did}", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["文件名"]


_载荷 = "x<img src=x onerror=alert(1)>.csv"


def test_rename_恶意名被清洗入库存名(client):
    """红：重命名路径不过 _清洗文件名，`<img>` 原样入库。"""
    token = _注册(client, "xss1")
    did = _上传(client, token)["数据集ID"]
    r = client.patch(f"/datasets/{did}", json={"文件名": _载荷},
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    name = r.json()["文件名"]
    assert "<" not in name and ">" not in name, f"存库名仍含尖括号：{name!r}"
    assert name == "x_img src=x onerror=alert(1)_.csv", name
    # 入库值与响应一致
    assert _读名(client, token, did) == name


def test_merge_恶意名被清洗(client):
    """红：merge 输出名不过 _清洗文件名。"""
    token = _注册(client, "xss2")
    a = _上传(client, token, "a.csv")["数据集ID"]
    b = _上传(client, token, "b.csv", "地区,销售额\n华南,300\n华东,150\n")["数据集ID"]
    r = client.post("/datasets/merge", json={"数据集ID列表": [a, b], "文件名": "x<script>alert(2)</script>.csv"},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    name = r.json()["文件名"]
    assert "<" not in name and ">" not in name, f"合并输出名仍含尖括号：{name!r}"
    assert _读名(client, token, r.json()["数据集ID"]) == name


def test_clean另存_恶意名被清洗(client):
    """红：clean 另存的 新文件名 不过 _清洗文件名。"""
    token = _注册(client, "xss3")
    did = _上传(client, token)["数据集ID"]
    r = client.post(f"/datasets/{did}/clean",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"deduplicate": "true", "新文件名": "y<img onerror=alert(3)>.csv"})
    assert r.status_code == 200, r.text
    new_id = r.json()["数据集ID"]
    assert new_id != did, "传了新文件名应另存为新数据集"
    name = _读名(client, token, new_id)
    assert "<" not in name and ">" not in name, f"另存名仍含尖括号：{name!r}"
    assert name == "y_img onerror=alert(3)_.csv", name


def test_rename_清洗后为空_400(client):
    """清洗后为空（".." 归一为空 / 纯空白）→ 400（对齐上传路径空名校验）。"""
    token = _注册(client, "xss4")
    did = _上传(client, token)["数据集ID"]
    for bad in ("..", "   "):
        r = client.patch(f"/datasets/{did}", json={"文件名": bad},
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 400, f"{bad!r} 应 400，实际 {r.status_code}：{r.text}"


def test_rename_空载荷_与上传路径一致回退upload(client):
    """空载荷（文件名缺省/空串）→ _清洗文件名 内置回退 "upload"（与上传路径
    对空名的兜底一致）；空串不误报 400。"""
    token = _注册(client, "xss8")
    did = _上传(client, token)["数据集ID"]
    for bad in ("", None):
        payload = {"文件名": bad} if bad is not None else {}
        r = client.patch(f"/datasets/{did}", json=payload,
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert r.json()["文件名"] == "upload"


def test_rename_仅尖括号_清洗为合法名而非400(client):
    """`<>` 清洗后是 "__"（合法名，尖括号已消除）→ 200，非空名不应误报 400。"""
    token = _注册(client, "xss7")
    did = _上传(client, token)["数据集ID"]
    r = client.patch(f"/datasets/{did}", json={"文件名": "<>"},
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["文件名"] == "__"


def test_rename_超长400(client):
    """长度校验作用于清洗后文件名（对齐上传路径）。"""
    token = _注册(client, "xss5")
    did = _上传(client, token)["数据集ID"]
    r = client.patch(f"/datasets/{did}", json={"文件名": "a" * 130 + ".csv"},
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400, r.text


def test_rename_正常中文名不受影响(client):
    """回归：正常名（含中文与空格）清洗后不变。"""
    token = _注册(client, "xss6")
    did = _上传(client, token)["数据集ID"]
    r = client.patch(f"/datasets/{did}", json={"文件名": "销售 数据 2026.csv"},
                     headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert r.json()["文件名"] == "销售 数据 2026.csv"
    # 路径穿越防护：取末段路径组件
    r2 = client.patch(f"/datasets/{did}", json={"文件名": "..\\..\\evil.csv"},
                      headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["文件名"] == "evil.csv"


# ═══ 补修 D1/D2（阶段 54-8 审查）：clean 原位 / merge 默认名 被 _清洗文件名
#    空输入回退 "upload" 劫持 ═══


def test_clean原位_数据集名保持原名已清洗(client):
    """D1 红：clean 原位清洗（不传 新文件名）——修复前
    `最终名 = _清洗文件名('') or _清洗文件名(原名+'（已清洗）')`，
    `_清洗文件名('')` 因 (raw or "upload") 返回 "upload"（真值）→ `or`
    短路 → 数据集被原地改名 "upload"；修复后原位清洗名 = 「原名（已清洗）」。"""
    token = _注册(client, "xss9")
    up = _上传(client, token, "销售数据.csv")
    did = up["数据集ID"]
    assert up["文件名"] == "销售数据.csv"

    r = client.post(f"/datasets/{did}/clean", headers={"Authorization": f"Bearer {token}"},
                    params={"deduplicate": "true"})
    assert r.status_code == 200, r.text
    # 原位清洗：数据集ID 不变（未另存）
    assert r.json()["数据集ID"] == did
    name = _读名(client, token, did)
    assert name == "销售数据.csv（已清洗）", f"原位清洗名应为「原名（已清洗）」，实际 {name!r}"


def test_merge_不传文件名_默认名合并数据集N个(client):
    """D2 红：merge 不传 文件名——修复前 `_清洗文件名(str("" or ""))`
    返回 "upload"（真值）→ L190 起 `新文件名 or f'合并数据集（N 个）'`
    兜底永不到达 → 合并产物名 "upload"；修复后默认名 = 「合并数据集（2 个）」。"""
    token = _注册(client, "xss10")
    a = _上传(client, token, "a.csv")["数据集ID"]
    b = _上传(client, token, "b.csv", "地区,销售额\n华南,300\n华东,150\n")["数据集ID"]

    r = client.post("/datasets/merge", json={"数据集ID列表": [a, b]},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    name = r.json()["文件名"]
    assert name == "合并数据集（2 个）", f"merge 默认名应为「合并数据集（2 个）」，实际 {name!r}"
    assert _读名(client, token, r.json()["数据集ID"]) == name