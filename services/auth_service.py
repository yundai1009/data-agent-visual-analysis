"""认证服务：密码哈希 + JWT 签发/校验。

为什么用标准库而非 passlib/python-jose
======================================
- passlib 已停止维护，python-jose 依赖 cryptography 安装较重
- PBKDF2-HMAC-SHA256 是标准 KDF，安全性足够（迭代 100k 次）
- JWT HS256 用 hmac 标准库即可实现，签名逻辑清晰可审计
- 零新增依赖，降低部署风险

安全性说明
==========
- 密码用 PBKDF2 加盐哈希，盐随机生成 16 字节，迭代 100_000 次
- JWT 密钥从 EnvConfig.JWT_SECRET_KEY 读取，不硬编码
- token 过期时间由 EnvConfig.JWT_EXPIRE_MINUTES 控制
"""

# =============================================================================
# 文件总览（面试讲解版）
# =============================================================================
# 【文件层级】项目根目录/services/auth_service.py —— 服务层，被 api 层调用
# 【负责功能】三项认证核心能力：
#   1. 密码哈希：PBKDF2-HMAC-SHA256 加盐慢哈希（注册/改密存库）与校验（登录比对）
#   2. JWT 签发与校验：基于标准库 hmac 自实现的 HS256 签名，零第三方依赖
#   3. 用户 ID 生成：密码学安全随机 ID
# 【依赖文件】
#   - config/settings.py（EnvConfig）：读取 JWT_SECRET_KEY / JWT_EXPIRE_MINUTES
#   - 被 api/dependencies.py、api/routes/auth.py 等上层模块调用
# 【调用关系】登录路由 → hash_password/verify_password → create_access_token
#             → 受保护路由 → get_current_user → verify_access_token
# =============================================================================

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional

# PBKDF2 迭代次数：OWASP 建议 SHA-256 至少 60 万次，此处取 10 万次平衡速度与安全
_PBKDF2_ITERATIONS = 100_000
# 盐长度 16 字节 = 128 bit：与哈希输出等长，足以让彩虹表/碰撞攻击失效
_SALT_BYTES = 16

# 默认 JWT 密钥（生产必须用 .env 覆盖）
# 该兜底值仅保证"没配密钥也能本地跑通"；生产环境此值会被 main.py 的安全自检直接拒绝
_DEFAULT_JWT_SECRET = "change-me-in-production"


# 【函数】读取 JWT 签名密钥：优先取 EnvConfig.JWT_SECRET_KEY，缺失时退回默认值。
# 入参：无
# 返回：str —— 签名密钥原文（签发与校验共用同一把钥匙）
# 业务定位：JWT 全部签/验都依赖这一个密钥——密钥泄露 = 可伪造任意用户 token，
#           因此生产环境由 main.py 安全自检强制要求显式配置强密钥。
def _get_secret() -> str:
    from config.settings import EnvConfig
    # getattr 防御性取值：配置类缺字段时退到模块级默认值，保证本地可跑
    return getattr(EnvConfig, "JWT_SECRET_KEY", "") or _DEFAULT_JWT_SECRET


# ---- 密码哈希 ----------------------------------------------------------------


