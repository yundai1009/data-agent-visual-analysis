"""LLM 客户端：OpenAI 兼容协议 + JSON 容错解析。

为什么不用 langchain
--------------------
- 本次仅需要 ``chat/completions`` + ``tools`` 两个接口，引入 langchain 会让依赖变重；
- DeepSeek / OpenAI / 硅基流动 全部兼容 OpenAI 协议，直接用 ``requests`` 调最透明、
  最便于面试时讲清楚每一步在做什么。

为什么不做 LLM 生成代码 + exec 的路线
-------------------------------------
- LLM 生成 Python 代码后用 ``exec`` 执行是“Agent 自动数据分析”常见但危险的写法；
- 本项目从一开始就明确拒绝这条路线：LLM 只输出结构化意图 JSON，由后端已有
  ``上传报表生成器.生成报表数据`` 安全执行；任何字段越界或 JSON 不合法都回退到
  关键词匹配兜底，而不是让 LLM 的输出直接进 exec/eval。

失败模式（调用方必须处理 ``返回 None`` 的情况）
-----------------------------------------------
- ``LLM_API_KEY`` 未配置 / 为占位字符串 ``your_llm_api_key`` → 不调用，返回 None
- ``requests`` 抛任何异常（网络/超时/SSL） → 捕获，返回 None
- HTTP 非 200 → 返回 None
- ``choices[0].message.content`` 为空或非字符串 → 返回 None
- ``content`` 中包含 markdown fence ``` ```json ... ``` ``` → 自动剥
- ``content`` 抓不到 ``{...}`` 片段 → 返回 None
- ``json.loads`` 解析失败 → 返回 None
- 解析出的不是 dict → 返回 None

═══════════════════════════════════════════════════════════════
【文件总览】项目层级与调用关系
═══════════════════════════════════════════════════════════════
- 所在目录：后端_核心/agent/
- 被谁调用：
  · 编排器.py    → chat_completion / extract_tool_call / is_llm_configured / 最近LLM失败
  · 记忆.py      → embed_text（把记忆文本转成向量存库/检索）
  · 结论润色.py  → chat_completion（LLM 润色分析结论）
- 调用了谁：
  · config/settings.py → EnvConfig / LLMRequestConfig（全局与请求级配置）
  · requests 库 → 直接调用 OpenAI 兼容 HTTP 接口（不用 langchain，依赖轻、好讲解）
- 本文件负责：
  1. 封装 OpenAI 兼容协议的 chat/completions 调用（DeepSeek/OpenAI/硅基流动通用）
  2. 从 LLM 响应中安全抽取 tool_call（名称 + 参数 JSON）
  3. 容错解析 LLM 输出的 JSON（剥 markdown fence、括号配平找 JSON 块）
  4. 失败不抛异常，统一返回 None + 记录原因，由调用方降级兜底
- 面试要点：所有失败路径都收敛为「返回 None + 记录原因」，上层永远有兜底；
  LLM 输出绝不直接进 exec/eval，只允许解析成结构化数据后走受控执行。
"""

from __future__ import annotations

import json
import logging
import re
import time  # 批次4：LLM 重试退避
from typing import Any, Dict, List, Optional

import requests

from config.settings import EnvConfig, LLMRequestConfig

logger = logging.getLogger(__name__)


# OpenAI 兼容 ``chat/completions`` 端点；DeepSeek / OpenAI / 硅基流动均一致。
_CHAT_COMPLETIONS_PATH = "/chat/completions"

# 视为“未配置 LLM”的占位字符串，触发静默回退。
_UNCONFIGURED_KEY_PLACEHOLDERS = {"", "your_llm_api_key", "your-api-key", "sk-xxx"}

# 最近一次 LLM 失败原因（模块级，供降级路径把原因透传给用户，
# 避免"LLM 失败静默回退规则"让用户误以为系统没理解）。
_last_llm_fail: Dict[str, Any] = {}


def 最近LLM失败() -> Dict[str, Any]:
    """返回最近一次 LLM 失败原因（供报表/前端明示）。"""
    return dict(_last_llm_fail)


def _record_llm_fail(reason: str, llm_config: Optional["LLMRequestConfig"] = None) -> None:
    """记录失败原因。优先写入请求级 llm_config（并发安全）；无 config 时写全局并清空旧值。"""
    if llm_config is not None:
        # 阶段 34 修复：LLMRequestConfig 是 frozen dataclass，直接赋值会抛
        # FrozenInstanceError（cannot assign to field），导致 LLM 失败时
        # 意图解析异常降级、失败原因丢失——用 object.__setattr__ 绕过冻结，
        # 保留 frozen 的"防意外修改"设计，仅允许内部记录失败原因。
        object.__setattr__(llm_config, "llm_fail_reason", reason)
        return
    _last_llm_fail.clear()
    _last_llm_fail.update({"reason": reason})


