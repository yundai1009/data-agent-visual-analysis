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
        llm_config.llm_fail_reason = reason
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

    当 ``LLM_API_KEY`` 缺失或为占位字符串时，全链路应静默回退到关键词匹配。
    可选传 ``api_key``（如 BYOK 用户自带 Key）优先判断，否则查服务端 EnvConfig。
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
    """从 LLM 输出文本解析出 JSON dict。失败统一返回 None。"""
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

    成功返回完整响应 dict；失败统一返回 None，由调用方回退兜底。
    不会抛网络异常给上层。

    配置优先级：``llm_config`` > ``user_base_url/user_api_key/user_model`` > ``EnvConfig``。
    注意：api_key 只接受服务端来源（``llm_config.api_key`` 或 ``EnvConfig.LLM_API_KEY``），
    前端无法通过请求头传入。
    """
    # 请求级配置优先合并；未显式提供的字段继续回退 EnvConfig 全局值
    if llm_config is not None:
        user_base_url = user_base_url or llm_config.base_url
        user_api_key = user_api_key or llm_config.api_key
        user_model = user_model or llm_config.model

    api_key = (user_api_key or EnvConfig.LLM_API_KEY or "").strip()
    if api_key.lower() in _UNCONFIGURED_KEY_PLACEHOLDERS:
        _record_llm_fail("未配置 API Key（服务端 .env 为占位符），请在页面填写自己的 Key", llm_config)
        return None

    base_url = ((user_base_url or EnvConfig.LLM_BASE_URL) or "").rstrip("/")
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
    max_attempts = 3
    response = None
    for attempt in range(max_attempts):
        try:
            # P0 加固：禁重定向（防 SSRF 重定向绕过）
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

    返回 ``{"name": str, "arguments": dict}``；不可用则 None。
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


def embed_text(text: str) -> Optional[List[float]]:
    """调用 OpenAI 兼容的 /embeddings 接口，返回向量。

    Args:
        text: 要编码的文本

    Returns:
        浮点数向量列表，失败返回 None
    """
    if not is_llm_configured():
        logger.warning("LLM 未配置，无法生成 embedding")
        return None

    base_url = (EnvConfig.LLM_BASE_URL or "").rstrip("/")
    url = f"{base_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {EnvConfig.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    # DeepSeek 使用 text-embedding-v3，OpenAI 使用 text-embedding-3-small
    model = "text-embedding-3-small"  # 通用 fallback
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
