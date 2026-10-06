# -*- coding: utf-8 -*-
"""阶段 54-8 · MySQL 全链路测试（MySQL 假开关修复的验收级测试）。

真库验证：DB_BACKEND=mysql 下跑 注册→上传→生成报表→导出→分享→收藏→删除→审计，
断言业务数据**真的落在 MySQL**（不再落 SQLite），中文不乱码、时区读写一致、
username/email 唯一约束生效、重复注册被 400 拒绝而非 500。

- 无 MySQL 凭据时整模块 skip（参考既有 skip 模式）；
- 表用后清理：删除 qa_mysql_* 前缀行 + 种子 admin，恢复走查后 0 行基线；
- 不触碰 :8000 生产实例（生产为 SQLite daa.db，与本测试无关）。
"""

from __future__ import annotations

import io
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 16 张业务表（对齐 sqlite_repo / 各仓储初始化集合）
业务表 = ["audit_log", "dashboards", "datasets", "email_codes", "event_gen",
          "event_payment", "event_paywall", "event_register", "favorites",
          "feedback", "llm_usage", "report_templates", "reports",
          "scheduled_jobs", "share_links", "users"]


def _能连mysql() -> bool:
    """复用既有 skip 判定：密码只从环境变量 MYSQL_TEST_PASSWORD 读（同 test_mysql_backend），
    未显式给凭据即跳过——默认回归不依赖本机 .env 的 MySQL 密码。"""
    from config import settings
    password = os.getenv("MYSQL_TEST_PASSWORD", "")
    if not password:
        return False
    try:
        import pymysql
        conn = pymysql.connect(
            host=settings.EnvConfig.MYSQL_HOST,
            port=int(settings.EnvConfig.MYSQL_PORT),
            user=settings.EnvConfig.MYSQL_USER,
            password=password,
            database=settings.EnvConfig.MYSQL_DATABASE,
            connect_timeout=3, charset="utf8mb4")
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _能连mysql(), reason="无 MySQL 实例或凭据，跳过")


def _mysql_计数(表: str, where: str = "", 参数: tuple = ()) -> int:
    """直连 MySQL（不经统一入口包装，独立核对"数据真的在 MySQL"）。"""
    from 后端_核心.存储 import mysql_backend
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            sql = f"SELECT COUNT(*) FROM `{表}`" + (f" WHERE {where}" if where else "")
            cur.execute(sql, 参数 or None)
            return int(cur.fetchone()[0])


def _mysql_查一列(表: str, 列: str, where: str, 参数: tuple = ()):
    """直连 MySQL 取单列单行（断言中文/时区值）。"""
    from 后端_核心.存储 import mysql_backend
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT `{列}` FROM `{表}` WHERE {where} LIMIT 1", 参数 or None)
            row = cur.fetchone()
            return row[0] if row else None


def _清理测试残留(cur) -> None:
    """删除 qa_mysql_* 测试行 + 种子 admin + 其衍生行，恢复走查后 0 行基线。

    - qa 用户 user_id 是随机 u_hex，且 audit/导出等行只存 user_id 不存 username；
    - 上一轮失败若已删 users，行仍残留在其他表 → 用 ``u_`` 前缀收集兜底。
    """
    ids: set = set()
    cur.execute("SELECT user_id FROM users WHERE username LIKE 'qa_mysql_%' OR username = 'admin'")
    ids.update(r[0] for r in cur.fetchall())
    for 表 in 业务表:
        if 表 in ("users", "email_codes"):
            continue
        cur.execute(f"SELECT DISTINCT user_id FROM `{表}` WHERE user_id LIKE 'u_%'")
        ids.update(r[0] for r in cur.fetchall())
    id_片段 = ", ".join(f"'{u}'" for u in sorted(ids)) if ids else "'__none__'"
    cur.execute(
        f"DELETE FROM audit_log WHERE user_id IN ({id_片段}) "
        f"OR user_id LIKE 'qa_mysql_%' OR username LIKE 'qa_mysql_%' OR username = 'admin'"
    )
    cur.execute(f"DELETE FROM users WHERE user_id IN ({id_片段}) OR username LIKE 'qa_mysql_%' OR username = 'admin'")
    cur.execute("DELETE FROM email_codes WHERE email LIKE 'qa_mysql_%'")
    for 表 in 业务表:
        if 表 in ("users", "email_codes", "audit_log"):
            continue
        cur.execute(f"DELETE FROM `{表}` WHERE user_id IN ({id_片段}) OR user_id LIKE 'qa_mysql_%'")