def _解释HTTP状态(status_code: int, model: str, base_url: str) -> str:
    """把 LLM API 的 HTTP 状态码转成用户可读的原因。"""
    common = {
        401: "API Key 无效（认证失败），请检查 Key 是否正确、服务商是否选对",
        402: "LLM 账号欠费或额度用尽（HTTP 402），请到服务商平台充值",
        403: "无权限访问（403），请检查 Key 权限/服务商是否匹配",
        404: "接口地址不存在（404），请检查模型名或服务商",
        429: "请求过于频繁或额度受限（429），请稍后重试",
    }
    if status_code in common:
        return f"LLM 调用失败：{common[status_code]}"
    return f"LLM 调用失败：HTTP {status_code}（模型 {model} @ {base_url}）"


class LLMError(Exception):
    """LLM 调用相关错误。本模块对外不抛出，仅内部用于日志区分。"""


def is_llm_configured(api_key: Optional[str] = None) -> bool:
    """LLM 是否真的配置了可用 key。

    作用：一键判断"能不能走 LLM 路径"，是全局降级开关的判定依据。

    当 ``LLM_API_KEY`` 缺失或为占位字符串时，全链路应静默回退到关键词匹配。
    可选传 ``api_key``（如 BYOK 用户自带 Key）优先判断，否则查服务端 EnvConfig。

    入参：
      - api_key：可选，用户自带的 Key；不传则用服务端 EnvConfig.LLM_API_KEY
    返回：
      - bool：True=有真实 Key 可调用 LLM；False=未配置/占位符，应走降级路径
    业务定位：编排器的总开关——决定用户请求走"LLM 智能分析"还是"关键词匹配兜底"。
    """
    key = (api_key or EnvConfig.LLM_API_KEY or "").strip()
    return key.lower() not in _UNCONFIGURED_KEY_PLACEHOLDERS


def _strip_markdown_fence(text: str) -> str:
    """剥除 ```json ... ``` 或 ``` ... ``` 的 markdown fence。"""
    stripped = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, re.S | re.I)
    if fence_match:
        return fence_match.group(1).strip()
    return stripped


