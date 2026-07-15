"""本地 LLM 预设测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.models.local_presets import (
    list_local_presets,
    probe_local_endpoint,
)


def test_list_presets_contains_ollama_and_lmstudio():
    presets = list_local_presets()
    ids = {p["id"] for p in presets}
    assert "ollama" in ids
    assert "lmstudio" in ids
    for p in presets:
        assert p["base_url"].startswith("http")
        assert "local_base_url_allowed" in p


def test_probe_without_opt_in_never_opens_network(monkeypatch):
    monkeypatch.delenv("ALLOW_LOCAL_LLM_BASE_URL", raising=False)
    with patch("backend.models.local_presets.create_ssrf_safe_http_client") as build_client:
        result = probe_local_endpoint("http://127.0.0.1:9", timeout=0.3)

    build_client.assert_not_called()
    assert result == {"available": False, "error": "url_not_allowed"}


def test_probe_unreachable_is_safe(monkeypatch):
    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")
    # 极不可能存在的端口
    r = probe_local_endpoint("http://127.0.0.1:9", timeout=0.3)
    assert r["available"] is False
    assert "error" in r
    assert "detail" not in r


@pytest.mark.parametrize("status_code", [200, 201, 204, 299])
def test_probe_accepts_only_success_statuses_without_reading_body(monkeypatch, status_code):
    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")
    response = MagicMock()
    response.status_code = status_code
    stream_context = MagicMock()
    stream_context.__enter__.return_value = response
    client = MagicMock()
    client.__enter__.return_value = client
    client.stream.return_value = stream_context

    with patch("backend.models.local_presets.create_ssrf_safe_http_client", return_value=client):
        result = probe_local_endpoint("http://127.0.0.1:11434/v1")

    assert result == {"available": True, "status_code": status_code}
    response.read.assert_not_called()


@pytest.mark.parametrize("status_code", [400, 401, 404, 500, 503])
def test_probe_rejects_unsuccessful_statuses_without_exposing_body(monkeypatch, status_code):
    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")
    response = MagicMock(status_code=status_code)
    response.text = "secret upstream response"
    stream_context = MagicMock()
    stream_context.__enter__.return_value = response
    client = MagicMock()
    client.__enter__.return_value = client
    client.stream.return_value = stream_context

    with patch("backend.models.local_presets.create_ssrf_safe_http_client", return_value=client):
        result = probe_local_endpoint("http://127.0.0.1:11434/v1")

    assert result == {
        "available": False,
        "error": "probe_failed",
        "status_code": status_code,
    }
    assert "secret" not in repr(result)
    response.read.assert_not_called()


def test_probe_sanitizes_transport_exceptions(monkeypatch):
    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")
    client = MagicMock()
    client.__enter__.return_value = client
    client.stream.side_effect = RuntimeError("secret at http://127.0.0.1/private")

    with patch("backend.models.local_presets.create_ssrf_safe_http_client", return_value=client):
        result = probe_local_endpoint("http://127.0.0.1:11434/v1")

    assert result == {"available": False, "error": "probe_failed"}


def test_probe_does_not_follow_redirects(monkeypatch):
    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")
    response = MagicMock(status_code=302, headers={"location": "http://169.254.169.254/latest/meta-data"})
    stream_context = MagicMock()
    stream_context.__enter__.return_value = response
    client = MagicMock()
    client.__enter__.return_value = client
    client.stream.return_value = stream_context

    with patch("backend.models.local_presets.create_ssrf_safe_http_client", return_value=client):
        result = probe_local_endpoint("http://127.0.0.1:11434/v1")

    assert result == {"available": False, "error": "redirect_not_allowed"}
    client.stream.assert_called_once()
