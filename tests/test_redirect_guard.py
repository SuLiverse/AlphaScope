"""重定向逐跳 SSRF 校验测试 — 全离线(monkeypatch requests.request, 不触网)。

对应 plan 030: ``url_guard.fetch_public_url`` 每一跳(含首跳)先
``validate_public_http_url(allow_local=False)`` 再请求, 堵住「首跳公网、
中间 30x 跳进内网」的盲 SSRF; 并冒烟 news/provider 两个接入点。
"""

from __future__ import annotations

import json as _json
import socket

import pytest

pytest.importorskip("requests")

import requests

from backend.api import news as news_api
from backend.providers import http_json_provider as hj
from backend.security import url_guard


def _mock_getaddrinfo(ips: dict[str, str]):
    """造一个按 host 查表解析的 getaddrinfo 替身(未登记的 host 解析失败)。"""

    def _fake(host, port, *args, **kwargs):
        ip = ips.get(host)
        if ip is None:
            raise socket.gaierror(f"unregistered host: {host}")
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, port or 80))]

    return _fake


class _FakeResponse:
    """requests.Response 替身: 仅实现 helper 与调用方用到的面。"""

    def __init__(
        self,
        status_code: int = 200,
        headers: dict | None = None,
        url: str = "",
        content: bytes = b"",
        encoding: str = "utf-8",
    ):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.encoding = encoding
        self._content = content

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 1):
        del chunk_size
        yield self._content

    def json(self):
        return _json.loads(self._content.decode("utf-8"))

    def close(self) -> None:
        return None


class _RequestLog:
    """替换 requests.request: 记录每次 (url, kwargs), 按脚本依次返回响应。"""

    def __init__(self, script: list[_FakeResponse]):
        self.script = list(script)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method, url, **kwargs):
        self.calls.append((url, kwargs))
        assert self.script, f"unexpected request: {method} {url}"
        return self.script.pop(0)


class TestFetchPublicUrl:
    def test_two_public_hops_ok(self, monkeypatch):
        # 两跳公网重定向 → 正常返回最终 response(合法多跳不误伤)
        monkeypatch.setattr(
            url_guard.socket,
            "getaddrinfo",
            _mock_getaddrinfo({"ads.example.com": "93.184.216.34", "cdn.example.com": "93.184.216.35"}),
        )
        log = _RequestLog(
            [
                _FakeResponse(301, {"Location": "https://cdn.example.com/final"}, url="https://ads.example.com/a"),
                _FakeResponse(200, url="https://cdn.example.com/final"),
            ]
        )
        monkeypatch.setattr(requests, "request", log)
        resp = url_guard.fetch_public_url("https://ads.example.com/a", timeout=(1.0, 1.0))
        assert resp.url == "https://cdn.example.com/final"
        assert [u for u, _ in log.calls] == ["https://ads.example.com/a", "https://cdn.example.com/final"]
        # 每一跳都必须以 allow_redirects=False 发出(手动逐跳循环的前提)
        assert all(kwargs.get("allow_redirects") is False for _, kwargs in log.calls)

    def test_redirect_into_loopback_blocked_before_request(self, monkeypatch):
        # 首跳公网、Location 指向 127.0.0.1 → 抛 ValueError, 且第二次请求从未发出
        monkeypatch.setattr(
            url_guard.socket,
            "getaddrinfo",
            _mock_getaddrinfo({"ads.example.com": "93.184.216.34"}),
        )
        log = _RequestLog(
            [_FakeResponse(302, {"Location": "http://127.0.0.1:8000/admin"}, url="https://ads.example.com/t")]
        )
        monkeypatch.setattr(requests, "request", log)
        with pytest.raises(ValueError, match="Localhost|not allowed"):
            url_guard.fetch_public_url("https://ads.example.com/t")
        assert len(log.calls) == 1  # 内网目标从未被请求

    def test_relative_location_resolved_against_current(self, monkeypatch):
        # 相对路径 Location: /next → urljoin 到当前 URL 后继续(仍是公网)
        monkeypatch.setattr(
            url_guard.socket,
            "getaddrinfo",
            _mock_getaddrinfo({"example.com": "93.184.216.34"}),
        )
        log = _RequestLog(
            [
                _FakeResponse(302, {"Location": "/next"}, url="https://example.com/a"),
                _FakeResponse(200, url="https://example.com/next"),
            ]
        )
        monkeypatch.setattr(requests, "request", log)
        resp = url_guard.fetch_public_url("https://example.com/a")
        assert resp.url == "https://example.com/next"
        assert [u for u, _ in log.calls] == ["https://example.com/a", "https://example.com/next"]

    def test_max_hops_exceeded(self, monkeypatch):
        # 重定向链超过 max_hops → ValueError
        monkeypatch.setattr(
            url_guard.socket,
            "getaddrinfo",
            _mock_getaddrinfo({f"h{i}.example.com": "93.184.216.34" for i in range(6)}),
        )
        script = [
            _FakeResponse(302, {"Location": f"https://h{i + 1}.example.com/x"}, url=f"https://h{i}.example.com/x")
            for i in range(4)
        ]
        log = _RequestLog(script)
        monkeypatch.setattr(requests, "request", log)
        with pytest.raises(ValueError, match="[Tt]oo many redirects"):
            url_guard.fetch_public_url("https://h0.example.com/x", max_hops=2)
        # 首跳 + max_hops 个重定向 = 3 次请求后拒绝
        assert len(log.calls) == 3

    def test_max_hops_boundary_allowed(self, monkeypatch):
        # 恰好 max_hops 跳 → 放行(上限不误伤合法链)
        monkeypatch.setattr(
            url_guard.socket,
            "getaddrinfo",
            _mock_getaddrinfo({f"h{i}.example.com": "93.184.216.34" for i in range(4)}),
        )
        script = [
            _FakeResponse(302, {"Location": f"https://h{i + 1}.example.com/x"}, url=f"https://h{i}.example.com/x")
            for i in range(2)
        ] + [_FakeResponse(200, url="https://h2.example.com/x")]
        log = _RequestLog(script)
        monkeypatch.setattr(requests, "request", log)
        resp = url_guard.fetch_public_url("https://h0.example.com/x", max_hops=2)
        assert resp.url == "https://h2.example.com/x"
        assert len(log.calls) == 3

    def test_first_hop_private_blocked_without_request(self, monkeypatch):
        # 首跳即内网 → 入口拒绝, 不发任何请求
        log = _RequestLog([])
        monkeypatch.setattr(requests, "request", log)
        with pytest.raises(ValueError):
            url_guard.fetch_public_url("http://127.0.0.1:8000/x")
        assert log.calls == []


