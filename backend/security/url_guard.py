"""SSRF 防护:校验 HTTP/HTTPS URL 的目标主机不是内网/环回/链路本地/云元数据端点。

复用入口
--------
- ``validate_public_http_url(url, allow_local=...)``:主入口, 不安全时抛 ``ValueError``。
  供 TickFlow 自定义行情源抓取(``http_json_provider.fetch_json``)、新闻 URL 抓取等复用。
- ``fetch_public_url(...)``:重定向逐跳校验的安全抓取(新闻解析、provider HTTP 通道接入),
  堵住「首跳合法、中间 30x 跳进内网」的盲 SSRF。

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
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

_LOCAL_HOSTS = {"localhost", "0.0.0.0"}

# 跟随重定向的 3x 状态码(301/302/303/307/308; 其余 3xx 视为普通响应交调用方处理)
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


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
        raise ValueError("Localhost URLs are not allowed (set ALPHASCOPE_ALLOW_LOCAL_FETCH=1 to allow)")
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


def fetch_public_url(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: tuple[float, float] = (3.0, 5.0),
    max_hops: int = 5,
    stream: bool = False,
    body: Any = None,
) -> requests.Response:
    """逐跳校验的重定向安全抓取(防「首跳合法、中间跳进内网」的盲 SSRF)。

    威胁模型: 自动跟随重定向(allow_redirects 放开)时 30x 的每一跳由 HTTP 库自行解析并**直接请求**,
    攻击者可提交首跳公网、重定向链穿过 127.0.0.1/内网/云元数据地址的 URL, 服务器会真实
    发出这些内部请求(盲 SSRF: 内网探测、触发内部服务的 GET 副作用); 事后仅复检最终 URL
    的失败响应本身还是干净的内网可达性 oracle。

    实现: ``allow_redirects=False`` 手动循环——当前 URL 先
    ``validate_public_http_url(allow_local=False)`` → 发请求 → 若 3xx 且带 ``Location``,
    按 RFC 3986 ``urljoin(current, location)`` 解析下一跳(相对重定向正确处理) →
    下一跳**先校验再请求**; 非 3xx 返回 response。

    - 任一跳(含首跳)校验失败 → 抛 ``ValueError``, 该跳请求不会发出。
    - 重定向次数超过 ``max_hops`` → 抛 ``ValueError``。
    - ``raise_for_status()``/content-type 判断/响应体读取留给调用方(保持现有职责划分)。

    注: ``body`` 仅 POST 场景使用, 经 requests 的 ``json=`` 发送——与
    ``http_json_provider.fetch_json`` 现行为一致; 若走 ``data=`` 传 dict 会被表单编码,
    改变 POST 语义。requests 是硬依赖(pyproject.toml 钉死 2.33.0), 故模块级导入。
    """
    current = validate_public_http_url(url, allow_local=False)
    followed = 0
    while True:
        response = requests.request(
            method,
            current,
            headers=headers,
            timeout=timeout,
            allow_redirects=False,
            stream=stream,
            json=body if body is not None else None,
        )
        location = (
            response.headers.get("Location") if response.status_code in _REDIRECT_STATUSES else None
        )
        if not location:
            return response
        if followed >= max_hops:
            response.close()
            raise ValueError(f"Too many redirects (limit={max_hops})")
        followed += 1
        response.close()  # 重定向响应无正文, 及时释放连接
        # 下一跳先校验再请求: 相对 Location 经 urljoin 得到的 URL 同样必须过公网校验
        current = validate_public_http_url(urljoin(current, location), allow_local=False)
