"""config 包：应用配置。

settings.py 从环境变量/ .env 加载全部配置（数据库、JWT、LLM、SMTP 等），
全项目通过 config.settings.EnvConfig 统一读取，避免散落的魔法值。
"""