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
from api.routes import datasets, reports, clean, examples, auth, admin, dashboards, shares, feedback, templates, schedules, search
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


def _解析workers() -> int:
    """推断本次启动 uvicorn 打算起几个 worker（用于向量记忆的单进程约束）。

    - CLI 方式（python -m uvicorn api.main:app --workers 4）：解析 sys.argv；
    - 其他一切方式（uvicorn.run(workers=N) / UVICORN_WORKERS 环境变量 / gunicorn
      / k8s 多个副本）在本函数里都看不到，统一按 1 处理——宁可少拦，也绝不宣称
      「绝对拦截」（见 _启动安全自检 第 5 道防线的文案）。
    - 非法值（如 --workers abc）同样按 1 处理：不因为一个打错的参数拒绝启动。
    - 非 uvicorn 启动形态（阶段 61 修复 M1）直接按 1 返回，见下方【关键行】。
    """
    # 【关键行】只有 sys.argv 里确实有 uvicorn 启动痕迹时才解析。
    # 为什么：sys.argv 是**进程级**全局量，pytest 进程的 argv 就是 pytest 的参数。
    #   装了 pytest-parallel（它的开关恰好也叫 --workers）或手写
    #   `pytest tests --workers 4` 时，本函数会误判成「多 worker 启动」，
    #   于是每个 TestClient 用例都在 lifespan 里被「安全拒绝启动」，而且报错
    #   指向 chromadb/向量记忆，与真实故障毫无关系——排查成本极高。
    #   非 uvicorn 启动本来就看不到真实 worker 数（本函数只能读 CLI），按 1 处理
    #   不会漏掉任何它原本能拦的情况。
    argv = [str(a) for a in sys.argv]
    uvicorn形态 = "uvicorn" in os.path.basename(argv[0] if argv else "") or any(
        "uvicorn" in a for a in argv[:3]  # `uvicorn ...` / `python -m uvicorn ...` 两种前缀
    )
    if not uvicorn形态:
        return 1
    for i, arg in enumerate(sys.argv):
        if arg == "--workers" and i + 1 < len(sys.argv):
            try:
                return max(1, int(sys.argv[i + 1]))
            except ValueError:
                return 1
        if arg.startswith("--workers="):
            try:
                return max(1, int(arg.split("=", 1)[1]))
            except ValueError:
                return 1
    return 1


