"""通知推送渠道 — 把告警/简报推送到外部(Server酱/PushPlus/飞书/Telegram/邮件)。

设计要点(延续「确定性 · 失败安全 · 不外泄密钥」基线):
- **统一协议**: 所有渠道实现 send(title, body) -> SendResult; 成功/失败都返回结构, 不抛。
- **可选依赖**: requests/urllib 走标准库优先;邮件用 smtplib(标准库)。
- **凭证安全**: webhook/token 从通知配置存储读取, 不写日志, 不回传明文。
- **合规**: 仅推送已生成的告警/简报内容, 不自动生成投资建议。

每个渠道只负责「把一段文字送到一个地址」, 不解析内容语义。
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import socket
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

logger = logging.getLogger(__name__)


@dataclass
class SendResult:
    ok: bool
    channel: str
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "channel": self.channel, "message": self.message}


def _http_post_json(url: str, payload: dict, headers: Optional[dict] = None, timeout: int = 10) -> dict:
    """用标准库 urllib 发 POST JSON;失败返回 {"ok": False, "error": ...}。"""
    import urllib.request
    import urllib.error

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:300]
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}", "body": str(e)[:200]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


def _http_get(url: str, timeout: int = 10) -> dict:
    import urllib.request
    import urllib.error

    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")[:300]
            return {"ok": 200 <= resp.status < 300, "status": resp.status, "body": body}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:200]}


# ---------------- 各渠道实现 ----------------


def send_serverchan(sckey: str, title: str, body: str) -> SendResult:
    """Server酱(Turbo):GET https://sctapi.ftqq.com/{key}.send?title=&desp="""
    sckey = (sckey or "").strip()
    if not sckey:
        return SendResult(False, "serverchan", "缺少 SendKey")
    url = f"https://sctapi.ftqq.com/{sckey}.send?" + urlencode({"title": title[:32], "desp": body[:2000]})
    res = _http_get(url)
    return SendResult(res["ok"], "serverchan", res.get("error") or res.get("body", ""))


def send_pushplus(token: str, title: str, body: str) -> SendResult:
    """PushPlus:POST http://www.pushplus.plus/send {token, title, content, template}"""
    token = (token or "").strip()
    if not token:
        return SendResult(False, "pushplus", "缺少 token")
    res = _http_post_json(
        "http://www.pushplus.plus/send",
        {"token": token, "title": title[:32], "content": body[:2000], "template": "txt"},
    )
    return SendResult(res["ok"], "pushplus", res.get("error") or res.get("body", ""))


def send_feishu(webhook: str, title: str, body: str) -> SendResult:
    """飞书自定义机器人 webhook:POST {msg_type: text, content: {text}}"""
    from backend.security.url_guard import validate_public_http_url

    webhook = (webhook or "").strip()
    parsed = urlparse(webhook)
    hostname = (parsed.hostname or "").lower()
    is_feishu = parsed.scheme == "https" and bool(hostname) and hostname in {"open.feishu.cn", "open.larksuite.com"}
    if not is_feishu:
        return SendResult(False, "feishu", "webhook 缺失或非飞书地址")
    try:
        # 第二道防线:目标主机必须为公网 IP(私网/环回/链路本地一律拒绝)
        safe_url = validate_public_http_url(webhook, allow_local=False)
    except ValueError:
        return SendResult(False, "feishu", "webhook 缺失或非飞书地址")
    # [:3500] 必须在 f-string 外(飞书文本上限 ~3500 字), 否则是字面文本会原样发送。
    res = _http_post_json(
        safe_url,
        {"msg_type": "text", "content": {"text": f"{title}\n\n{body}"[:3500]}},
    )
    return SendResult(res["ok"], "feishu", res.get("error") or res.get("body", ""))


