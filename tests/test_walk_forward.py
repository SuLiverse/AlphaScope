"""Walk-forward analysis tests — temporal-robustness backtest splitting."""

from __future__ import annotations

import math
from datetime import datetime, timedelta


def _make_bars(n: int, start_close: float = 100.0, drift: float = 0.3, wobble: float = 6.0):
    """Deterministic OHLCV series: gentle uptrend + sine wobble. Fixed base date
    (not ``now``) so the data is fully reproducible."""
    base = datetime(2024, 1, 1)
    bars = []
    for i in range(n):
        close = start_close + drift * i + wobble * math.sin(i / 7.0)
        close = max(1.0, close)
        openp = close - 0.4
        high = max(openp, close) + 1.0
        low = min(openp, close) - 1.0
        bars.append(
            {
                "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": round(openp, 2),
                "high": round(high, 2),
                "low": round(max(0.5, low), 2),
                "close": round(close, 2),
                "volume": 10000 + (i % 5) * 1000,
            }
        )
    return bars


class TestWindowSplitting:
    def test_insufficient_data_is_failsafe(self):
        from backend.quant.walk_forward import run_walk_forward, INSUFFICIENT

        report = run_walk_forward("ma_crossover", _make_bars(20), symbol="TEST", n_splits=5)
        assert report.status == INSUFFICIENT
        assert report.n_windows == 0
        assert report.windows == []
        # never raises, aggregate still well-formed
        assert report.aggregate["robustness"] == "数据不足"

    def test_enough_data_produces_requested_windows(self):
        from backend.quant.walk_forward import run_walk_forward, OK, DEGRADED

        report = run_walk_forward("ma_crossover", _make_bars(240), symbol="TEST", n_splits=5)
        assert report.status in (OK, DEGRADED)
        assert report.n_windows >= 2
        assert report.n_windows <= 5

    def test_oos_windows_are_chronological_and_tiling(self):
        from backend.quant.walk_forward import run_walk_forward

        report = run_walk_forward("ma_crossover", _make_bars(240), symbol="TEST", n_splits=5)
        prev_oos_end = ""
        for w in report.windows:
            # IS precedes OOS within each window
            assert w.is_start_date <= w.is_end_date
            assert w.is_end_date <= w.oos_start_date
            assert w.oos_start_date <= w.oos_end_date
            # OOS segments advance forward, no backtracking
            assert w.oos_start_date >= prev_oos_end
            prev_oos_end = w.oos_end_date


class TestSchemes:
    def test_anchored_is_starts_at_bar_zero(self):
        from backend.quant.walk_forward import run_walk_forward

        bars = _make_bars(240)
        report = run_walk_forward("ma_crossover", bars, symbol="T", n_splits=5, scheme="anchored")
        assert report.scheme == "anchored"
        for w in report.windows:
            assert w.is_start_date == bars[0]["date"]

    def test_rolling_is_window_slides(self):
        from backend.quant.walk_forward import run_walk_forward

        report = run_walk_forward("ma_crossover", _make_bars(240), symbol="T", n_splits=5, scheme="rolling")
        assert report.scheme == "rolling"
        starts = [w.is_start_date for w in report.windows]
        # rolling IS start must be non-decreasing and not all identical
        assert starts == sorted(starts)
        assert len(set(starts)) > 1

    def test_invalid_scheme_defaults_to_anchored(self):
        from backend.quant.walk_forward import run_walk_forward

        report = run_walk_forward("ma_crossover", _make_bars(150), symbol="T", scheme="nonsense")
        assert report.scheme == "anchored"


