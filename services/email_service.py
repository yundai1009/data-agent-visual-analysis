"""邮箱验证码服务：生成验证码 + 发送邮件（标准库 smtplib，零新增依赖）。

设计：
- 验证码：6 位数字（secrets 生成），默认 10 分钟有效
- 验证码存储：只存哈希（HMAC-SHA256，密钥复用 JWT_SECRET_KEY），不存明文；
  dry-run 模式下明文验证码打印到后端日志（本地调试用），数据库始终不落明文
- 发送：SMTP_SSL（默认 465 端口）；未配置 SMTP_HOST 或 SMTP_DRY_RUN=true 时不真发
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import smtplib
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr

from config.settings import EnvConfig

logger = logging.getLogger(__name__)

# 验证码有效期（秒）
CODE_TTL_SECONDS = 10 * 60

# 校验尝试限频：10 分钟内最多尝试次数
MAX_VERIFY_ATTEMPTS = 5
VERIFY_WINDOW_SECONDS = 10 * 60

# 发送限频：同一邮箱最短发送间隔（秒）
SEND_COOLDOWN_SECONDS = 60


def 生成验证码() -> str:
    """生成 6 位数字验证码。"""
    return f"{secrets.randbelow(1_000_000):06d}"


def 验证码哈希(code: str) -> str:
    """验证码哈希（HMAC-SHA256，密钥来自 JWT_SECRET_KEY）。"""
    secret = getattr(EnvConfig, "JWT_SECRET_KEY", "change-me-in-production")
    return hmac.new(secret.encode(), code.encode(), hashlib.sha256).hexdigest()


def 校验验证码(code: str, code_hash: str) -> bool:
    """常量时间比对验证码。"""
    return hmac.compare_digest(验证码哈希(code), code_hash)


def _send_smtp(email: str, code: str) -> None:
    """真实发送验证码邮件（SMTP_SSL）。失败抛异常，由调用方决定降级。"""
    host = EnvConfig.SMTP_HOST
    port = EnvConfig.SMTP_PORT
    user = EnvConfig.SMTP_USER
    password = EnvConfig.SMTP_PASS
    sender = EnvConfig.SMTP_FROM or user

    body = (
        f"【数据分析 Agent 平台】\n\n"
        f"您的注册验证码是：{code}\n"
        f"验证码 {CODE_TTL_SECONDS // 60} 分钟内有效，请勿泄露给他人。\n\n"
        f"如果不是您本人操作，请忽略本邮件。"
    )
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header("数据分析 Agent 平台 - 注册验证码", "utf-8")
    msg["From"] = formataddr(("数据分析 Agent 平台", sender))
    msg["To"] = email

    with smtplib.SMTP_SSL(host, port, timeout=15) as server:
        server.login(user, password)
        server.sendmail(sender, [email], msg.as_string())


def 发送验证码邮件(email: str, code: str) -> bool:
    """发送验证码邮件。

    - dry-run（未配 SMTP_HOST 或 SMTP_DRY_RUN=true）：验证码打印到后端日志，返回 True
    - 真实发送：成功返回 True；失败打日志返回 False（验证码仍入库，可重发）
    """
    if EnvConfig.SMTP_DRY_RUN or not EnvConfig.SMTP_HOST:
        # 用 warning 级别：保证在 --log-level warning 的默认配置下也可见（dry-run 仅调试用）
        logger.warning("[SMTP_DRY_RUN] 验证码邮件 收件人=%s 验证码=%s（未配置 SMTP，验证码未真实发送）", email, code)
        return True
    try:
        _send_smtp(email, code)
        logger.info("验证码邮件已发送：%s", email)
        return True
    except Exception as exc:
        logger.error("验证码邮件发送失败（%s）：%s", email, exc)
        return False
