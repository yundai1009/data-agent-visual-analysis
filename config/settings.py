# config/settings.py
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"

# 自动读取项目根目录 .env；系统环境变量优先级更高，不会被 .env 覆盖。
load_dotenv(dotenv_path=ENV_FILE, override=False)


class EnvConfig:
    # API 基础配置
    API_VERSION = os.getenv("API_VERSION", "0.1.0")
    HOST = os.getenv("API_HOST", "127.0.0.1")
    PORT = int(os.getenv("API_PORT", "8000"))

    # OpenAI-compatible LLM 配置；用于后续自然语言增强，当前上传报表主链路不强制依赖。
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0"))

    # SQLite 持久化配置（阶段 2）
    # - 默认落在 PROJECT_ROOT/data/daa.db
    # - 可用环境变量 DAA_SQLITE_PATH 覆盖
    # - 该文件已加入 .gitignore，不会提交
    SQLITE_PATH = os.getenv(
        "DAA_SQLITE_PATH",
        str(PROJECT_ROOT / "data" / "daa.db"),
    )

    # 认证开关：开发阶段设为 false 可免 token 访问
    AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() in ("true", "1", "yes")

    # SMTP 邮件（阶段十三：邮箱验证码注册）
    # 未配置 SMTP_HOST 或 SMTP_DRY_RUN=true 时，验证码不真发邮件，打印到后端日志（本地调试可用）
    SMTP_HOST = os.getenv("SMTP_HOST", "")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASS = os.getenv("SMTP_PASS", "")
    SMTP_FROM = os.getenv("SMTP_FROM", "")
    SMTP_DRY_RUN = os.getenv("SMTP_DRY_RUN", "false").lower() in ("true", "1", "yes")

    # 种子管理员（阶段十三）：启动时幂等创建；生产环境务必通过 SEED_ADMIN_PASSWORD 覆盖默认密码
    SEED_ADMIN_USERNAME = os.getenv("SEED_ADMIN_USERNAME", "admin")
    SEED_ADMIN_PASSWORD = os.getenv("SEED_ADMIN_PASSWORD", "admin123")

    # JWT 认证配置（阶段 3）
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

    # LLM provider 白名单（阶段 5）：用户只能选 provider+model，不能传任意 URL/Key
    # 结构：provider -> {base_url, default_model, models: [可选模型列表]}
    # 阶段 13.5：provider 配置外置到 config/providers.toml（参考 Reasonix 接入方式，
    # 支持任意 OpenAI 兼容 provider + api_key_env），文件不存在时回退内置默认。
    # 注意：此赋值在类体末尾（_加载LLMProviders 定义之后）执行。

    @staticmethod
    def _加载LLMProviders() -> Dict[str, Any]:
        import logging
        import os
        from pathlib import Path as _Path
        _log = logging.getLogger(__name__)
        _file = _Path(__file__).resolve().parents[1] / "config" / "providers.toml"
        if _file.exists():
            try:
                import tomllib
                with open(_file, "rb") as fh:
                    data = tomllib.load(fh)
                out: Dict[str, Any] = {}
                for p in data.get("providers", []):
                    name = (p.get("name") or "").strip()
                    # 本期仅支持 OpenAI 兼容协议（anthropic 后续扩展）
                    if not name or p.get("kind", "openai") != "openai":
                        continue
                    out[name] = {
                        "base_url": p["base_url"],
                        "default_model": p.get("default", "") or "",
                        "models": list(p.get("models") or []),
                        "api_key_env": p.get("api_key_env") or "",
                        "balance_url": p.get("balance_url") or "",
                    }
                if out:
                    _log.info("已从 providers.toml 加载 %d 个 LLM provider", len(out))
                    return out
                _log.warning("providers.toml 无可用 provider，回退内置默认")
            except Exception as exc:
                _log.error("解析 providers.toml 失败，回退内置默认: %s", exc)
        # 内置默认（回退）
        return {
            "deepseek": {
                "base_url": "https://api.deepseek.com/v1",
                "default_model": "deepseek-chat",
                "models": ["deepseek-chat", "deepseek-reasoner"],
                "api_key_env": "DEEPSEEK_API_KEY",
            },
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "default_model": "gpt-4o-mini",
                "models": ["gpt-4o-mini", "gpt-4o"],
                "api_key_env": "OPENAI_API_KEY",
            },
            "siliconflow": {
                "base_url": "https://api.siliconflow.cn/v1",
                "default_model": "Qwen/Qwen2.5-7B-Instruct",
                "models": [],
                "api_key_env": "SILICONFLOW_API_KEY",
            },
        }


# 类定义完成后加载 provider 配置（_加载LLMProviders 此时已定义）
EnvConfig.LLM_PROVIDERS = EnvConfig._加载LLMProviders()


@dataclass(frozen=True)
class LLMRequestConfig:
    """请求级 LLM 配置（并发安全，阶段 12 收尾）。

    每次生成报表时由服务端根据用户选择的 provider+model 构建，并沿调用链显式传递，
    取代「临时覆盖全局 EnvConfig.LLM_BASE_URL / LLM_MODEL」的旧做法：
    - 无并发污染：不同请求互不干扰，也不依赖 try/finally 还原全局变量；
    - 显式传参：调用链上每个环节都能看到本次请求实际使用的配置；
    - api_key 始终来自服务端 .env（EnvConfig.LLM_API_KEY），不接收用户输入。
    """

    provider: str
    base_url: str
    model: str = ""
    api_key: str = ""