def _启动安全自检() -> None:
    """P0 安全硬门槛：拒绝不安全默认配置启动。

    - AUTH_ENABLED 必须显式设置（true=生产/测试，false=演示/开发），缺省拒绝
      —— 默认关认证会让全站匿名可访问（审计 P0-1）。
    - 认证开启时：JWT_SECRET_KEY 必须是显式非默认强密钥、SEED_ADMIN_PASSWORD
      必须被覆盖（默认 admin123 公开已知）——否则可伪造 token / 直接登录管理员。
    - 认证关闭时（AUTH_ENABLED=false）：只允许绑定回环地址——免认证模式一旦绑到
      0.0.0.0 暴露公网 = 全站无鉴权，直接拒绝启动，物理上杜绝"公网免登录站"。
    - 阶段 61 新增第 5 道：--workers > 1 拒绝启动（向量记忆是嵌入式单进程库）。
    - 阶段 61 新增第 6 道：记忆库 embedding 指纹与当前配置不同源 → 拒绝启动
      （只是「库打不开」则放行，记忆是可降级依赖）。
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

    # 第 5 道防线（阶段 61 决策 D5）：向量记忆是嵌入式单进程库，多 worker 拒绝启动。
    # 【关键行】--workers > 1 直接拒绝启动。
    # 为什么：chromadb.PersistentClient 是嵌入式 sqlite + 内存索引，每个进程各写一份；
    #         并发写会互相破坏索引，而失败方式一样只是 logger.warning——监控全绿，
    #         只是记忆慢慢变得不准（最隐蔽的一类故障）。
    # 替代方案：换 Qdrant/pgvector 服务端向量库（多进程安全，但部署成本上台阶）。
    # 局限（必须如实说明）：本闸门只能解析 CLI 的 --workers，CLI 尽力而为。
    #         以下三种启动方式都会绕过它——代码里写 uvicorn.run(workers=N)、
    #         环境变量 UVICORN_WORKERS=4、gunicorn -w 4 / k8s 多副本。
    #         它们需要各自显式处理（不要给这些方式开向量记忆）。
    workers = _解析workers()
    if workers > 1:
        raise RuntimeError(
            f"安全拒绝启动：检测到 --workers {workers}，向量记忆暂不支持多 worker。\n"
            "原因：chromadb 是嵌入式单进程库，多进程并发写会破坏索引，且故障只表现为"
            "「记忆慢慢不准」，监控上完全看不见。\n"
            "本闸门是 CLI 尽力而为，不是绝对拦截——代码里写 uvicorn.run(workers=N)、"
            "环境变量 UVICORN_WORKERS=4、gunicorn -w 4 / k8s 多副本都会绕过它，"
            "用这些方式启动时必须自行确认。\n"
            "怎么办：① 用 --workers 1 启动（推荐）；或 ② 清空 embedding Key"
            "（LLM_EMBEDDING_API_KEY / LLM_API_KEY 都留空）让记忆链路整体不读写——"
            "此时第 6 道指纹闸也会一并跳过，不会再撞上拒绝启动；或 ③ 换成服务端向量库"
            "（Qdrant / pgvector），它们本身支持多进程。"
        )

    # 第 6 道防线（阶段 61 决策 D4）：记忆库 embedding 指纹必须与当前配置同源。
    # 【关键行】指纹不一致 → 走与上面同样的「安全拒绝启动」通道。
    # 为什么必须硬失败：换了 embedding 模型/端点/向量化文本模板后，旧向量与新查询
    #         向量不在同一语义空间。维度不同时查询抛异常被吞（检索恒空）；
    #         维度相同时**完全不报错**，只是结果全是噪声。
    # 降级边界：「打开记忆库本身失败」（磁盘满/权限/锁文件）不拦截启动——记忆是
    #         非关键依赖，只记 warning 并在 /healthz.memory 里暴露，交给运维处理。
    try:
        from 后端_核心.agent.llm_client import embedding_settings, is_llm_configured
        from 后端_核心.agent.memory import 校验记忆库一致性

        # 【关键行】embedding Key 为空 = 记忆链路整体不读写 → 跳过指纹校验。
        # 为什么（阶段 61 修复 M2，审查指出的自相矛盾）：指纹里**不含** Key
        #   （含 Key 会把轮换密钥误判成"换了模型"，见 memory.当前指纹），
        #   所以上面第 5 道防线的自救建议②"清空 embedding Key 关记忆"在旧实现下
        #   根本走不通：只删 Key 而 LLM_BASE_URL 仍配置时，指纹会回落到
        #   LLM_BASE_URL + 默认模型，反而更容易撞上第 6 道拒绝启动。
        #   语义上也不该拦：Key 为空时 保存记忆/检索相似记忆 全部早退，
        #   不存在"新旧向量不同源"的问题，硬拦只会把一个可降级依赖变成启动故障。
        # 删除后果：按文案②自救的用户被卡在启动阶段，只能删库（丢全部长期记忆）。
        _, _, embedding_key = embedding_settings()
        if not is_llm_configured(embedding_key):
            logger.info(
                "embedding Key 未配置：记忆链路整体不读写，跳过第 6 道指纹校验"
                "（记忆降级为「未启用」，不影响分析主流程）"
            )
        else:
            校验记忆库一致性()
    except RuntimeError as exc:
        raise RuntimeError(f"安全拒绝启动：{exc}") from exc
    except Exception as exc:
        # 记忆库打不开属于可降级故障：让服务起来，只是记忆不可用
        logger.warning("向量记忆库一致性检查未通过（不影响分析主流程）: %s", exc)


# 【函数】FastAPI 生命周期钩子：应用启动前/关闭后各执行一次。
# 入参：app —— FastAPI 应用实例（框架自动注入）
# 返回：异步上下文管理器——yield 前 = 启动初始化，yield 后 = 关闭清理
# 业务定位：所有"进程级初始化"的统一入口，比散落在模块级代码更可控、可测试。
@asynccontextmanager
async def lifespan(app: FastAPI):
    # P0 加固：启动即做安全自检，不通过则进程拒绝启动
    _启动安全自检()
    # 阶段 54-8 修复：启动即幂等初始化表结构（按 DB_BACKEND 分发：sqlite→sqlite_repo；
    # mysql→mysql_repo）。原因：api.main 模块级 `数据集仓储()` 只在首次 import 时建表，
    # 测试多模块换临时库、或生产手动换库路径后，新库会缺 datasets 等表——每次启动都
    # CREATE IF NOT EXISTS，确保表一定存在（幂等，重复调用安全）。
    try:
        from 后端_核心.存储.连接 import 初始化数据库
        初始化数据库()
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

# 【函数】深度健康检查：后端类型 + 数据库连通性 + 向量记忆状态（部署探活升级版）。
# 返回：{"status", "db_backend", "db_ok", "memory"} —— status=ok 表示进程与库都健康；
#       degraded 表示进程活着但库连不上（供负载均衡摘除/告警）。
# 阶段 61（决策 D8）：新增 memory 段——记忆故障原来只有 warning，运维看不见。
# 关键取舍：**memory.ok=False 不影响顶层 status**。记忆是非关键依赖（关掉它
#       分析主流程照跑），因为它坏了就把实例从负载均衡摘掉不划算；
#       交给"人看 /healthz.memory"比交给"机器摘节点"更合适。
# 阶段 61 修复 M3：本路由改成**同步 def**（FastAPI 自动丢到线程池执行）。
# 为什么：路由体里**一个 await 都没有**，却全是阻塞 IO——sqlite/mysql 的
#   connect+execute，以及 记忆状态() 里的 chroma `col.count()`（嵌入式 sqlite +
#   可能触发索引加载）。async def 会让 FastAPI 直接在**事件循环线程**里执行它们，
#   探活一卡就是整个后端全部接口一起卡住（历史上真发生过：开发日志
#   docs/开发日志/项目开发日志.md:4536-4537 记录 /healthz 把接口从 2241ms
#   拖到 2.7s，:4674、:4716 是同一条线的后续）。
# 为什么不是"加个 await 或包线程池"：这里没有需要让出的异步 IO；同步 def 由
#   Starlette 自动 `run_in_threadpool`，语义上正好表达"这活儿是阻塞的"。
# 删除后果：并发探活/启动器轮询时，记忆库 count() 的几百毫秒会冻结事件循环。
@app.get("/healthz")
def healthz():
    from 后端_核心.存储 import backend as 存储后端
    后端名 = 存储后端.当前后端()
    db_ok = False
    try:
        if 后端名 == "mysql":
            from 后端_核心.存储 import mysql_backend
            with mysql_backend.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
        else:
            from 后端_核心.存储 import sqlite_backend
            with sqlite_backend.get_conn() as conn:
                conn.execute("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False
    memory_info: dict = {"ok": False, "原因": "未查询"}
    try:
        from 后端_核心.agent.memory import 记忆状态
        memory_info = 记忆状态()
    except Exception as exc:
        # 探活本身不能因记忆模块出错而 500：兜底成 ok=False + 原因
        memory_info = {"ok": False, "原因": f"查询失败: {exc}"}
    return {
        "status": "ok" if db_ok else "degraded",
        "db_backend": 后端名,
        "db_ok": db_ok,
        "memory": memory_info,
    }

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
app.include_router(search.router)


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
    # 【Bug33 修复】路径带 /api/ 前缀或显式 API 风格路径时，不走 SPA 回退——
    # 旧实现把所有未命中 GET 都返回 index.html，前端拼错的 API 路径（如
    # /reports/xxx 实际不存在）拿到 200+HTML，res.json() 解析失败产生误导性报错。
    if full_path.startswith("api/") or full_path.startswith("auth/") or full_path.startswith("datasets/"):
        raise HTTPException(status_code=404, detail="接口不存在")
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
