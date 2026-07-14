"""Rate limit unit tests."""

from __future__ import annotations

from backend.security.rate_limit import check_rate_limit, is_expensive_path, reset_for_tests


def test_expensive_paths():
    assert is_expensive_path("/api/analysis/run")
    assert is_expensive_path("/api/quant/evolve")
    assert not is_expensive_path("/health")
    assert not is_expensive_path("/api/prices/600519")


def test_rate_limit_allows_then_blocks(monkeypatch):
    reset_for_tests()
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPM", "3")
    monkeypatch.setenv("ALPHASCOPE_RATE_LIMIT_RPH", "100")
    reset_for_tests()
    key = "test-client-1"
    assert check_rate_limit(key)["allowed"] is True
    assert check_rate_limit(key)["allowed"] is True
    assert check_rate_limit(key)["allowed"] is True
    blocked = check_rate_limit(key)
    assert blocked["allowed"] is False
    assert blocked.get("reason") == "rpm"
