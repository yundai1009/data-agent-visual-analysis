from __future__ import annotations

import os
from typing import Any, Dict, Optional

from config.settings import EnvConfig

import requests

try:
    import streamlit as st
except Exception:  # pragma: no cover - 允许在非 Streamlit 环境中导入本模块
    st = None


API_BASE_URL = os.getenv("AGENT_API_BASE_URL", "http://127.0.0.1:8000")
API_TIMEOUT = int(os.getenv("AGENT_API_TIMEOUT", "120"))
AUTH_HEADERS = {"Authorization": "Bearer demo-token"}


def _显示错误(message: str) -> None:
    if st is not None:
        st.error(message)


def _请求(method: str, path: str, **kwargs) -> Optional[Any]:
    url = f"{API_BASE_URL}{path}"
    headers = kwargs.pop("headers", {})
    headers = {**AUTH_HEADERS, **headers}
    try:
        response = requests.request(method, url, headers=headers, timeout=API_TIMEOUT, **kwargs)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()
    except requests.RequestException as exc:
        _显示错误(f"API 请求失败：{exc}")
        return None


def _转换执行模式(执行模式: str) -> str:
    if "快速" in 执行模式:
        return "fast"
    if "深度" in 执行模式:
        return "deep"
    return "auto"


def 创建任务(
    问题: str,
    执行模式: str = "auto",
    最大重试次数: int = 2,
    启用缓存: bool = True,
    异步执行: bool = True,
) -> Optional[str]:
    payload = {
        "问题": 问题,
        "执行模式": _转换执行模式(执行模式),
        "最大重试次数": 最大重试次数,
        "启用缓存": 启用缓存,
        "异步执行": 异步执行,
    }
    data = _请求("POST", "/tasks", json=payload)
    if not data:
        return None
    return data.get("任务ID")


def 获取任务状态(任务ID: str) -> Optional[Dict[str, Any]]:
    data = _请求("GET", f"/tasks/{任务ID}")
    return data if isinstance(data, dict) else None


def 取消任务(任务ID: str) -> Optional[Dict[str, Any]]:
    data = _请求("POST", f"/tasks/{任务ID}/cancel")
    return data if isinstance(data, dict) else None


def 获取任务列表(**kwargs) -> Dict[str, Any]:
    data = _请求("GET", "/tasks")
    if not isinstance(data, dict):
        return {"数据": [], "总数": 0}

    items = data.get("items", [])
    normalized_items = []
    for item in items:
        result = item.get("结果") or {}
        normalized_items.append({
            **item,
            "状态": _状态转中文(item.get("状态", "")),
            "问题": item.get("问题", ""),
            "SQL": result.get("SQL"),
            "数据": result.get("数据"),
            "图表": result.get("图表"),
            "结论": result.get("结论"),
            "执行耗时秒": result.get("执行耗时秒", 0),
            "返回行数": result.get("返回行数", 0),
            "Token消耗": result.get("Token消耗", 0),
            "成本_元": result.get("成本_元", 0),
            "完成时间": item.get("更新时间"),
        })
    return {"数据": normalized_items, "总数": data.get("total", len(normalized_items))}


def 获取任务详情(任务ID: str) -> Optional[Dict[str, Any]]:
    data = 获取任务状态(任务ID)
    if not data:
        return None
    result = data.get("结果") or {}
    return {**data, **result, "状态": _状态转中文(data.get("状态", ""))}


def 删除任务(*args, **kwargs) -> bool:
    _显示错误("删除任务接口尚未实现，最小闭环版本暂不支持删除。")
    return False


def 重新执行任务(任务ID: str) -> Optional[str]:
    detail = 获取任务详情(任务ID)
    if not detail:
        return None
    return 创建任务(问题=detail.get("问题") or "重新执行真实分析")


def _状态转中文(status: str) -> str:
    return {
        "pending": "等待中",
        "running": "运行中",
        "completed": "完成",
        "failed": "失败",
        "cancelled": "取消",
    }.get(status, status)


def 获取可视化配置(*args, **kwargs):
    return None


def 保存可视化配置(*args, **kwargs):
    return "mock_dashboard"


def 删除可视化配置(*args, **kwargs):
    return True


def 搜索指标口径(*args, **kwargs):
    return None


def 获取指标详情(*args, **kwargs):
    return None


def 创建指标口径(*args, **kwargs):
    return None


def 更新指标口径(*args, **kwargs):
    return None


def 删除指标口径(*args, **kwargs):
    return None


def 搜索优质资产(*args, **kwargs):
    return None


def 获取资产详情(*args, **kwargs):
    return None


def 创建优质资产(*args, **kwargs):
    return None


def 更新优质资产(*args, **kwargs):
    return None


def 删除优质资产(*args, **kwargs):
    return None


def 触发全量评测(*args, **kwargs):
    return None


def 获取评测结果(*args, **kwargs):
    return None


def 获取评测历史(*args, **kwargs):
    return None


def 获取系统指标(*args, **kwargs):
    return None


def 获取告警历史(*args, **kwargs):
    return []


def 获取链路追踪(*args, **kwargs):
    return []