# 【函数】对明文密码做 PBKDF2 加盐慢哈希，返回可持久化的自描述字符串。
# 入参：password —— 用户明文密码（只短暂存在于内存，不落库、不打日志）
# 返回：str —— 格式 "pbkdf2$迭代次数$盐(base64)$哈希(base64)"；盐和算法参数随结果
#              一起存储，校验时无需额外记录"当初用了多少次迭代"，未来升级迭代
#              次数时旧哈希仍可校验（格式自包含）。
# 业务定位：注册/改密时调用，把明文密码变成数据库中保存的唯一形态；
#           数据库中永远不会出现明文密码。
def hash_password(password: str) -> str:
    """PBKDF2 加盐哈希，返回格式：pbkdf2$iterations$salt_b64$hash_b64"""
    # 【关键行】生成 16 字节随机盐：每次哈希的盐都不同，同一密码两次哈希结果不同。
    # 为什么：无盐哈希可被彩虹表（预计算"密码→哈希"映射表）秒破；随机盐让每个
    #         用户的哈希都独一无二，彩虹表失效，还能抵御跨库撞库。
    # 删除后果：改为固定盐或无盐后，相同密码得到相同哈希，泄露库可直接查表批量破解。
    # 替代方案：secrets.token_bytes(16) 与 os.urandom 同为密码学安全随机源，等价；
    #          盐必须每次随机生成，任何"固定盐"方案安全价值都归零。
    salt = os.urandom(_SALT_BYTES)
    # 【关键行】PBKDF2 慢哈希：把"迭代 10 万次"的累计耗时作为密码的安全成本。
    # 为什么：攻击者暴力破解时也要付出同等 10 万倍开销，拖慢 GPU/ASIC 批量尝试；
    #         同时每次迭代都混入盐与上轮结果，输出不可逆。
    # 删除后果：换成单次 SHA256(password+salt)，攻击者每秒可试数百万个密码，
    #           8 位弱口令在分钟级内被穷举，等于明文存储。
    # 替代方案：bcrypt/scrypt/argon2（内存难型，抗专用硬件更强，但需第三方库、
    #          部署更重）；标准库 PBKDF2 零依赖、可审计，满足本项目安全水位。
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    # 拼出自描述哈希串：算法名/迭代次数/盐/哈希一次打包，库里只存这一个字段
    return "pbkdf2${}${}${}".format(
        _PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


# 【函数】登录时校验明文密码与库里存储的哈希是否匹配。
# 入参：password —— 用户本次输入的明文密码；
#       stored_hash —— 库里存的 "pbkdf2$迭代次数$盐$哈希" 字符串
# 返回：bool —— True=匹配通过 / False=不匹配（含格式损坏、算法不符等任何异常）
# 业务定位：登录接口的核心比对动作；任何异常都返回 False 而非抛错，
#           避免把哈希内部格式等实现细节泄露给调用方/前端。
def verify_password(password: str, stored_hash: str) -> bool:
    """校验密码。stored_hash 格式不合法时返回 False（不抛异常）。"""
    try:
        # 拆出哈希串的四个组成部分：算法名/迭代次数/盐/期望哈希
        scheme, iterations_str, salt_b64, hash_b64 = stored_hash.split("$")
        # 算法标识不符（老数据、未知格式）一律视为校验失败
        if scheme != "pbkdf2":
            return False
        iterations = int(iterations_str)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
    except (ValueError, TypeError):
        # 拆包失败/数字非法/base64 损坏：统一当作无效哈希处理
        return False
    # 用库里记录的盐和迭代次数，对本次输入重新做一遍 PBKDF2（与注册时完全同参数）
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    )
    # 【关键行】恒定时间比较：无论两串差异在哪、差多少位，耗时都恒定。
    # 为什么：普通 == 遇到第一个不同字节就提前返回，耗时随"猜对前缀长度"变化，
    #         攻击者可逐字节探测出哈希值（时序侧信道攻击）；compare_digest
    #         保证整串比较耗时一致，从时间上榨不出任何信息。
    # 删除后果：理论上可被远程时序攻击逐步还原哈希，再配合字典离线破解密码。
    # 替代方案：标准库无更优选择；关键是绝不能写成可提前短路的逐字节比较。
    return hmac.compare_digest(digest, expected)


# ---- JWT --------------------------------------------------------------------


# 【函数】标准 Base64URL 编码（JWT 规范）：把 + / 换成 - _，并去掉尾部 = 填充。
# 入参：data —— 待编码的原始字节
# 返回：str —— 不含填充符的 URL 安全字符串（JWT 三段式要求各段不含 +/= 字符）
# 业务定位：JWT 头/载荷/签名的通用编码工具，签发与校验两端共用。
def _b64url_encode(data: bytes) -> str:
    # rstrip(b"=") 去掉填充：JWT 约定省略填充符，解码端自行补回
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# 【函数】标准 Base64URL 解码（_b64url_encode 的逆操作）。
# 入参：data —— JWT 中取出的无填充 Base64URL 字符串
# 返回：bytes —— 还原后的原始字节
# 业务定位：校验端把签名与载荷从字符串还原为字节/JSON。
def _b64url_decode(data: str) -> bytes:
    # 按长度补齐 "=" 填充（len%4 余 1/2/3 分别补 3/2/1 个等号）再解码
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# 【函数】生成 JWT 头：声明签名算法 HS256（HMAC-SHA256 对称签名）、类型 JWT。
# 入参：无
# 返回：str —— Base64URL 编码后的 JSON 头
# 业务定位：JWT 三段中的第一段，明文可见、无敏感信息，只告诉验票方"用哪个算法验"。
def _jwt_header() -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    # separators 压缩 JSON 空格：减小 token 体积（header/payload 都会进 URL/请求头）
    return _b64url_encode(json.dumps(header, separators=(",", ":")).encode())


