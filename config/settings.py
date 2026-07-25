# config/settings.py
from __future__ import annotations

import os
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
