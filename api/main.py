# =============================================================================
# 文件总览（面试讲解版）
# =============================================================================
# 【文件层级】项目根目录/api/main.py —— API 层入口（FastAPI 应用装配点）
# 【负责功能】启动/装配整个后端：
#   1. 路径注入：把项目根目录塞进 sys.path，保证任何方式启动都能 import 各模块
#   2. 安全自检：启动前验证 AUTH_ENABLED/JWT_SECRET_KEY/监听地址等硬门槛，
#      不过关拒绝启动（P0 安全闸口）
#   3. 应用装配：CORS 白名单、请求 ID / 请求体上限中间件、统一异常处理器、全部路由
#   4. 静态托管：生产模式下同一个进程托管前端构建产物（SPA 回退）
# 【依赖文件】
#   - config/settings.py（EnvConfig）：全部配置项入口
#   - api/routes/*.py：9 个业务路由模块
#     （datasets/reports/clean/examples/auth/admin/dashboards/shares/feedback）
#   - api/middleware.py：RequestBodyLimitMiddleware / RequestIDMiddleware
#   - api/error_handlers.py：统一异常响应
#   - api/contracts.py：HealthResponse 等响应模型
# 【调用关系】uvicorn 加载本文件 → lifespan 安全自检 + 种子管理员 → 中间件栈 →
#             请求按注册顺序命中具体路由，未命中则落入 SPA 回退路由。
# =============================================================================
from __future__ import annotations
import os
import sys

# 【必须放在所有import最开头】优先注入项目根目录
# __file__ = api/main.py，dirname一次=api文件夹，再dirname=项目根目录
# 【关键行】把项目根目录注入 sys.path——保证无论从哪个目录启动（uvicorn 或直接
# python api/main.py），都能 import 到 config/、services/、api/ 等顶层包。
# 为什么：uvicorn 常从项目根启动，但直接运行本文件时 sys.path[0] 是 api/ 目录，
#         不注入就 import 不到 config.settings 等模块。
# 删除后果：python api/main.py 直接报 ModuleNotFoundError，只有 uvicorn 方式能跑。
# 替代方案：用相对导入（.contracts）——但 uvicorn "api.main:app" 方式不支持
#           相对导入，路径注入是同时兼容两种启动方式的通用做法。
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from contextlib import asynccontextmanager
from datetime import datetime
import logging
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse

from api.contracts import HealthResponse
from api.error_handlers import register_error_handlers
from api.middleware import RequestBodyLimitMiddleware, RequestIDMiddleware
from api.routes import datasets, reports, clean, examples, auth, admin, dashboards, shares, feedback, templates, schedules
from config.settings import EnvConfig

logger = logging.getLogger(__name__)

# 前端静态产物目录：启动器通过 FRONTEND_DIST 环境变量选择
# - 正式构建 frontend/dist（AUTH_REQUIRED=true）
# - 演示构建 frontend/dist-demo（AUTH_REQUIRED=false + 自动加载示例数据）
# 默认值：项目根/frontend/dist（正式构建产物路径）
FRONTEND_DIST = os.getenv("FRONTEND_DIST", str(Path(project_root) / "frontend" / "dist"))


def _解析监听地址() -> str:
    """推断本次启动 uvicorn 将要绑定的 host（用于免认证模式的回环强制）。

    - CLI 方式（python -m uvicorn api.main:app --host X）：取 sys.argv 中的 --host 值；
    - 直接运行（python api/main.py → uvicorn.run(host=EnvConfig.HOST)）：取 EnvConfig.HOST
      （API_HOST 环境变量，默认 127.0.0.1）。
    """
    # 优先从命令行参数找 --host（uvicorn CLI 方式启动时，真正生效的是命令行值）
    for i, arg in enumerate(sys.argv):
        # 同时支持 "--host 0.0.0.0"（空格分隔）与 "--host=0.0.0.0"（等号分隔）两种写法
        if arg == "--host" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith("--host="):
            return arg.split("=", 1)[1]
    # 命令行没指定时，回落到 EnvConfig.HOST（API_HOST 环境变量，默认 127.0.0.1）
    return EnvConfig.HOST