class TestAggregateAndContract:
    def test_aggregate_fields_in_range(self):
        from backend.quant.walk_forward import run_walk_forward

        agg = run_walk_forward("ma_crossover", _make_bars(240), symbol="T", n_splits=5).aggregate
        assert 0.0 <= agg["consistency_score"] <= 100.0
        assert 0.0 <= agg["pct_profitable_windows"] <= 100.0
        assert agg["worst_oos_return"] <= agg["best_oos_return"]
        assert agg["windows_evaluated"] >= 2

    def test_full_period_present(self):
        from backend.quant.walk_forward import run_walk_forward

        report = run_walk_forward("ma_crossover", _make_bars(240), symbol="T", n_splits=5)
        assert report.full_period  # non-empty performance dict
        assert "total_return" in report.full_period

    def test_to_dict_roundtrip_has_disclaimer(self):
        from backend.quant.walk_forward import run_walk_forward

        d = run_walk_forward("ma_crossover", _make_bars(240), symbol="T").to_dict()
        assert "disclaimer" in d
        assert "不构成任何投资建议" in d["disclaimer"]
        assert isinstance(d["windows"], list)
        assert d["windows"] and "oos_return" in d["windows"][0]
        # assumptions carry the engine's honest-friction disclosure
        assert d["assumptions"].get("t_plus_1") is True

    def test_determinism(self):
        from backend.quant.walk_forward import run_walk_forward

        bars = _make_bars(240)
        a = run_walk_forward("ma_crossover", bars, symbol="T", n_splits=5).to_dict()
        b = run_walk_forward("ma_crossover", bars, symbol="T", n_splits=5).to_dict()
        assert a == b

    def test_unknown_strategy_degrades_without_raising(self):
        from backend.quant.walk_forward import run_walk_forward

        report = run_walk_forward("__no_such_strategy__", _make_bars(240), symbol="T")
        # factory yields None every window → no windows built, but no exception
        assert report.n_windows == 0
        assert report.full_period == {}

    def test_splits_clamped(self):
        from backend.quant.walk_forward import run_walk_forward

        # request absurd split count → clamped to <= 12, and auto-reduced to fit data
        report = run_walk_forward("ma_crossover", _make_bars(300), symbol="T", n_splits=99)
        assert report.requested_windows == 99
        assert report.n_windows <= 12


class TestInstanceInput:
    def test_accepts_strategy_instance(self):
        from backend.quant.walk_forward import run_walk_forward
        from backend.quant.strategies import StrategyRegistry

        strat = StrategyRegistry.create("ma_crossover", {})
        report = run_walk_forward(strat, _make_bars(240), symbol="T", n_splits=4)
        assert report.strategy_name == "ma_crossover"
        assert report.n_windows >= 2


class TestApiPayload:
    def test_local_walk_forward_payload(self):
        from unittest.mock import patch

        from backend.api.quant_core import _run_walk_forward_local
        from backend.api.quant_schemas import WalkForwardRequestBody

        body = WalkForwardRequestBody(
            strategy_id="ma_crossover",
            symbol="600519",
            start_date="2024-01-01",
            end_date="2024-12-31",
            n_splits=5,
            scheme="anchored",
        )
        bars = _make_bars(240)
        with patch(
            "backend.api.quant_core._load_local_bars",
            return_value=(bars, "local_price_store"),
        ):
            payload = _run_walk_forward_local(body)

        assert payload["mode"] == "walk_forward"
        assert payload["run_id"].startswith("wf-")
        assert payload["strategy_name"] == "ma_crossover"
        assert payload["bar_count"] == 240
        assert payload["data_source"] == "local_price_store"
        assert payload["n_windows"] >= 2
        assert isinstance(payload["windows"], list) and payload["windows"]
        assert "consistency_score" in payload["aggregate"]
        assert "不构成任何投资建议" in payload["disclaimer"]

    def test_unknown_strategy_raises_value_error(self):
        import pytest

        from backend.api.quant_core import _run_walk_forward_local
        from backend.api.quant_schemas import WalkForwardRequestBody

        body = WalkForwardRequestBody(
            strategy_id="__nope__",
            symbol="600519",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        with pytest.raises(ValueError):
            _run_walk_forward_local(body)