def _smtp_connect_host(host: str) -> str | None:
    """Return a validated, pinned SMTP connection target.

    The public-host path returns the first validated IP rather than the input
    hostname, preventing DNS rebinding between validation and ``smtplib``'s
    socket connection. Private relays remain an explicit opt-in escape hatch.
    """
    if os.environ.get("ALPHASCOPE_ALLOW_PRIVATE_SMTP", "").strip().lower() in {"1", "true", "yes", "on"}:
        return host
    try:
        addrinfo = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return None
    public_addresses: list[str] = []
    try:
        for info in addrinfo:
            address = info[4][0]
            ip = ipaddress.ip_address(address)
            if any(
                (
                    ip.is_private,
                    ip.is_loopback,
                    ip.is_link_local,
                    ip.is_multicast,
                    ip.is_reserved,
                    ip.is_unspecified,
                )
            ):
                return None
            if address not in public_addresses:
                public_addresses.append(address)
    except ValueError:
        return None
    return public_addresses[0] if public_addresses else None


def send_telegram(bot_token: str, chat_id: str, title: str, body: str) -> SendResult:
    """Telegram Bot:GET https://api.telegram.org/bot{token}/sendMessage?chat_id=&text="""
    bot_token = (bot_token or "").strip()
    chat_id = (chat_id or "").strip()
    if not bot_token or not chat_id:
        return SendResult(False, "telegram", "缺少 bot_token 或 chat_id")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage?" + urlencode(
        {"chat_id": chat_id, "text": f"{title}\n\n{body}"[:3500], "parse_mode": "HTML"}
    )
    res = _http_get(url)
    return SendResult(res["ok"], "telegram", res.get("error") or res.get("body", ""))


def send_email(
    smtp_host: str,
    smtp_port: int,
    username: str,
    password: str,
    from_addr: str,
    to_addr: str,
    title: str,
    body: str,
) -> SendResult:
    """SMTP 邮件(标准库 smtplib);TLS 587 / SSL 465。"""
    import smtplib
    import ssl
    from email.mime.text import MIMEText

    if not all([smtp_host, username, password, from_addr, to_addr]):
        return SendResult(False, "email", "SMTP 配置不完整")
    connect_host = _smtp_connect_host(smtp_host)
    if not connect_host:
        return SendResult(False, "email", "SMTP 主机位于内网/环回, 如需私网中继请设置 ALPHASCOPE_ALLOW_PRIVATE_SMTP=1")
    msg = MIMEText(body[:8000], "plain", "utf-8")
    msg["Subject"] = title[:120]
    msg["From"] = from_addr
    msg["To"] = to_addr
    try:
        port = int(smtp_port or 587)
        tls_context = ssl.create_default_context()
        if port == 465:
            client = smtplib.SMTP_SSL(timeout=15, context=tls_context)
            client._host = smtp_host
            client.connect(connect_host, port)
            with client as s:
                s.login(username, password)
                s.sendmail(from_addr, [to_addr], msg.as_string())
        else:
            client = smtplib.SMTP(timeout=15)
            client._host = smtp_host
            client.connect(connect_host, port)
            with client as s:
                s.starttls(context=tls_context)
                s.login(username, password)
                s.sendmail(from_addr, [to_addr], msg.as_string())
        return SendResult(True, "email", "ok")
    except Exception as e:  # noqa: BLE001
        return SendResult(False, "email", str(e)[:200])


# ---------------- 统一分发 ----------------

CHANNELS = ["serverchan", "pushplus", "feishu", "telegram", "email"]


def dispatch(channel: str, config: dict, title: str, body: str) -> SendResult:
    """按渠道名分发。config 为该渠道的凭证 dict。未知渠道返回失败。"""
    try:
        if channel == "serverchan":
            return send_serverchan(config.get("sckey", ""), title, body)
        if channel == "pushplus":
            return send_pushplus(config.get("token", ""), title, body)
        if channel == "feishu":
            return send_feishu(config.get("webhook", ""), title, body)
        if channel == "telegram":
            return send_telegram(config.get("bot_token", ""), config.get("chat_id", ""), title, body)
        if channel == "email":
            return send_email(
                config.get("smtp_host", ""),
                int(config.get("smtp_port", 587)),
                config.get("username", ""),
                config.get("password", ""),
                config.get("from_addr", ""),
                config.get("to_addr", ""),
                title,
                body,
            )
    except Exception as e:  # noqa: BLE001
        return SendResult(False, channel, f"分发异常: {str(e)[:160]}")
    return SendResult(False, channel, f"未知渠道: {channel}")