def _启动安全自检() -> None:
    """P0 安全硬门槛：拒绝不安全默认配置启动。

    - AUTH_ENABLED 必须显式设置（true=生产/测试，false=演示/开发），缺省拒绝
      —— 默认关认证会让全站匿名可访问（审计 P0-1）。
    - 认证开启时：JWT_SECRET_KEY 必须是显式非默认强密钥、SEED_ADMIN_PASSWORD
      必须被覆盖（默认 admin123 公开已知）——否则可伪造 token / 直接登录管理员。
    - 认证关闭时（AUTH_ENABLED=false）：只允许绑定回环地址——免认证模式一旦绑到
      0.0.0.0 暴露公网 = 全站无鉴权，直接拒绝启动，物理上杜绝"公网免登录站"。
    """
    auth = os.getenv("AUTH_ENABLED")
    # 【关键行】AUTH_ENABLED 没设置 → 直接拒绝启动。
    # 为什么：认证开关的"没配"和"配了 false"必须严格区分——缺省按关闭处理会让
    #         用户忘记配置时全站匿名可访问（审计 P0-1）；强制显式声明把
    #         "忘记配置"变成"启动失败"而非"裸奔上线"。
    # 删除后果：未配置 AUTH_ENABLED 时服务照常启动且默认免认证，生产事故级隐患。
    # 替代方案：默认 true（安全默认）会让演示部署必须多配一个变量；本项目
    #          演示场景多，选择"显式声明 + 缺省拒绝"两头都堵。
    if auth is None:
        raise RuntimeError(
            "安全拒绝启动：必须显式设置 AUTH_ENABLED=true（生产/测试）或 "
            "AUTH_ENABLED=false（演示/开发）。缺省关闭认证会让全站匿名可访问。"
        )
    # 宽松解析：true/1/yes 都视为开启（兼容 .env 常见写法）
    auth_true = str(auth).lower() in ("true", "1", "yes")
    if auth_true:
        # 【关键行】认证开启时，JWT 密钥必须是显式配置的强密钥。
        # 为什么：JWT 的安全性完全押在密钥上；默认值 "change-me-in-production"
        #         公开写在代码里，任何人可据此伪造管理员 token。
        # 删除后果：带着默认密钥上线 = 攻击者 1 分钟伪造全站任意身份。
        # 替代方案：启动时自动生成随机密钥——但重启后旧 token 全部失效、多实例
        #           不一致；强制显式配置最稳妥。
        secret = os.getenv("JWT_SECRET_KEY") or ""
        if secret in ("", "change-me-in-production"):
            raise RuntimeError(
                "安全拒绝启动：AUTH_ENABLED=true 时 JWT_SECRET_KEY 必须显式配置为强随机密钥，"
                "默认值公开已知可伪造任意 token。"
            )
        # 【关键行】种子管理员密码也必须覆盖默认值。
        # 为什么：admin123 是公开已知的默认口令，不覆盖等于把管理员账号拱手送人；
        #         启动时拦截比上线后补救成本低得多。
        # 删除后果：默认密码的管理员账户可被直接登录，控制台数据全泄露。
        # 替代方案：首次启动强制改密（多一步交互，无人值守部署会卡住）；
        #          当前"配置期拦截"对自动化部署最友好。
        if os.getenv("SEED_ADMIN_PASSWORD", "admin123") in ("", "admin123"):
            raise RuntimeError(
                "安全拒绝启动：AUTH_ENABLED=true 时必须通过 SEED_ADMIN_PASSWORD "
                "覆盖默认管理员密码（admin123 公开已知）。"
            )
    else:
        # 【关键行】免认证模式只允许监听回环地址（127.0.0.1/localhost/::1）。
        # 为什么：AUTH_ENABLED=false = 全站无鉴权，一旦绑到 0.0.0.0 就是公网裸奔；
        #         本机演示场景根本不需要对外网卡，物理上堵死"公网免登录站"。
        # 删除后果：误配 0.0.0.0 时服务照常启动，任何人可通过公网 IP 直接访问
        #         全站数据与操作接口。
        # 替代方案：免认证时动态生成一次性密钥（复杂且演示无收益）；
        #          回环强制是最简单有效的物理隔离。
        host = _解析监听地址()
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError(
                "安全拒绝启动：AUTH_ENABLED=false（免认证）时只允许本机访问，"
                f"监听 host 必须是 127.0.0.1/localhost/::1，当前是 {host!r}。"
            )


