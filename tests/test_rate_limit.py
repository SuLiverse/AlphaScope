"""Rate limit unit tests."""

from __future__ import annotations

import pytest

from backend.security.rate_limit import (
    _state_for_tests,
    check_rate_limit,
    client_key_from_request,
    is_expensive_path,
    reset_for_tests,
)


@pytest.fixture(autouse=True)
def clean_rate_limit_state():
    reset_for_tests()
    yield
    reset_for_tests()


def test_expensive_paths():
    assert is_expensive_path("/api/analysis/run")
    assert is_expensive_path("/api/quant/evolve")
    assert is_expensive_path("/api/quant/portfolio/backtest")
    assert is_expensive_path("/api/quant/portfolio/walk-forward")
    assert is_expensive_path("/api/quant/experiments/compare")
    assert is_expensive_path("/api/quant/compare-strategies")
    assert is_expensive_path("/api/settings/local-llm-presets/probe")
    assert is_expensive_path("/api/settings/providers/deepseek/test")
    assert not is_expensive_path("/health")
    assert not is_expensive_path("/api/prices/600519")
    assert not is_expensive_path("/api/analysisevil")
    assert not is_expensive_path("/api/quant/compare")
    assert not is_expensive_path("/api/settings/providers/deepseek")


def test_rate_limit_allows_then_blocks(monkeypatch):
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPM", "3")
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPH", "100")
    key = "test-client-1"
    assert check_rate_limit(key)["allowed"] is True
    assert check_rate_limit(key)["allowed"] is True
    assert check_rate_limit(key)["allowed"] is True
    blocked = check_rate_limit(key)
    assert blocked["allowed"] is False
    assert blocked.get("reason") == "rpm"


def test_bucket_store_is_bounded(monkeypatch):
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPM", "1000")
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPH", "1000")
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_MAX_BUCKETS", "2")

    for index in range(20):
        assert check_rate_limit(f"client-{index}")["allowed"] is True

    state = _state_for_tests()
    assert state["bucket_count"] <= 2
    assert state["max_buckets"] == 2


def test_environment_change_and_reset_reload_configuration(monkeypatch):
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPM", "3")
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPH", "10")
    assert check_rate_limit("first")["limit_rpm"] == 3

    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPM", "7")
    assert check_rate_limit("second")["limit_rpm"] == 7
    assert _state_for_tests()["bucket_count"] == 1

    reset_for_tests()
    state = _state_for_tests()
    assert state["bucket_count"] == 0
    assert state["rpm"] == 30
    assert state["rph"] == 200


def test_unvalidated_token_is_not_used_as_bucket_identity(monkeypatch):
    class Request:
        headers = {"X-AlphaScope-Local-Token": "random-token"}
        query_params = {}
        client = type("Client", (), {"host": "127.0.0.1"})()

    monkeypatch.delenv("ALPHASCOPE_LOCAL_API_TOKEN", raising=False)
    assert client_key_from_request(Request()) == "ip:127.0.0.1"

    monkeypatch.setenv("ALPHASCOPE_LOCAL_API_TOKEN", "real-token")
    assert client_key_from_request(Request()) == "ip:127.0.0.1"
