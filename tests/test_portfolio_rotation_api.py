"""API coverage for the multi-asset ETF momentum + RSRS research endpoints."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


@pytest.fixture
def client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _bars(n: int, *, base: float, drift: float):
    start = datetime(2020, 1, 1)
    rows = []
    for index in range(n):
        close = base + drift * index + 3 * math.sin(index / 4)
        open_price = close * (0.998 + 0.002 * math.sin(index / 3))
        rows.append(
            {
                "symbol": "",
                "date": (start + timedelta(days=index)).strftime("%Y-%m-%d"),
                "open": round(open_price, 4),
                "high": round(max(open_price, close) * (1.01 + 0.002 * math.sin(index / 5)), 4),
                "low": round(min(open_price, close) * (0.99 - 0.001 * math.cos(index / 7)), 4),
                "close": round(close, 4),
                "volume": 100000 + index,
            }
        )
    return rows


def _portfolio_data(n: int = 160):
    symbols = {"510300": (100, 0.18), "518880": (80, 0.08), "513100": (60, -0.02)}
    result = {}
    for symbol, (base, drift) in symbols.items():
        rows = _bars(n, base=base, drift=drift)
        for row in rows:
            row["symbol"] = symbol
        result[symbol] = rows
    return result, {symbol: "local_price_store" for symbol in symbols}


def _params():
    return {
        "momentum_window": 10,
        "ma_window": 10,
        "rsrs_window": 5,
        "rsrs_history": 20,
        "rsrs_entry": -10,
        "rsrs_exit": -20,
        "rebalance_interval": 5,
        "top_k": 1,
        "commission_min": 0,
        "require_positive_momentum": False,
        "require_above_ma": False,
    }


@pytest.mark.anyio
async def test_portfolio_backtest_endpoint_uses_isolated_engine(client, monkeypatch):
    import backend.api.quant_core as quant_core

    bars, sources = _portfolio_data()
    monkeypatch.setattr(quant_core, "_require_portfolio_bars", lambda body: (bars, sources))
    monkeypatch.setattr(quant_core, "_persist_experiment", lambda payload: None)

    response = await client.post(
        "/api/quant/portfolio/backtest",
        json={
            "symbols": ["510300", "518880", "513100"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "params": _params(),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    payload = data["data"]
    assert payload["engine"] == "local_portfolio_rotation"
    assert payload["strategy_id"] == "etf_momentum_rsrs"
    assert payload["status"] == "completed"
    assert payload["universe"] == sorted(bars)
    assert payload["assumptions"]["signal_timing"].endswith("open[t+1].")
    assert payload["data_sources"] == sources


@pytest.mark.anyio
async def test_portfolio_walk_forward_endpoint_returns_oos_contract(client, monkeypatch):
    import backend.api.quant_core as quant_core

    bars, sources = _portfolio_data()
    monkeypatch.setattr(quant_core, "_require_portfolio_bars", lambda body: (bars, sources))
    monkeypatch.setattr(quant_core, "_persist_experiment", lambda payload: None)

    response = await client.post(
        "/api/quant/portfolio/walk-forward",
        json={
            "symbols": ["510300", "518880", "513100"],
            "start_date": "2020-01-01",
            "end_date": "2020-12-31",
            "params": _params(),
            "n_splits": 3,
            "scheme": "anchored",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    payload = data["data"]
    assert payload["engine"] == "local_portfolio_rotation"
    assert payload["n_windows"] >= 2
    assert payload["aggregate"]["windows_evaluated"] == payload["n_windows"]
    assert "investment advice" in payload["disclaimer"]


def test_portfolio_symbol_guard_rejects_duplicates():
    import pytest

    from backend.api.quant_core import _unique_portfolio_symbols

    with pytest.raises(ValueError, match="至少需要两个"):
        _unique_portfolio_symbols(["510300", "510300"])


def test_portfolio_loader_requires_indicator_warmup_and_full_date_coverage(monkeypatch):
    import backend.api.quant_core as quant_core
    from backend.api.quant_schemas import PortfolioBacktestRequestBody
    from backend.quant.etf_rotation import make_config

    calls = []

    def fake_require(_body, **kwargs):
        calls.append(kwargs)
        return [{"symbol": kwargs["symbol"], "date": "2020-01-01", "close": 1}], "provider"

    monkeypatch.setattr(quant_core, "_require_bars", fake_require)
    body = PortfolioBacktestRequestBody(
        symbols=["510300", "518880"],
        start_date="2020-01-01",
        end_date="2025-12-31",
    )

    quant_core._require_portfolio_bars(body)

    expected = make_config().warmup_bars + 2
    assert [call["min_bars"] for call in calls] == [expected, expected]
    assert all(call["require_full_coverage"] is True for call in calls)


def test_history_limit_covers_requested_range_without_silent_1000_bar_cap():
    from backend.api.quant_core import _history_limit

    assert _history_limit(datetime(2020, 1, 1), datetime(2025, 12, 31), 271) > 1_000


def test_requested_date_coverage_rejects_a_large_internal_gap():
    from backend.api.quant_core import _covers_requested_dates

    early = [{"date": (datetime(2020, 1, 1) + timedelta(days=index)).isoformat()} for index in range(140)]
    late = [{"date": (datetime(2024, 8, 15) + timedelta(days=index)).isoformat()} for index in range(140)]

    assert not _covers_requested_dates(early + late, datetime(2020, 1, 1), datetime(2024, 12, 31))


def test_requested_date_coverage_allows_normal_market_holidays():
    from backend.api.quant_core import _covers_requested_dates

    bars = [{"date": "2020-01-02"}, {"date": "2020-01-10"}, {"date": "2020-01-20"}]

    assert _covers_requested_dates(bars, datetime(2020, 1, 1), datetime(2020, 1, 21))


def test_portfolio_history_refreshes_when_cached_rows_are_too_short(monkeypatch):
    import backend.api.quant_core as quant_core

    provider_bars = _bars(400, base=100, drift=0.1)
    for row in provider_bars:
        row["symbol"] = "510300"
    calls = []

    class _Registry:
        def get(self, **kwargs):
            calls.append(kwargs)
            return provider_bars

    monkeypatch.setattr("backend.price_store.get_prices", lambda *args, **kwargs: provider_bars[-30:])
    monkeypatch.setattr("backend.price_store.save_price_bars", lambda rows: len(rows))
    monkeypatch.setattr("backend.providers.registry.get_registry", lambda: _Registry())
    monkeypatch.setattr(quant_core, "call_with_timeout", lambda callback, *args, **kwargs: callback())

    bars, source = quant_core._load_local_bars(
        "510300",
        "2020-01-01",
        "2021-01-01",
        1_000_000,
        minimum_bars=271,
        require_full_coverage=True,
    )

    assert source == "provider"
    assert len(bars) == len(provider_bars)
    assert calls[0]["market"] == "CN"


def test_portfolio_history_refreshes_when_cache_has_a_large_internal_gap(monkeypatch):
    import backend.api.quant_core as quant_core

    provider_bars = _bars(400, base=100, drift=0.1)
    for row in provider_bars:
        row["symbol"] = "510300"
    cached_bars = provider_bars[:135] + provider_bars[-136:]
    calls = []

    class _Registry:
        def get(self, **kwargs):
            calls.append(kwargs)
            return provider_bars

    monkeypatch.setattr("backend.price_store.get_prices", lambda *args, **kwargs: cached_bars)
    monkeypatch.setattr("backend.price_store.save_price_bars", lambda rows: len(rows))
    monkeypatch.setattr("backend.providers.registry.get_registry", lambda: _Registry())
    monkeypatch.setattr(quant_core, "call_with_timeout", lambda callback, *args, **kwargs: callback())

    bars, source = quant_core._load_local_bars(
        "510300",
        "2020-01-01",
        "2021-01-01",
        1_000_000,
        minimum_bars=271,
        require_full_coverage=True,
    )

    assert source == "provider"
    assert bars == provider_bars
    assert calls