def test_mysql_全链路_业务数据真实落库(monkeypatch):
    """DB_BACKEND=mysql 下全链路业务数据必须真实写入 MySQL（原缺陷：全落 SQLite）。"""
    from config import settings
    monkeypatch.setattr(settings.EnvConfig, "DB_BACKEND", "mysql", raising=False)

    # 基线准备：清掉任何残留（含 healthz mysql 模式等其他用例启动 lifespan 幂等创建的种子
    # admin），断言走查后 16 张业务表 0 行基线成立，测试结束后再恢复
    from 后端_核心.存储 import mysql_backend
    with mysql_backend.get_conn() as conn:
        with conn.cursor() as cur:
            _清理测试残留(cur)
    基线 = {表: _mysql_计数(表) for 表 in 业务表}
    for 表, n in 基线.items():
        assert n == 0, f"基线污染：{表} 已有 {n} 行（走查后应为 0，先人工清理）"

    # 捕获 dry-run 验证码（与 test_api_integration 同款）
    _SENT_CODES: dict = {}
    from services import email_service

    def _fake_send(email: str, code: str) -> bool:
        _SENT_CODES[email] = code
        return True

    _orig_send = email_service.发送验证码邮件
    email_service.发送验证码邮件 = _fake_send

    # 收集本测试创建的 dataset_id（清理 parquet/uploads 用）
    数据集文件: list = []

    try:
        from fastapi.testclient import TestClient
        from api.main import app
        with TestClient(app) as client:
            # 1) healthz：必须真报 mysql（原缺陷：报 mysql 但数据落 SQLite）
            r = client.get("/healthz")
            assert r.status_code == 200
            assert r.json()["db_backend"] == "mysql", r.text

            # 2) 注册（send-code → register）
            用户 = "qa_mysql_full1"
            邮箱 = f"{用户}@test.com"
            r = client.post("/auth/send-code", json={"email": 邮箱})
            assert r.status_code == 200, r.text
            code = _SENT_CODES.get(邮箱)
            assert code, "未捕获验证码"
            r = client.post("/auth/register", json={
                "username": 用户, "email": 邮箱, "code": code, "password": "secret123",
            })
            assert r.status_code == 200, r.text
            tok = r.json()["access_token"]
            h = {"Authorization": f"Bearer {tok}"}
            # ★ 验收：MySQL users 表有行（原缺陷 = 0 行，行全落 SQLite）
            assert _mysql_计数("users", "username = %s", (用户,)) == 1, "注册后 MySQL users 无行——假开关未修复"
            用户id = _mysql_查一列("users", "user_id", "username = %s", (用户,))
            assert 用户id

            # 3) 上传中文 CSV（中文文件名 + 中文内容，验证 utf8mb4 往返）
            content = "地区,销售额,备注\n华东,100,优质客户\n华南,200,普通客户\n"
            r = client.post(
                "/datasets/upload",
                files={"file": ("中文客户.csv", content.encode("utf-8"), "text/csv")},
                headers=h,
            )
            assert r.status_code == 200, r.text
            did = r.json()["上传成功"][0]["数据集ID"]
            数据集文件.append(Path("data/parquet") / f"{did}.parquet")
            assert _mysql_计数("datasets", "user_id = %s", (用户id,)) == 1, "上传后 MySQL datasets 无行"
            assert _mysql_查一列("datasets", "file_name", "dataset_id = %s", (did,)) == "中文客户.csv", \
                "中文文件名落 MySQL 乱码/丢失"

            # 4) 生成报表（规则引擎确定性路径，LLM 被 conftest 占位 key 禁用）
            r = client.post("/reports/generate", json={"数据集ID": did, "分析需求": "按地区统计"}, headers=h)
            assert r.status_code == 200, r.text
            rid = r.json()["报表ID"]
            assert _mysql_计数("reports", "user_id = %s", (用户id,)) == 1, "生成后 MySQL reports 无行"
            assert _mysql_计数("event_gen", "user_id = %s", (用户id,)) >= 1, "生成埋点未落 MySQL event_gen"

            # 5) 导出（xlsx 读回正常 = 数据链路完整）
            r = client.get(f"/reports/{rid}/export?format=xlsx", headers=h)
            assert r.status_code == 200 and r.content, r.text

            # 6) 分享 + 匿名访问（share_links 落 MySQL）
            r = client.post(f"/reports/{rid}/share", json={"有效小时数": 24}, headers=h)
            assert r.status_code == 200, r.text
            sid = r.json()["链接ID"]
            assert _mysql_计数("share_links", "share_id = %s", (sid,)) == 1, "分享未落 MySQL share_links"
            r = client.get(f"/share-data/{sid}")
            assert r.status_code == 200, f"匿名访问分享失败：{r.text[:200]}"
            body = r.json()
            assert body["标题"] and len(body["报表数据"]) > 0, "分享视图数据为空"
            assert "地区" in str(body), "分享数据中文内容异常"

            # 7) 收藏（favorites 落 MySQL）
            r = client.put(f"/reports/{rid}/favorite", headers=h)
            assert r.status_code == 200 and r.json()["is_favorited"] is True, r.text
            assert _mysql_计数("favorites", "user_id = %s AND report_id = %s", (用户id, rid)) == 1, \
                "收藏未落 MySQL favorites"

            # 8) 删除数据集（MySQL 行删除 + 物理文件清理）
            r = client.delete(f"/datasets/{did}", headers=h)
            assert r.status_code == 200, r.text
            assert _mysql_计数("datasets", "dataset_id = %s", (did,)) == 0, "删除后 MySQL datasets 仍残行"

            # 9) 审计：登录写 audit_log（落 MySQL）
            r = client.post("/auth/login", json={"username": 用户, "password": "secret123"})
            assert r.status_code == 200, r.text
            assert _mysql_计数("audit_log", "user_id = %s", (用户id,)) >= 1, "审计未落 MySQL audit_log"

            # 10) 唯一约束生效（MySQL UNIQUE）：
            #   API 层：同用户名 + 新邮箱注册 → 400「用户名已存在」（走 MySQL 1062 → ValueError）
            邮箱2 = "qa_mysql_dup2@test.com"
            r = client.post("/auth/send-code", json={"email": 邮箱2})
            assert r.status_code == 200, r.text
            code2 = _SENT_CODES.get(邮箱2)
            r = client.post("/auth/register", json={
                "username": 用户, "email": 邮箱2, "code": code2, "password": "secret123",
            })
            assert r.status_code == 400, f"重复用户名注册应 400（唯一约束未生效？），实际 {r.status_code}: {r.text[:200]}"
            assert "用户名已存在" in r.json().get("message", ""), r.text
            #   repo 层：直接二次创建 → 唯一冲突必须被识别为 ValueError（sqlite 与 mysql 错误文案不同）
            from repositories import user_repo
            user_repo.创建用户("qa_mysql_dup3", "hash1", email="qa_mysql_dup3@test.com")
            try:
                user_repo.创建用户("qa_mysql_dup3", "hash2", email="qa_mysql_dup4@test.com")
                raise AssertionError("重复用户名未触发唯一冲突（MySQL UNIQUE 未生效）")
            except ValueError as exc:
                assert "用户名已存在" in str(exc), str(exc)

            # 11) 时区：写入 +00:00 ISO 读回不得 +8h（VARCHAR 存 ISO 原文，读回字节一致更佳）
            from repositories import email_code_repo
            email_code_repo.保存验证码("qa_mysql_tz@test.com", "deadbeef", "2026-10-06T07:07:00.000000+00:00")
            读回 = str(_mysql_查一列("email_codes", "expires_at", "email = %s", ("qa_mysql_tz@test.com",)))
            归一 = 读回.replace("T", " ").replace("+00:00", "")
            assert 归一.startswith("2026-10-06 07:07:00"), \
                f"时区读写不一致：写入 2026-10-06T07:07:00+00:00 读回 {读回!r}（+8h 平移）"

            # 12) 中文内容往返：上传时字段列表含中文列名（已由 step3 断言 file_name，这里再钉数据不丢字）
            r = client.get(f"/reports/{rid}", headers=h)
            assert r.status_code == 200, r.text
            assert "优质客户" in str(r.json().get("报表", {})), "报表数据中文丢失"

    finally:
        email_service.发送验证码邮件 = _orig_send
        # 清理：qa_mysql_* 行 + 种子 admin + 物理文件 → 恢复基线 0 行
        with mysql_backend.get_conn() as conn:
            with conn.cursor() as cur:
                _清理测试残留(cur)
        for p in 数据集文件:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        # 恢复断言：16 张业务表回到基线（0 行）
        for 表, n in 基线.items():
            现 = _mysql_计数(表)
            assert 现 == n, f"清理不彻底：{表} 应为 {n} 行，实际 {现} 行（请人工清理后重跑）"