# 【函数】FastAPI 生命周期钩子：应用启动前/关闭后各执行一次。
# 入参：app —— FastAPI 应用实例（框架自动注入）
# 返回：异步上下文管理器——yield 前 = 启动初始化，yield 后 = 关闭清理
# 业务定位：所有"进程级初始化"的统一入口，比散落在模块级代码更可控、可测试。
@asynccontextmanager
async def lifespan(app: FastAPI):
    # P0 加固：启动即做安全自检，不通过则进程拒绝启动
    _启动安全自检()
    # 阶段 34 修复：启动即幂等初始化 SQLite 表结构。原因：api.main 模块级
    # `数据集仓储()` 只在首次 import 时建表，测试多模块换临时库、或生产手动
    # 换库路径后，新库会缺 datasets 等表——每次启动都 CREATE IF NOT EXISTS，
    # 确保表一定存在（幂等，重复调用安全）。
    try:
        from 后端_核心.存储 import sqlite_repo
        sqlite_repo.初始化数据库()
    except Exception as exc:
        logger.error("初始化数据库失败：%s", exc)
    # 阶段十三：启动时幂等创建种子管理员（密码来自 EnvConfig，生产务必覆盖默认值）
    try:
        from repositories import user_repo
        from services import auth_service
        # 幂等创建：已存在则跳过，不存在则用配置账号创建；密码以 PBKDF2 哈希形态入库
        user_repo.确保管理员存在(
            EnvConfig.SEED_ADMIN_USERNAME,
            auth_service.hash_password(EnvConfig.SEED_ADMIN_PASSWORD),
        )
    except Exception as exc:
        # 种子管理员创建失败不阻断启动（可能只是库未初始化），记日志便于排查
        logger.error("创建种子管理员失败：%s", exc)
    # 阶段 30：启动定时调度器（daemon 线程，每 30s tick 一次，到点自动执行模板）
    try:
        from services.scheduler import 启动调度器
        启动调度器()
    except Exception as exc:
        logger.error("调度器启动失败（定时任务不可用，不影响手动生成）：%s", exc)
    yield
    # TODO: 关闭时清理连接


# 创建应用实例：title/version 会展示在 /docs 与 /openapi.json；lifespan 绑定启动流程
app = FastAPI(
    title="自助式数据分析 Agent 平台",
    description="基于 FastAPI 的文件上传数据分析与可视化报表平台",
    version=EnvConfig.API_VERSION,
    lifespan=lifespan,
)

# 【关键行】CORS 白名单：只允许 EnvConfig.CORS_ORIGINS 里列出的前端域名跨域访问。
# 为什么：浏览器同源策略下，未列入白名单的站点发来的请求会被浏览器拦截；早期用
#         "*" 通配符 + allow_credentials=True——规范禁止两者组合（带凭证请求不允许
#         通配来源），浏览器会直接拒绝，且通配等于"任何恶意站点都能以登录用户
#         身份调接口"（放大 CSRF 攻击面）。
# 删除后果：要么任意站点都能跨域调用本 API（凭证场景下等于给钓鱼站开后门），
#           要么去掉凭证后登录态丢失，前端全部接口报错。
# 替代方案：不加 CORS（同源部署）最安全但要求前后端同源托管；
#          显式白名单 + 凭证组合是"前后端分离部署"下的标准平衡解。
app.add_middleware(
    CORSMiddleware,
    # P0 加固：通配符 + credentials 组合违规；改为显式白名单（EnvConfig.CORS_ORIGINS）
    allow_origins=EnvConfig.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 中间件注册顺序说明（FastAPI/Starlette 中间件是"后注册先执行"的栈）：
# 实际请求链路 = RequestBodyLimit → RequestID → CORS → 路由处理器。
# request_id 中间件：放在最外层，保证所有请求都有 request_id
app.add_middleware(RequestIDMiddleware)
# P0 加固：请求体上限中间件（放最外层，先于业务处理拦截超大 body）
# 超大请求体在进入任何业务逻辑前就被 413 拦截，避免恶意大包占满内存/带宽
app.add_middleware(RequestBodyLimitMiddleware)

# 统一错误响应：注册异常处理器
register_error_handlers(app)


# 【函数】健康检查接口：部署/启动器探活用（启动.ps1 轮询它判断后端就绪）。
# 入参：无
# 返回：HealthResponse —— {status: "ok", version, timestamp}
# 业务定位：无业务逻辑、无需认证，只回答"进程活着吗、版本多少"。
@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=EnvConfig.API_VERSION,
        timestamp=datetime.now(),
    )

