# 测试环境 P0 启动自检要求（conftest 最先加载，先于 config.settings 的 load_dotenv）：
# AUTH_ENABLED/JWT_SECRET_KEY/SEED_ADMIN_PASSWORD 必须显式非默认，否则 api.main lifespan
# 的 _启动安全自检() 会拒绝启动。
import os

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"
# 测试环境禁用真实 LLM：占位 key 使 is_llm_configured() 返回 False，
# 全链路走确定性规则降级（不依赖真实网络/Key，测试快且可复现）。
# 需要验证 LLM 行为的用例自行 monkeypatch chat_completion 或显式设置 EnvConfig.LLM_API_KEY。
os.environ["LLM_API_KEY"] = "your_llm_api_key"
