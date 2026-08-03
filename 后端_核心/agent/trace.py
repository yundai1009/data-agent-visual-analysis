"""Agent 真实 Trace 记录与序列化。

阶段 1 的 ``Agent Trace`` 是 6 段固定模板字符串，无任何真实决策证据。
阶段 2 改为 **每轮 LLM 调用都记 1 条真实记录**，最终塞回 ``Agent Trace`` 字段。

每条记录含：
- ``轮次``    1, 2, 3...
- ``步骤``    LLM/Tool/观察
- ``工具名``  当步骤是 Tool 调用时
- ``工具入参`` 已脱敏（不传原始数据，仅传字段名/聚合方式等结构化参数）
- ``工具输出摘要``  截断到 200 字符，避免把整张聚合表塞进 trace
- ``token``   prompt_tokens + completion_tokens + total（如响应里有）
- ``耗时_ms``  本轮从开始到结束
- ``状态``    成功 / 失败
- ``理由``    LLM 给出的决策理由 / 失败原因

设计纪律
--------
- trace 永远不携带原始数据行，只携带 schema 化摘要（保护隐私 + 控制 token）
- trace 总长度有上限，避免大表聚合结果撑爆响应
- trace 本身是 list[dict]，与阶段 1 的 list[dict] 形态一致，前端零改动也能渲染
"""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional


# 单条 trace 长度上限：超长会被截断
_MAX_TRACE_RECORDS = 20
# 工具输出摘要长度
_OUTPUT_SUMMARY_LIMIT = 200


class TraceRecorder:
    """记录一轮 ReAct 决策的证据。线程不安全；每个请求一个新实例。

    on_event: 可选回调，每记录一条就实时推送一条
        ``{"type": "step", "data": record}``（供 SSE 直播使用）。回调异常
        被吞掉，绝不影响主流程。
    """

    def __init__(self, on_event: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._records: List[Dict[str, Any]] = []
        self._on_event = on_event

    def _emit(self, record: Dict[str, Any]) -> None:
        if self._on_event:
            try:
                self._on_event({"type": "step", "data": record})
            except Exception:  # noqa: BLE001 - 推送失败不影响分析主流程
                pass

    def 记录LLM调用(
        self,
        轮次: int,
        *,
        prompt_summary: str,
        耗时_ms: int,
        token: Optional[Dict[str, int]] = None,
        状态: str = "成功",
        理由: str = "",
    ) -> None:
        record: Dict[str, Any] = {
            "轮次": 轮次,
            "步骤": "LLM推理",
            "prompt摘要": prompt_summary[:200],
            "耗时_ms": 耗时_ms,
            "token": token or {},
            "状态": 状态,
            "理由": 理由[:200],
        }
        self._records.append(record)
        self._emit(record)
        if len(self._records) > _MAX_TRACE_RECORDS:
            self._records = self._records[:_MAX_TRACE_RECORDS]

    def 记录工具调用(
        self,
        轮次: int,
        *,
        工具名: str,
        入参: Dict[str, Any],
        输出摘要: str,
        耗时_ms: int,
        状态: str = "成功",
        理由: str = "",
    ) -> None:
        record: Dict[str, Any] = {
            "轮次": 轮次,
            "步骤": "工具调用",
            "工具名": 工具名,
            "工具入参": _sanitize_args(入参),
            "工具输出摘要": 输出摘要[:_OUTPUT_SUMMARY_LIMIT],
            "耗时_ms": 耗时_ms,
            "状态": 状态,
            "理由": 理由[:200],
        }
        self._records.append(record)
        self._emit(record)
        if len(self._records) > _MAX_TRACE_RECORDS:
            self._records = self._records[:_MAX_TRACE_RECORDS]

    def 记录观察(
        self,
        轮次: int,
        *,
        说明: str,
        状态: str = "成功",
    ) -> None:
        record: Dict[str, Any] = {
            "轮次": 轮次,
            "步骤": "观察",
            "说明": 说明[:200],
            "状态": 状态,
        }
        self._records.append(record)
        self._emit(record)
        if len(self._records) > _MAX_TRACE_RECORDS:
            self._records = self._records[:_MAX_TRACE_RECORDS]

    def 记录失败(
        self,
        轮次: int,
        *,
        步骤: str,
        理由: str,
    ) -> None:
        record: Dict[str, Any] = {
            "轮次": 轮次,
            "步骤": 步骤,
            "状态": "失败",
            "理由": 理由[:200],
        }
        self._records.append(record)
        self._emit(record)
        if len(self._records) > _MAX_TRACE_RECORDS:
            self._records = self._records[:_MAX_TRACE_RECORDS]

    # ---------- 输出 ----------

    def to_list(self) -> List[Dict[str, Any]]:
        """标准化 list[dict] 形态，供响应 Agent_Trace 字段使用。"""
        return list(self._records)

    @property
    def records(self) -> List[Dict[str, Any]]:
        return list(self._records)


# ---- 私有 -------------------------------------------------------------------

_SENSITIVE_KEYS = {"password", "api_key", "token", "secret"}


def _sanitize_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """脱敏：丢弃敏感 key，过长字符串截断。"""
    out: Dict[str, Any] = {}
    for k, v in (args or {}).items():
        if k.lower() in _SENSITIVE_KEYS:
            out[k] = "***"
            continue
        if isinstance(v, str):
            out[k] = v[:100]
        elif isinstance(v, list):
            out[k] = [_truncate_str(item) for item in v[:20]]
        else:
            out[k] = v
    return out


def _truncate_str(item: Any) -> Any:
    if isinstance(item, str):
        return item[:100]
    return item


# ---- 计时小工具 -------------------------------------------------------------


class _Timer:
    """用 ``with`` 计时。"""

    def __init__(self) -> None:
        self._start = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)

    @property
    def elapsed_ms(self) -> int:  # 由 __exit__ 写入
        return getattr(self, "_elapsed_ms", 0)  # type: ignore[no-any-return]

    @elapsed_ms.setter
    def elapsed_ms(self, value: int) -> None:
        self._elapsed_ms = value


def 计时() -> _Timer:
    return _Timer()


def 提取token(响应: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """从 OpenAI 兼容响应中提取 token 用量；不存在则返回空 dict。"""
    if not 响应 or not isinstance(响应, dict):
        return {}
    usage = 响应.get("usage") or {}
    if not isinstance(usage, dict):
        return {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
    }
