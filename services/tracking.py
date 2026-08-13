# ============================================================
# 文件头 · 后端采集推断（面试讲解）
# ------------------------------------------------------------
# 管什么：为预测数据采集提供"纯后端、用户无感知"的字段推断：
#   设备类型（User-Agent）、来源渠道/活动来源（Referer 参数）、
#   发起入口（Referer 路径）。
# 为什么放在后端：埋点信息不应依赖前端上报——前端探测设备、
#   携带渠道头会留下可被用户/抓包发现的痕迹，也不便扩展；
#   由后端在请求到达时自动推断，用户完全无感，前端零改动。
# 关键设计：
#   - 全部有兜底默认值（"网页"/"未知"/空），任何异常不抛错；
#   - 渠道解析兼容 channel / utm_source 两种参数，活动来源兼容
#     utm_campaign / utm_medium / source；
#   - 发起入口按 Referer 路径前缀匹配（/analysis→提问框 等），
#     无 Referer（如服务端调用/定时任务）归"未知"。
# ============================================================
from __future__ import annotations

from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

# 设备类型兜底（识别不出统一按网页，不新增未知类噪声）
_DEVICE_FALLBACK = "网页"

# 渠道兜底：Referer 拿不到渠道时用"未知"（预测系统特征层
# get_dummies 自动生成 channel_未知 列，模型自适应，不报错）
_CHANNEL_FALLBACK = "未知"

# 发起入口：Referer 路径前缀 → 语义标签
_ENTRY_RULES: list[Tuple[str, str]] = [
    ("/analysis", "提问框"),
    ("/report", "报表页"),
    ("/dashboard", "看板"),
    ("/data", "数据管理"),
    ("/template", "模板"),
    ("/schedule", "定时"),
]


def 推断设备类型(user_agent: Optional[str]) -> str:
    """从 User-Agent 推断设备类型：安卓 / 苹果 / 网页（兜底）。

    为什么用关键词匹配而不是正则：UA 形态繁杂，Android/iPhone/iPad
    关键词覆盖绝大多数真实终端；匹配不到（爬虫/桌面客户端）归网页。
    """
    if not user_agent:
        return _DEVICE_FALLBACK
    ua = user_agent
    if "Android" in ua:
        return "安卓"
    if "iPhone" in ua or "iPad" in ua or "iPod" in ua:
        return "苹果"
    return _DEVICE_FALLBACK


def 解析渠道与活动来源(referer: Optional[str]) -> Tuple[str, str]:
    """从 Referer URL 的查询参数解析 (来源渠道, 活动来源)。

    渠道：channel / utm_source；活动来源：utm_campaign / utm_medium / source。
    都拿不到时渠道返回"未知"、活动来源返回空串（可选字段）。
    """
    if not referer:
        return _CHANNEL_FALLBACK, ""
    try:
        query = parse_qs(urlparse(referer).query)
    except ValueError:
        return _CHANNEL_FALLBACK, ""
    channel = (query.get("channel") or query.get("utm_source") or [""])[0].strip()
    user_source = (
        query.get("utm_campaign")
        or query.get("utm_medium")
        or query.get("source")
        or [""]
    )[0].strip()
    return (channel or _CHANNEL_FALLBACK), user_source


def 推断发起入口(referer: Optional[str]) -> str:
    """按 Referer 路径推断发起入口（提问框/报表页/看板/…），无则"未知"。"""
    if not referer:
        return "未知"
    try:
        path = urlparse(referer).path
    except ValueError:
        return "未知"
    for prefix, label in _ENTRY_RULES:
        if prefix in path:
            return label
    return "未知"
