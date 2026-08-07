"""LLM 供应商 URL 安全校验（P0 加固：SSRF 防护）。

自定义供应商 base_url 由用户提供、服务端代为请求——若指向内网/云元数据/保留地址，
可被用于内网探测或窃取（配合服务端 key 回退）。本模块提供统一校验：

1. 仅允许 http/https scheme；
2. 字面 IP 与 DNS 解析后的 IP 均不能落在内网/保留/链路本地/CGNAT 段；
3. 请求层配合 allow_redirects=False 防重定向绕过（见 llm客户端）。
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_内网前缀 = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),   # 云元数据（AWS 169.254.169.254 等）
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1"),
    ipaddress.ip_network("fc00::/7"),         # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),        # IPv6 link-local
)


def 校验LLM供应商URL(base_url: str) -> str:
    """校验并规范化 base_url；不合法抛 ValueError（由调用方转 400）。

    对域名同时做一次 DNS 解析校验（保存/测试是低频操作，可接受）；
    请求时的 DNS rebinding 由 allow_redirects=False 与字面校验共同缓解。
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("API 地址不能为空")

    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http"):
        raise ValueError("仅支持 http/https 协议")
    host = parsed.hostname
    if not host:
        raise ValueError("API 地址缺少主机名")

    ips: list = []
    try:
        ips.append(ipaddress.ip_address(host))  # 字面 IP
    except ValueError:
        try:
            ips = [ipaddress.ip_address(info[4][0]) for info in socket.getaddrinfo(host, None)]
        except OSError:
            raise ValueError("无法解析主机名")

    for ip in ips:
        if any(ip in net for net in _内网前缀):
            raise ValueError("不允许访问内网/保留地址（SSRF 防护）")
    return url