# 注册 9 个业务路由模块：顺序即 /docs 文档中的展示顺序；FastAPI 按注册顺序
# 匹配请求，具体路由总是先于末尾的 SPA 回退路由命中，互不干扰
app.include_router(datasets.router)
app.include_router(reports.router)
app.include_router(clean.router)
app.include_router(examples.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(dashboards.router)
app.include_router(shares.router)
app.include_router(feedback.router)
app.include_router(templates.router)
app.include_router(schedules.router)


# 【函数】SPA 回退路由：托管前端构建产物 + 兜底所有未命中路径。
# 入参：full_path —— URL 路径（不含域名）；request —— 完整请求对象（用于判断 HTTP 方法）
# 返回：FileResponse（静态资源，带缓存头）或 HTMLResponse（index.html，禁缓存）
# 业务定位：让"一个后端进程同时服务 API + 前端页面"，零基础用户无需安装 Node；
#           必须最后注册，否则会吞掉所有具体路由。
@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
async def spa_fallback(full_path: str, request: Request):
    """托管前端构建产物 + SPA 路由回退。

    放在所有 API 路由之后注册，因此 /health、/auth、/datasets、/reports 等
    具体路由优先匹配；其余 GET 路径（/data、/analysis、/report/xxx 等）返回
    前端 index.html，由 React Router 接管。非 GET 方法且未命中任何路由时
    返回 404（与无 catch-all 时的行为一致）。这样只需要一个后端进程即可
    完整运行，零基础用户无需安装 Node。
    """
    if request.method != "GET":
        raise HTTPException(status_code=404, detail="Not Found")
    dist = Path(FRONTEND_DIST).resolve()
    if not dist.is_dir():
        raise HTTPException(status_code=404, detail="前端构建产物不存在，请先运行构建")
    if full_path:
        target = (dist / full_path).resolve()
        # 路径穿越防护：目录边界校验（P0 加固：startswith 是字符串前缀匹配，
        # 可命中 dist 前缀兄弟目录；is_relative_to 是真正的路径边界判断）
        if target.is_file() and target.is_relative_to(dist):
            # hash 文件名内容指纹：可安全长缓存（浏览器内容变了 hash 自动变）
            if full_path.startswith("assets/") or "/assets/" in "/" + full_path:
                return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable"})
            # 非 hash 文件（favicon.svg / icons.svg 等）无指纹：禁启发式缓存，每次回源
            return FileResponse(target, headers={"Cache-Control": "no-cache"})
    index = dist / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="前端构建产物不存在，请先运行构建")
    # HTML 永不缓存：no-store 禁止浏览器/代理保存任何副本（no-cache 依赖
    # 重新验证，个别浏览器/代理实现不遵守导致旧版 HTML 残留），
    # 每次访问必须回源拿到最新构建（引用新 hash 资源）
    return HTMLResponse(
        index.read_text(encoding="utf-8"),
        media_type="text/html",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


# 直接运行本文件（python api/main.py）时的入口：等价于 uvicorn api.main:app
#（由 uvicorn 命令启动时不走这里，host/port 由命令行参数决定）
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=EnvConfig.HOST,
        port=EnvConfig.PORT,
    )
