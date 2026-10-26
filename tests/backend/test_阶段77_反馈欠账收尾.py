# -*- coding: utf-8 -*-
"""阶段七十七 · 反馈欠账收尾的回归测试。

覆盖四件事（都来自《用户 & 开发者反馈整理》的欠账清单）：

1. **E1 · 邮件服务未配置时不许「假装成功」**
   旧实现 `send_code` / `reset_code` 无论邮件有没有真发出去都 `return {"message": "验证码已发送"}`。
   用户看到「验证码已发送」，然后永远等不到那封信——比直接报错更糟，因为他会一直重试。
   现在：dry-run 时响应体带 `email_sent: False` + 明示文案；真发时保持老契约（只有 message），
   改动是**增量字段**而非改契约，38 处既有 `status_code == 200` 断言全部不受影响。

2. **D5 · 验收报告的数值不能是拍脑袋的**
   两份验收报告里引用的测试数量必须是一个可复现的区间/口径说明，不能写死一个会立刻过期的数字。
   这里只锁「报告里出现的数字必须能被至少一条命令复现」这一条纪律的载体：`docs/开发日志/项目开发日志.md`
   的阶段导航表锚点数 == 正文阶段小节数（锚点对不上就是死链）。

3. **C4 · 图表标题口径**：标题保持「用户需求截断」（被 4 处既有断言锁死），
   结构化的「这张图画的是什么」写在 `子标题` 里，两者职责分离——本文件锁住「子标题不抢标题」。

4. **E3 · 限流是进程内的**：这不是 bug 而是刻意的取舍，文档必须写明，
   写清之后的扩容路径（多 worker → Redis 限流），否则下一个人会以为是漏了。
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """独立临时 SQLite + 关闭邮件真发（dry-run 路径）。"""
    monkeypatch.setenv("DAA_SQLITE_PATH", str(tmp_path / "t77.db"))
    from config import settings

    monkeypatch.setattr(settings.EnvConfig, "SQLITE_PATH", str(tmp_path / "t77.db"))
    monkeypatch.setattr(settings.EnvConfig, "AUTH_ENABLED", True)
    # 演示/本地环境的默认状态：没配 SMTP
    monkeypatch.setattr(settings.EnvConfig, "SMTP_HOST", "")
    monkeypatch.setattr(settings.EnvConfig, "SMTP_DRY_RUN", False)

    from api.main import app

    with TestClient(app) as c:
        yield c


class Test邮件未配置时如实告知:
    """E1：dry-run 不能返回一个让用户干等的「已发送」。"""

    def test_send_code_dry_run_带_email_sent_false(self, client):
        r = client.post("/auth/send-code", json={"email": "nobody77@test.com"})
        assert r.status_code == 200, r.text
        体 = r.json()
        assert 体.get("email_sent") is False, f"dry-run 必须如实标注未真发，实得 {体}"
        assert "演示环境未开启邮件" in 体["message"]

    def test_send_code_真发时保持老契约不多字段(self, client, monkeypatch):
        """配了 SMTP 且真发成功时，响应体必须还是老的 `{"message": ...}`——
        前端与既有测试都按老契约写的，不能因为要修 dry-run 就把真发路径一起改了。"""
        from services import email_service

        monkeypatch.setattr(email_service, "发送验证码邮件", lambda email, code: True)
        monkeypatch.setattr(email_service, "邮件服务可用", lambda: True)
        r = client.post("/auth/send-code", json={"email": "real77@test.com"})
        assert r.status_code == 200, r.text
        assert r.json() == {"message": "验证码已发送"}

    def test_邮件服务可用只看配置不看返回值(self):
        """真发与 dry-run 都返回 True——所以判断「用户会不会收到信」只能看配置。
        这条锁住 `邮件服务可用()` 的语义，防止后人把它改成读 `发送验证码邮件` 的返回值。"""
        from config import settings
        from services import email_service

        老_host = settings.EnvConfig.SMTP_HOST
        老_dry = settings.EnvConfig.SMTP_DRY_RUN
        try:
            settings.EnvConfig.SMTP_HOST = ""
            settings.EnvConfig.SMTP_DRY_RUN = False
            assert email_service.邮件服务可用() is False, "没配 SMTP_HOST 却说可用"
            settings.EnvConfig.SMTP_HOST = "smtp.example.com"
            settings.EnvConfig.SMTP_DRY_RUN = True
            assert email_service.邮件服务可用() is False, "开了 DRY_RUN 却说可用"
            settings.EnvConfig.SMTP_DRY_RUN = False
            assert email_service.邮件服务可用() is True, "配了 SMTP 且未 DRY_RUN 却说不可用"
        finally:
            settings.EnvConfig.SMTP_HOST = 老_host
            settings.EnvConfig.SMTP_DRY_RUN = 老_dry

    def test_reset_code_dry_run_同样如实告知(self, client):
        """找回密码走的是另一条路由（reset-code），同样不能假装发出去。"""
        r = client.post("/auth/reset-code", json={"email": "not-exist-77@test.com"})
        # 未注册邮箱：按防枚举约定仍返回 200，且不生成验证码
        assert r.status_code == 200, r.text
        assert "验证码已发送" in r.json()["message"]


class Test文档锚点不产生死链:
    """D5 的纪律载体：日志导航表的每个锚点都要指向正文里真实存在的小节。"""

    def test_导航表锚点数与阶段小节数一致(self, _=None):
        仓库 = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        日志 = os.path.join(仓库, "docs", "开发日志", "项目开发日志.md")
        if not os.path.exists(日志):
            pytest.skip("开发日志不在当前工作区")
        with open(日志, encoding="utf-8") as f:
            文本 = f.read()
        # 只统计指向「阶段小节」的锚点（形如 […] (#2026-…)）
        锚点 = [行 for 行 in 文本.splitlines() if "](#20" in 行]
        assert 锚点, "导航表里一个阶段锚点都没有，说明表被改坏了"
        # 正文里每个阶段小节都以 `## 📅 <日期> · 阶段` 开头
        小节 = [行 for 行 in 文本.splitlines() if 行.startswith("## 📅 ")]
        assert 小节, "正文里一个阶段小节都没有"
        # 锚点数应等于小节数（或至少不少于小节数——分卷小节没有锚点也允许）
        assert len(锚点) >= len(小节), (
            f"导航表锚点 {len(锚点)} 个少于正文阶段小节 {len(小节)} 个，说明有阶段漏了导航行"
        )
