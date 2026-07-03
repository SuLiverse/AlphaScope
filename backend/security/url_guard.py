"""SSRF 防护:校验 HTTP/HTTPS URL 的目标主机不是内网/环回/链路本地/云元数据端点。

复用入口
--------
- ``validate_public_http_url(url, allow_local=...)``:主入口, 不安全时抛 ``ValueError``。
  供 TickFlow 自定义行情源抓取(``http_json_provider.fetch_json``)、新闻 URL 抓取等复用。

设计
----
- scheme 限 http/https;host 必填。
- IP 直连: ``ipaddress`` 分类拦截 loopback/private/link-local/multicast/reserved/unspecified
  (覆盖 127.0.0.1、10.x、172.16-31.x、192.168.x、169.254.x 云元数据、224+ 多播等)。
- 域名: ``socket.getaddrinfo`` 解析后**逐 IP 校验**, 防 DNS rebinding(如 127.0.0.1.nip.io)。
- ``allow_local``: True 时放行本地(开发调试);None 时读 ``ALPHASCOPE_ALLOW_LOCAL_FETCH`` env;
  False 时强制拒绝(news 等不可降级路径用)。

注: ``backend/api/news.py`` 此前有等价实现, 已统一改用本模块(allow_local=False 保持原行为)。
"""
from __future__ import annotations

import ipaddress
import os
import socket
from urllib.parse import urlsplit

_LOCAL_HOSTS = {"localhost", "0.0.0.0"}


def _blocked_ip(address: str) -> bool:
    """IP 是否属于内网/环回/链路本地/多播/保留/未指定。"""
    ip = ipaddress.ip_address(address)
    return any(
        (
            ip.is_loopback,
            ip.is_private,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        )
    )


def _local_fetch_allowed() -> bool:
    """``ALPHASCOPE_ALLOW_LOCAL_FETCH`` env 是否开启本机抓取 opt-in。"""
    return os.environ.get("ALPHASCOPE_ALLOW_LOCAL_FETCH", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def validate_public_http_url(url: str, *, allow_local: bool | None = None) -> str:
    """校验 URL scheme=http/https 且目标主机非内网/环回/链路本地。

    返回清理后的 URL。不安全时抛 ``ValueError``。

    ``allow_local``:
      - ``None``: 读 ``ALPHASCOPE_ALLOW_LOCAL_FETCH`` env(默认关, 即拒绝本地)。
      - ``True``: 强制放行本地(开发本机调试 TickFlow 用)。
      - ``False``: 强制拒绝本地(news 等不可降级路径, 不受 env 影响)。
    """
    cleaned = (url or "").strip()
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are supported")
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError("URL host is required")
    if allow_local is None:
        allow_local = _local_fetch_allowed()
    if allow_local:
        return cleaned  # opt-in 放行, 不校验内网
    if host in _LOCAL_HOSTS or host.endswith(".localhost"):
        raise ValueError(
            "Localhost URLs are not allowed (set ALPHASCOPE_ALLOW_LOCAL_FETCH=1 to allow)"
        )
    # IP 直连: 分类拦截
    try:
        ip = ipaddress.ip_address(host)
        if _blocked_ip(str(ip)):
            raise ValueError("Private or local network URLs are not allowed")
        return cleaned
    except ValueError as exc:
        if "not allowed" in str(exc):
            raise
        # host 不是 IP, 是域名 → DNS 解析后逐 IP 校验(防 DNS rebinding)
    try:
        addrinfo = socket.getaddrinfo(host, parsed.port, type=socket.SOCK_STREAM)
    except socket.gaierror as dns_exc:
        raise ValueError("URL host cannot be resolved") from dns_exc
    for info in addrinfo:
        if _blocked_ip(info[4][0]):
            raise ValueError("Private or local network URLs are not allowed")
    return cleaned
