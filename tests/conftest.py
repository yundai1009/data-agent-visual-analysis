# 测试环境 P0 启动自检要求（conftest 最先加载，先于 config.settings 的 load_dotenv）：
# AUTH_ENABLED/JWT_SECRET_KEY/SEED_ADMIN_PASSWORD 必须显式非默认，否则 api.main lifespan
# 的 _启动安全自检() 会拒绝启动。
import os

os.environ["AUTH_ENABLED"] = "true"
os.environ["JWT_SECRET_KEY"] = "test-secret-0123456789abcdef0123456789abcdef"
os.environ["SEED_ADMIN_PASSWORD"] = "test-admin-password"
