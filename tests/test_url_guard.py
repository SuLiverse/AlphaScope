"""url_guard SSRF 防护测试 — 纯函数, 不触网(getaddrinfo 用 monkeypatch 注入)。"""

from __future__ import annotations

import socket

import pytest

from backend.security import url_guard


def _mock_getaddrinfo(ip: str):
    """造一个始终解析到 ip 的 getaddrinfo 替身。"""

    def _fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, port or 80))]

    return _fake


class TestSchemeAndHost:
    def test_rejects_non_http(self):
        with pytest.raises(ValueError, match="http/https"):
            url_guard.validate_public_http_url("ftp://example.com/x")

    def test_rejects_missing_host(self):
        with pytest.raises(ValueError, match="host"):
            url_guard.validate_public_http_url("http:///path")

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            url_guard.validate_public_http_url("")


class TestLocalhost:
    def test_rejects_localhost(self):
        with pytest.raises(ValueError, match="Localhost"):
            url_guard.validate_public_http_url("http://localhost:8000/x")

    def test_rejects_dot_localhost(self):
        with pytest.raises(ValueError):
            url_guard.validate_public_http_url("http://api.localhost/x")

    def test_rejects_0_0_0_0(self):
        with pytest.raises(ValueError):
            url_guard.validate_public_http_url("http://0.0.0.0/x")


class TestPrivateIPs:
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://10.0.0.1/x",
            "http://192.168.1.1/x",
            "http://172.16.0.1/x",
            "http://172.31.255.255/x",
            "http://169.254.169.254/latest/meta-data/",  # 云元数据端点
        ],
    )
    def test_rejects(self, url):
        with pytest.raises(ValueError, match="not allowed"):
            url_guard.validate_public_http_url(url)


class TestDnsRebinding:
    def test_rejects_resolved_to_loopback(self, monkeypatch):
        # 域名解析到 127.0.0.1 → 拒(DNS rebinding 如 127.0.0.1.nip.io)
        monkeypatch.setattr(url_guard.socket, "getaddrinfo", _mock_getaddrinfo("127.0.0.1"))
        with pytest.raises(ValueError, match="not allowed"):
            url_guard.validate_public_http_url("http://127.0.0.1.nip.io/x")

    def test_rejects_resolved_to_private(self, monkeypatch):
        monkeypatch.setattr(url_guard.socket, "getaddrinfo", _mock_getaddrinfo("10.1.2.3"))
        with pytest.raises(ValueError, match="not allowed"):
            url_guard.validate_public_http_url("http://internal.example.com/x")

    def test_allows_resolved_to_public(self, monkeypatch):
        monkeypatch.setattr(url_guard.socket, "getaddrinfo", _mock_getaddrinfo("93.184.216.34"))
        assert (
            url_guard.validate_public_http_url("http://example.com/x") == "http://example.com/x"
        )

    def test_rejects_unresolved(self, monkeypatch):
        def _raise(*a, **k):
            raise socket.gaierror("no such host")

        monkeypatch.setattr(url_guard.socket, "getaddrinfo", _raise)
        with pytest.raises(ValueError, match="cannot be resolved"):
            url_guard.validate_public_http_url("http://nonexistent.invalid/x")


class TestAllowLocal:
    def test_allow_local_true_bypasses_localhost(self):
        assert (
            url_guard.validate_public_http_url("http://localhost:8000/x", allow_local=True)
            == "http://localhost:8000/x"
        )

    def test_allow_local_true_bypasses_private_ip(self):
        assert (
            url_guard.validate_public_http_url("http://127.0.0.1/x", allow_local=True)
            == "http://127.0.0.1/x"
        )

    def test_env_opt_in_allows_localhost(self, monkeypatch):
        monkeypatch.setenv("ALPHASCOPE_ALLOW_LOCAL_FETCH", "1")
        assert url_guard.validate_public_http_url("http://localhost/x") == "http://localhost/x"

    def test_env_opt_out_rejects(self, monkeypatch):
        monkeypatch.delenv("ALPHASCOPE_ALLOW_LOCAL_FETCH", raising=False)
        with pytest.raises(ValueError):
            url_guard.validate_public_http_url("http://localhost/x")