# 【函数】签发 JWT access token（登录成功后的"通行证"）。
# 入参：user_id —— 用户唯一标识，写入 sub 声明（吊销对账的主键）；
#       role —— 角色（admin/analyst），写入载荷供鉴权直接用；
#       username —— 用户名冗余携带，省去每请求查库；
#       expires_minutes —— 覆盖全局过期时长，None 时用 EnvConfig.JWT_EXPIRE_MINUTES；
#       token_version —— 当前用户的 token 版本号（P1 加固），吊销对账的依据
# 返回：str —— 形如 "头.载荷.签名" 的三段式 JWT 字符串
# 业务定位：登录/注册成功后的唯一发证入口；JWT 无状态、服务端不保存会话，
#           吊销只能靠版本号对账（见 api/dependencies.py 的 get_current_user）。
def create_access_token(
    user_id: str,
    role: str,
    username: str = "",
    expires_minutes: Optional[int] = None,
    token_version: int = 0,
) -> str:
    """签发 JWT access token（P1 加固：载荷带 token_version 供吊销校验）。"""
    from config.settings import EnvConfig
    # 过期时长取值优先级：显式入参 > 全局配置（默认 60 分钟）
    minutes = expires_minutes or getattr(EnvConfig, "JWT_EXPIRE_MINUTES", 60)
    now = int(time.time())
    # 载荷：sub=用户ID、ver=token版本号、iat=签发时间、exp=过期时间戳（Unix 秒）。
    # 所有字段都可被接收方离线验真——这就是 JWT 无状态的核心前提。
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "ver": int(token_version or 0),
        "iat": now,
        "exp": now + int(minutes) * 60,
    }
    header = _jwt_header()
    # 载荷序列化后同样做 Base64URL 编码：JWT 三段全部是 URL 安全字符串
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    # 待签名原文 = "头.载荷"：签名只覆盖这两段，与标准 JWT 完全一致
    signing_input = f"{header}.{payload_b64}".encode()
    # 【关键行】HS256 签名：用服务器密钥对"头.载荷"做 HMAC-SHA256，结果作为第三段。
    # 为什么：签名 = 服务器独有的防伪印章。攻击者不知道密钥就无法伪造合法签名，
    #         也无法篡改载荷（改任意一个字符，重算签名就对不上）。
    # 删除后果：token 失去防伪能力——任何人都能自造 payload（冒充 admin、把 exp
    #           改成 9999 年），认证体系彻底失效。
    # 替代方案：RS256 非对称（私钥签、公钥验，适合多服务各自验签）但要管理密钥对；
    #          HS256 对称密钥在"单服务签发+单服务校验"场景更简单，本项目适用。
    signature = hmac.new(_get_secret().encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload_b64}.{_b64url_encode(signature)}"


# 【函数】校验 JWT 并取出载荷（受保护接口的"入口验票"动作）。
# 入参：token —— 客户端 Authorization 头中携带的完整 JWT 字符串
# 返回：Optional[dict] —— 校验通过返回载荷字典；签名错误/已过期/格式损坏返回 None
# 业务定位：get_current_user 的底层验票器，所有受保护接口的信任起点；
#           本函数只验"票真不真、过期没有"，吊销对账在依赖层另行比对。
def verify_access_token(token: str) -> Optional[Dict[str, Any]]:
    """校验 JWT，返回 payload；无效/过期返回 None。"""
    try:
        # 拆三段：头.载荷.签名；段数不对说明不是合法 JWT
        header_b64, payload_b64, signature_b64 = token.split(".")
        # 用服务器密钥对"头.载荷"重算签名（与签发时完全同一套算法与密钥）
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = hmac.new(_get_secret().encode(), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(signature_b64)
        # 【关键行】恒定时间比对"重算签名 vs 客户端签名"：不一致 = 伪造或被篡改。
        # 为什么：JWT 验真的本质就是"验章"——只有持有服务器密钥的人才能算出合法
        #         签名；篡改 sub/exp/role 任一字段都会导致重算结果不同而拒收；
        #         compare_digest 同时防时序侧信道。
        # 删除后果：任意伪造 token 直接放行（或一律拒绝），认证形同虚设。
        # 替代方案：pyjwt 库内部同样是 HMAC 比对；自实现代码量小、零依赖，
        #           且面试可完整口述"签发-验签"全流程。
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        # 签名通过后才信任载荷：解码 JSON（签名已验过，内容不可能被篡改）
        payload = json.loads(_b64url_decode(payload_b64).decode())
        # 过期检查：exp 是签发时写死的过期时间戳，到期后一律拒收
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        # 任何异常（缺段、base64 非法、JSON 损坏、类型异常）统一视为无效 token
        return None


# 【函数】生成用户 ID：前缀 u_ + 16 位十六进制随机串（8 字节 = 64 bit 熵）。
# 入参：无
# 返回：str —— 形如 "u_1a2b3c4d5e6f7a8b" 的全局唯一 ID
# 业务定位：注册新用户时生成主键；必须用密码学安全随机源，保证 ID 不可预测、
#           不可枚举，杜绝"猜测他人 ID"导致的越权访问。
def generate_user_id() -> str:
    """生成随机 user_id。"""
    # secrets（而非 random 模块）：random 的伪随机序列可被预测，会被用来撞库
    return f"u_{secrets.token_hex(8)}"
