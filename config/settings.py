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

    # JWT 认证配置（阶段 3）
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "60"))

    # LLM provider 白名单（阶段 5）：用户只能选 provider+model，不能传任意 URL/Key
    # 结构：provider -> {base_url, default_model, models: [可选模型列表]}
    LLM_PROVIDERS = {
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "default_model": "deepseek-chat",
            "models": ["deepseek-chat", "deepseek-reasoner"],
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-4o-mini",
            "models": ["gpt-4o-mini", "gpt-4o"],
        },
        "siliconflow": {
            "base_url": "https://api.siliconflow.cn/v1",
            "default_model": "Qwen/Qwen2.5-7B-Instruct",
            "models": [],
        },
    }


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