class TestCallSites:
    def test_news_fetch_html_uses_guarded_fetch(self, monkeypatch):
        # news._fetch_html 接入冒烟: 底层经 fetch_public_url, 不再自动跟随重定向
        monkeypatch.setattr(
            url_guard.socket,
            "getaddrinfo",
            _mock_getaddrinfo({"example.com": "93.184.216.34"}),
        )
        log = _RequestLog(
            [
                _FakeResponse(
                    200,
                    {"content-type": "text/html; charset=utf-8"},
                    url="https://example.com/story",
                    content=b"<html><head><title>t</title></head></html>",
                ),
            ]
        )
        monkeypatch.setattr(requests, "request", log)
        final_url, text = news_api._fetch_html("https://example.com/story")
        assert final_url == "https://example.com/story"
        assert "t" in text
        assert len(log.calls) == 1
        assert log.calls[0][1].get("allow_redirects") is False
        assert log.calls[0][1].get("stream") is True

    def test_provider_fetch_json_uses_guarded_fetch(self, monkeypatch):
        # provider requests 路径接入冒烟: 经 fetch_public_url(allow_redirects=False)抓取
        monkeypatch.setattr(
            url_guard.socket,
            "getaddrinfo",
            _mock_getaddrinfo({"api.example.com": "93.184.216.34"}),
        )
        log = _RequestLog(
            [
                _FakeResponse(
                    200,
                    {"content-type": "application/json"},
                    url="https://api.example.com/x",
                    content=b'{"data": []}',
                ),
            ]
        )
        monkeypatch.setattr(requests, "request", log)
        res = hj.fetch_json("https://api.example.com/x")
        assert res["ok"] is True
        assert res["payload"] == {"data": []}
        assert len(log.calls) == 1
        assert log.calls[0][1].get("allow_redirects") is False

    def test_provider_post_body_sent_as_json(self, monkeypatch):
        # POST 源: body 经 json= 发送(与原 requests json= 行为一致, 不被表单编码)
        monkeypatch.setattr(
            url_guard.socket,
            "getaddrinfo",
            _mock_getaddrinfo({"api.example.com": "93.184.216.34"}),
        )
        log = _RequestLog(
            [
                _FakeResponse(
                    200,
                    {"content-type": "application/json"},
                    url="https://api.example.com/x",
                    content=b'{"ok": 1}',
                ),
            ]
        )
        monkeypatch.setattr(requests, "request", log)
        res = hj.fetch_json("https://api.example.com/x", method="POST", body={"a": 1})
        assert res["ok"] is True
        assert log.calls[0][1].get("json") == {"a": 1}
