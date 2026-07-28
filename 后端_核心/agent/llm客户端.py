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
from typing import Any, Dict, List, Optional

import requests

from config.settings import EnvConfig

logger = logging.getLogger(__name__)


# OpenAI 兼容 ``chat/completions`` 端点；DeepSeek / OpenAI / 硅基流动均一致。
_CHAT_COMPLETIONS_PATH = "/chat/completions"

# 视为“未配置 LLM”的占位字符串，触发静默回退。
_UNCONFIGURED_KEY_PLACEHOLDERS = {"", "your_llm_api_key", "your-api-key", "sk-xxx"}


class LLMError(Exception):
    """LLM 调用相关错误。本模块对外不抛出，仅内部用于日志区分。"""


def is_llm_configured() -> bool:
    """LLM 是否真的配置了可用 key。

    当 ``LLM_API_KEY`` 缺失或为占位字符串时，全链路应静默回退到关键词匹配。
    """
    key = (EnvConfig.LLM_API_KEY or "").strip()
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
    # 用户自配 LLM 覆盖（来自前端请求头）
    user_base_url: Optional[str] = None,
    user_api_key: Optional[str] = None,
    user_model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """调用 OpenAI 兼容 ``chat/completions`` 接口。

    成功返回完整响应 dict；失败统一返回 None，由调用方回退兜底。
    不会抛网络异常给上层。
    """
    if not is_llm_configured() and not user_api_key:
        return None

    base_url = ((user_base_url or EnvConfig.LLM_BASE_URL) or "").rstrip("/")
    url = f"{base_url}{_CHAT_COMPLETIONS_PATH}"
    api_key = user_api_key or EnvConfig.LLM_API_KEY
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
    }
    if tools:
        payload["tools"] = tools
    if tool_choice:
        payload["tool_choice"] = tool_choice

    request_timeout = timeout or EnvConfig.LLM_TIMEOUT or 30
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=request_timeout)
    except requests.RequestException as exc:
        logger.warning("LLM 网络异常: %s", exc)
        return None

    if response.status_code != 200:
        logger.warning("LLM HTTP %s: %s", response.status_code, response.text[:200])
        return None

    try:
        return response.json()
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("LLM 响应非 JSON: %s", exc)
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
        response = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        logger.warning("Embedding 网络异常: %s", exc)
        return None

    if response.status_code != 200:
        logger.warning("Embedding HTTP %s: %s", response.status_code, response.text[:200])
        return None

    try:
        data = response.json()
        return data.get("data", [{}])[0].get("embedding")
    except (json.JSONDecodeError, IndexError, TypeError, ValueError) as exc:
        logger.warning("Embedding 响应解析失败: %s", exc)
        return None
