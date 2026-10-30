# 测试环境 P0 启动自检要求（conftest 最先加载，先于 config.settings 的 load_dotenv）：
# AUTH_ENABLED/JWT_SECRET_KEY/SEED_ADMIN_PASSWORD 必须显式非默认，否则 api.main lifespan
# 的 _启动安全自检() 会拒绝启动。
import os
import tempfile

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"
# 测试一律跑 sqlite：生产 .env 现在写的是 DB_BACKEND=mysql，若不在这里压住，
# load_dotenv(override=False) 会让整套用例连上真实 daa 库、往生产数据里写测试行。
# load_dotenv 不覆盖已有 os.environ，所以本文件（先于 config.settings 导入）先设值即可。
os.environ["DB_BACKEND"] = "sqlite"
# 测试环境禁用真实 LLM：占位 key 使 is_llm_configured() 返回 False，
# 全链路走确定性规则降级（不依赖真实网络/Key，测试快且可复现）。
# 需要验证 LLM 行为的用例自行 monkeypatch chat_completion 或显式设置 EnvConfig.LLM_API_KEY。
os.environ["LLM_API_KEY"] = "your_llm_api_key"

# 向量记忆库重定向到系统临时目录（阶段 61 Task 3）：memory.py:53 在**导入时**读 DAA_CHROMA_PATH，
# 不设就会回落到仓库内的 data/chroma_db——跑一次测试就污染真实记忆库。
# 用 mkdtemp（每次唯一）而不是固定路径：固定路径会让上一次运行的残留影响下一次断言。
os.environ["DAA_CHROMA_PATH"] = tempfile.mkdtemp(prefix="daa_chroma_test_")