def _extract_json_block(text: str) -> Optional[str]:
    """从 LLM 输出文本中抽取第一个平衡的 ``{...}`` 块。

    朴素 ``re.search(r'\\{.*\\}', text, re.S)`` 在 LLM 输出多个 JSON 片段或
    含解释性文字时会抓错。这里用括号配平的方式找第一个完整 dict 块。
    """
    if not text:
        return None
    candidate = _strip_markdown_fence(text)
    start = candidate.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    quote_char = ""
    for index in range(start, len(candidate)):
        char = candidate[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote_char:
                in_string = False
            continue
        if char in ('"', "'"):
            in_string = True
            quote_char = char
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return candidate[start:index + 1]
    return None


def parse_llm_json(content: Optional[str]) -> Optional[Dict[str, Any]]:
    """从 LLM 输出文本解析出 JSON dict。失败统一返回 None。

    作用：LLM 的输出经常带解释性文字、markdown 代码块围栏，直接 json.loads 必挂；
    这里先做容错抽取（剥 fence + 括号配平），再严格解析。

    入参：
      - content：LLM 输出的原始文本（可能为 None/非字符串）
    返回：
      - 成功：解析出的 dict
      - 失败：None（无内容/抽不到 JSON 块/解析失败/不是 dict）
    业务定位：LLM 自由文本 → 结构化数据的唯一通道；解析失败即触发降级。
    """
    if not content or not isinstance(content, str):
        return None
    block = _extract_json_block(content)
    if not block:
        return None
    try:
        parsed = json.loads(block)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def chat_completion(
    messages: List[Dict[str, str]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    timeout: Optional[int] = None,
    # 请求级 LLM 配置（并发安全，优先于 user_* 与 EnvConfig 全局配置）
    llm_config: Optional["LLMRequestConfig"] = None,
    # 用户自配 LLM 覆盖（来自前端请求头）——旧签名，优先级低于 llm_config
    user_base_url: Optional[str] = None,
    user_api_key: Optional[str] = None,
    user_model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """调用 OpenAI 兼容 ``chat/completions`` 接口。

    作用：整个 Agent 链路的"发动机"——所有 LLM 推理都从这里发出请求。

    成功返回完整响应 dict；失败统一返回 None，由调用方回退兜底。
    不会抛网络异常给上层。

    配置优先级：``llm_config`` > ``user_base_url/user_api_key/user_model`` > ``EnvConfig``。
    注意：api_key 只接受服务端来源（``llm_config.api_key`` 或 ``EnvConfig.LLM_API_KEY``），
    前端无法通过请求头传入。

    入参：
      - messages：OpenAI 协议的消息列表（system/user/assistant/tool）
      - tools：Function Calling 工具 schema 列表（None 表示纯聊天）
      - tool_choice：是否强制指定工具（"auto" 让模型自己选）
      - timeout：请求超时秒数（不传用配置值）
      - llm_config：请求级配置对象（含 base_url/api_key/model）
      - user_base_url/user_api_key/user_model：旧版用户覆盖参数（优先级低）
    返回：
      - 成功：LLM 完整响应 dict（含 choices/usage 等）
      - 失败：None（未配置 Key/网络异常/HTTP 非 200/响应非 JSON 等，原因已记录）
    业务定位：多轮 ReAct 每轮推理、结论润色，全靠这一个函数对外通信。
    重试、脱敏、降级提示都在这里统一处理，调用方不需要关心细节。
    """
    # 请求级配置优先合并；未显式提供的字段继续回退 EnvConfig 全局值
    if llm_config is not None:
        user_base_url = user_base_url or llm_config.base_url
        user_api_key = user_api_key or llm_config.api_key
        user_model = user_model or llm_config.model

    api_key = (user_api_key or EnvConfig.LLM_API_KEY or "").strip()
    # 【关键行】未配置真实 Key（空值或占位符）时直接短路返回 None，不发起任何请求。
    # 为什么：占位 Key 发出去只会得到 401，白费一次网络请求还拖慢响应；
    # 提前拦截并记录原因，让上层立刻走关键词匹配兜底，用户几乎无感知。
    # 删除后果：每次请求都打到 LLM 网关拿 401，系统变慢且错误日志刷屏。
    # 替代方案：让请求失败后由异常处理兜底（慢 + 不可控）；前置校验更干净。
    if api_key.lower() in _UNCONFIGURED_KEY_PLACEHOLDERS:
        _record_llm_fail("未配置 API Key（服务端 .env 为占位符），请在页面填写自己的 Key", llm_config)
        return None

    base_url = ((user_base_url or EnvConfig.LLM_BASE_URL) or "").rstrip("/")
    # S2 修复：请求前二次校验用户侧 base_url——防保存后 DNS rebinding 绕过。
    # 仅对用户自配（user_base_url/llm_config）的地址校验；EnvConfig 全局地址
    # 属运维配置，不在本防护范围。校验失败则记录原因并短路不发请求。
    if user_base_url:
        from services.llm_security import 校验LLM供应商URL
        try:
            base_url = 校验LLM供应商URL(base_url)
        except ValueError as exc:
            _record_llm_fail(f"LLM 地址 SSRF 校验失败：{exc}", llm_config)
            return None
    url = f"{base_url}{_CHAT_COMPLETIONS_PATH}"
    model = user_model or EnvConfig.LLM_MODEL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": EnvConfig.LLM_TEMPERATURE,
        "stream": False,
        # 批次4：输出长度上限（防失控/控成本，默认 2048）
        "max_tokens": getattr(EnvConfig, "LLM_MAX_TOKENS", 2048),
    }
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice

    request_timeout = timeout or EnvConfig.LLM_TIMEOUT or 30
    # 批次4：LLM 重试——网络异常与可重试状态码（429/5xx/408）最多重试 2 次（指数退避）
    # 【关键行】最多尝试 3 次（首次 + 2 次重试），网络抖动/限流时自动恢复。
    # 为什么：LLM 网关经常因限流（429）或瞬时过载（5xx）失败，重试一次成功率大增；
    # 指数退避（0.5s/1s）避免雪崩式重试把网关打得更死。
    # 删除后果：网络一抖整个分析就降级成关键词匹配，明明重试一次就能成功。
    # 替代方案：固定间隔重试（简单但会加剧限流）；指数退避是标准做法。
    max_attempts = 3
    response = None
    for attempt in range(max_attempts):
        try:
            # P0 加固：禁重定向（防 SSRF 重定向绕过）
            # 【关键行】真正向 LLM API 发起 HTTP POST 请求，携带 messages + tools。
            # 为什么：整个 Agent 的"思考"都发生在这里——LLM 根据上下文决定调用哪个工具；
            # allow_redirects=False 是为了防 SSRF：恶意配置的 base_url 若返回重定向，
            # 可能把请求转发到内网地址，禁重定向从根上堵住这个漏洞。
            # 删除后果：Agent 完全失去推理能力，全链路只能降级到关键词匹配。
            # 替代方案：用 requests.Session + 校验重定向白名单（复杂）；
            # 直接禁重定向最简单且满足业务（合法 LLM 网关不会重定向）。
            response = requests.post(url, headers=headers, json=payload, timeout=request_timeout, allow_redirects=False)
        except requests.RequestException as exc:
            logger.warning("LLM 网络异常（第 %d 次）: %s", attempt + 1, exc)
            if attempt == max_attempts - 1:
                _record_llm_fail(f"LLM 网络异常（无法访问 {base_url}）：{type(exc).__name__}，请检查网络/代理", llm_config)
                return None
            time.sleep(0.5 * (attempt + 1))
            continue

        if response.status_code == 200:
            break
        retryable = response.status_code in (408, 429, 500, 502, 503, 504)
        if not retryable or attempt == max_attempts - 1:
            logger.warning("LLM HTTP %s（响应内容已脱敏，仅记录状态码）", response.status_code)
            _record_llm_fail(_解释HTTP状态(response.status_code, model, base_url), llm_config)
            return None
        logger.warning("LLM HTTP %s，重试（第 %d 次）", response.status_code, attempt + 1)
        time.sleep(0.5 * (attempt + 1))

    if response is None:
        return None

    try:
        return response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("LLM 响应非 JSON: %s", exc)
        _record_llm_fail("LLM 响应不是合法 JSON", llm_config)
        return None


def extract_tool_call(response: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从 ``chat_completion`` 响应中提取第一个 ``tool_calls`` 项。

    作用：LLM 返回的响应结构很"深"（choices → message → tool_calls → function），
    这个函数负责逐层剥壳，取出第一个工具调用的名称和参数。

    返回 ``{"name": str, "arguments": dict}``；不可用则 None。

    入参：
      - response：chat_completion 的完整返回 dict（可能为 None）
    返回：
      - 成功：{"name": 工具名, "arguments": 参数字典}（arguments 已做 JSON 解析）
      - 失败：None（响应为空/结构不对/没有 tool_calls）
    业务定位：ReAct 循环的"决策读取器"——编排器拿到这个结果才知道 LLM 想调用哪个工具。
    """
    if not response or not isinstance(response, dict):
        return None
    choices = response.get("choices") or []
    if not choices or not isinstance(choices, list):
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not tool_calls or not isinstance(tool_calls, list):
        return None
    call = tool_calls[0]
    if not isinstance(call, dict):
        return None
    function = call.get("function") or {}
    name = function.get("name")
    arguments_raw = function.get("arguments")
    if not name or arguments_raw is None:
        return None
    if isinstance(arguments_raw, dict):
        arguments = arguments_raw
    elif isinstance(arguments_raw, str):
        parsed = parse_llm_json(arguments_raw)
        arguments = parsed if parsed is not None else {}
    else:
        arguments = {}
    return {"name": name, "arguments": arguments}


def embed_text(
    text: str,
    llm_config: Optional["LLMRequestConfig"] = None,
) -> Optional[List[float]]:
    """调用 OpenAI 兼容的 /embeddings 接口，返回向量。

    与 ``chat_completion`` 相同的配置优先级：``llm_config`` > ``EnvConfig``。
    此前直接读全局 EnvConfig（多 provider 并发下 embedding 走错供应商），
    本轮对齐为请求级配置透传（见 记忆.py 调用链）。

    Args:
        text: 要编码的文本
        llm_config: 请求级 LLM 配置（可选，缺省回退服务端全局配置）

    Returns:
        浮点数向量列表，失败返回 None
    """
    api_key = ((llm_config.api_key if llm_config else None) or EnvConfig.LLM_API_KEY or "").strip()
    if not is_llm_configured(api_key):
        logger.warning("LLM 未配置，无法生成 embedding")
        return None

    base_url = (
        (llm_config.base_url if llm_config else None)
        or EnvConfig.LLM_BASE_URL
        or ""
    ).rstrip("/")
    # 阶段 34 修复（Bug3）：embedding 优先走独立配置 LLM_EMBEDDING_BASE_URL/
    # LLM_EMBEDDING_MODEL——chat 端点（如智谱 GLM）不支持 /embeddings 时，
    # 可指向供应商的专用 embedding 端点；未配置则回退通用 base_url 与模型。
    embed_base = (EnvConfig.LLM_EMBEDDING_BASE_URL or base_url).rstrip("/")
    url = f"{embed_base}/embeddings"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # DeepSeek 使用 text-embedding-v3，OpenAI 使用 text-embedding-3-small
    model = EnvConfig.LLM_EMBEDDING_MODEL or "text-embedding-3-small"  # 通用 fallback
    payload = {
        "input": text,
        "model": model,
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30, allow_redirects=False)
    except requests.RequestException as exc:
        logger.warning("Embedding 网络异常: %s", exc)
        return None

    if response.status_code != 200:
        logger.warning("Embedding HTTP %s（响应内容已脱敏，仅记录状态码）", response.status_code)
        return None

    try:
        data = response.json()
        return data.get("data", [{}])[0].get("embedding")
    except (json.JSONDecodeError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Embedding 响应解析失败: %s", exc)
        return None
