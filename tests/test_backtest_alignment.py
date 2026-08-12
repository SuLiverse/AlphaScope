"""Characterization tests for plan 003: strategy-signal bar alignment and the
three metric-basis fixes (annualization on calendar days, equity-curve date
alignment, single-attempt order filling).

Written RED first: on the pre-fix engine these tests must fail, pinning the
defects:

* built-in strategies return a shorter, offset signal table (``signals[k]`` is
  produced by bar ``k+1``), so the engine's next-open fill lands one bar early
  (fill at the *signal* bar's open, not the following bar's);
* ``calc_annualized_return`` is fed trading-day counts (~252/year) but
  exponentiated on a 365-day basis, inflating one-year results;
* the single-symbol API payload zips ``dates`` against ``equity_curve``,
  pinning the opening capital to the first trading day and dropping the last
  day's mark-to-market;
* a limit-locked order is kept pending and stale-retried on the next bar.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.quant.strategies import BaseStrategy, Signal, StrategyRegistry


def _zero_cost_model():
    from backend.quant.constraints import TradingCostModel

    return TradingCostModel(
        commission_rate=0.0,
        commission_min=0.0,
        stamp_duty_rate=0.0,
        slippage_rate=0.0,
    )


def _zero_friction_engine(**overrides):
    from backend.quant.engine import BacktestEngine

    kwargs = dict(
        initial_capital=100000,
        commission_rate=0.0,
        cost_model=_zero_cost_model(),
        enable_t_plus_1=False,
        enable_price_limit=False,
    )
    kwargs.update(overrides)
    return BacktestEngine(**kwargs)


class _FixedScheduleStrategy(BaseStrategy):
    """Test fixture: emits a pre-set per-bar signal schedule, hold elsewhere."""

    name = "fixed_schedule_alignment"
    description = "test fixture"
    default_params: dict = {}

    def __init__(self, schedule: dict[int, Signal], params=None):
        super().__init__()
        self._schedule = schedule

    def generate_signals(self, bars, portfolio_state=None):
        return [self._schedule.get(i, Signal("hold", "TEST")) for i in range(len(bars))]


class _UpSignalStrategy(BaseStrategy):
    """Toy strategy structured like the post-fix built-ins: bar-aligned with a
    warm-up hold at bar 0 (``signals[i]`` is produced by bar ``i`` inclusive)."""

    name = "alignment_probe_up"
    description = "test fixture"
    default_params: dict = {}

    def __init__(self, params=None):
        self.params = {}

    def generate_signals(self, bars, portfolio_state=None):
        closes = [b["close"] for b in bars]
        out = []
        for i in range(len(bars)):
            if i == 0:
                out.append(Signal("hold", "TEST", reason="warm-up"))
            elif closes[i] > closes[i - 1]:
                out.append(Signal("buy", "TEST", shares=100, reason="up"))
            else:
                out.append(Signal("hold", "TEST", reason="flat"))
        return out


PROBE_BARS = [
    {"date": "2026-01-01", "open": 100.0, "high": 100.0, "low": 9.0, "close": 10.0, "volume": 1000},
    {"date": "2026-01-02", "open": 101.0, "high": 101.0, "low": 10.0, "close": 11.0, "volume": 1000},
    {"date": "2026-01-03", "open": 102.0, "high": 102.0, "low": 11.0, "close": 12.0, "volume": 1000},
    {"date": "2026-01-04", "open": 103.0, "high": 103.0, "low": 12.0, "close": 13.0, "volume": 1000},
    {"date": "2026-01-05", "open": 104.0, "high": 104.0, "low": 13.0, "close": 14.0, "volume": 1000},
]


def _trend_bars(n: int, start: date = date(2026, 1, 1), symbol: str = "TEST") -> list[dict]:
    """Monotonic bars: opens 100, closes 10 + i*0.2 (distinguishable, rising)."""
    bars = []
    for i in range(n):
        close = 10.0 + i * 0.2
        bars.append(
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "symbol": symbol,
                "open": 100.0,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000,
            }
        )
    return bars


# ================================================================
# 1. Alignment probe: a buy produced from bar i must fill at bar i+1's open
# ================================================================


class TestAlignmentProbe:
    def test_buy_signal_fills_next_bar_open(self):
        engine = _zero_friction_engine()
        result = engine.run(_UpSignalStrategy(), PROBE_BARS, "TEST")

        buys = [t for t in result.trades if t["side"] == "buy"]
        assert len(buys) >= 1
        # The first rising close is bar 1, so the first buy (produced from bar 1)
        # must fill at bar 2's OPEN (102.0), never at bar 1's open (101.0).
        assert buys[0]["price"] == pytest.approx(102.0)
        assert buys[0]["timestamp"] == "2026-01-03"


# ================================================================
# 2. Length contract: every registered strategy aligns to len(bars)
# ================================================================


class TestLengthContract:
    def test_all_registered_strategies_align_to_bars(self):
        bars = _trend_bars(60)
        for item in StrategyRegistry.list_strategies():
            strategy = StrategyRegistry.create(item["name"])
            assert strategy is not None
            signals = strategy.generate_signals(bars, {"equity": 100000})
            assert len(signals) == len(bars), f"{item['name']} returned {len(signals)} signals for {len(bars)} bars"


# ================================================================
# 3. Annualization basis: calendar days, not trading days
# ================================================================


class TestAnnualizedBasis:
    def test_calc_annualized_return_365_days_is_identity(self):
        from backend.quant.metrics import calc_annualized_return

        assert abs(calc_annualized_return(0.10, 365) - 0.10) < 1e-9

    def test_annualized_equals_total_over_calendar_year(self):
        # 252 trading bars spanning roughly one calendar year: annualized
        # return must be ~= total return (tolerance 2pp). The pre-fix engine
        # feeds days=252 into a 365-day exponent, inflating the result.
        n = 252
        day = date(2025, 1, 1)
        dates: list[date] = []
        while len(dates) < n:
            if day.weekday() < 5:
                dates.append(day)
            day += timedelta(days=1)
        span = (dates[-1] - dates[0]).days
        assert 340 <= span <= 370, f"weekday span {span} days"

        bars = []
        for i, d in enumerate(dates):
            close = 100.0 + i * (10.0 / (n - 1))
            bars.append(
                {
                    "date": d.isoformat(),
                    "open": 100.0,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000,
                }
            )
        schedule = {1: Signal("buy", "TEST", shares=900)}
        from backend.quant.risk_controller import RiskConfig

        engine = _zero_friction_engine(risk_config=RiskConfig(max_position_pct=100, max_total_exposure_pct=100))
        result = engine.run(_FixedScheduleStrategy(schedule), bars, "TEST")

        assert result.performance["trading_days"] == n  # trading-day count keeps its meaning
        assert result.performance["total_return"] == pytest.approx(9.0, abs=0.1)
        assert abs(result.performance["annualized_return"] - result.performance["total_return"]) < 2.0


# ================================================================
# 4. Equity-curve / date alignment at the API payload layer
# ================================================================


class TestEquityCurveAlignment:
    def test_payload_equity_curve_aligned_to_dates(self, monkeypatch):
        from backend.api import quant_core
        from backend.api.quant_schemas import BacktestRequestBody

        # 6 bars, distinct opens/closes so every equity value is distinguishable.
        bars = []
        for i in range(6):
            close = 100.0 + i * 5.0
            bars.append(
                {
                    "date": f"2026-01-{i + 1:02d}",
                    "symbol": "TEST",
                    "open": 100.0,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000,
                }
            )
        # custom_rule with a tautology buys on every bar (fills from bar 1 on).
        monkeypatch.setattr(quant_core, "_require_bars", lambda *a, **k: (bars, "local_preview"))
        monkeypatch.setattr(quant_core, "_persist_experiment", lambda *a, **k: None)
        body = BacktestRequestBody(
            strategy_id="custom_rule",
            symbol="TEST",
            start_date=bars[0]["date"],
            end_date=bars[-1]["date"],
            initial_capital=100000.0,
            params={"buy_rules": [{"field": "close", "op": ">", "value": 0}], "position_size_pct": 20},
        )
        payload = quant_core._run_local_backtest(body)
        points = payload["equity_curve"]

        assert len(points) == len(bars)
        # First point carries the first bar's date; last point the last bar's.
        assert points[0]["date"] == bars[0]["date"]
        assert points[-1]["date"] == bars[-1]["date"]
        # The last point must be the mark-to-market AFTER the final bar (the
        # pre-fix zip pins opening capital to the first date and drops it).
        assert points[-1]["equity"] == pytest.approx(payload["metrics"]["final_equity"])
        # A fill at bar-1's open plus bar-1's close mark-to-market makes the
        # point aligned with bar 1 differ from initial capital. (Bar 0's point
        # equals initial capital by construction: nothing can fill on bar 0.)
        assert points[1]["equity"] != pytest.approx(100000.0)


# ================================================================
# 5. Limit-locked orders get exactly one fill attempt
# ================================================================


class TestStaleOrder:
    def test_limit_locked_order_is_dropped_not_retried(self):
        bars = [
            {"date": "2026-01-01", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000},
            {"date": "2026-01-02", "open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0, "volume": 1000},
            # bar 2 is limit-up vs prev close 10.0 (10% band): buy rejected
            {"date": "2026-01-03", "open": 10.0, "high": 11.0, "low": 10.0, "close": 11.0, "volume": 1000},
            # bar 3 is normal: the rejected order must NOT be stale-retried here
            {"date": "2026-01-04", "open": 12.0, "high": 12.0, "low": 12.0, "close": 12.0, "volume": 1000},
            {"date": "2026-01-05", "open": 12.0, "high": 12.0, "low": 12.0, "close": 12.0, "volume": 1000},
        ]
        schedule = {1: Signal("buy", "TEST", shares=100)}
        engine = _zero_friction_engine(enable_price_limit=True)
        result = engine.run(_FixedScheduleStrategy(schedule), bars, "TEST")

        assert any(v["rule"] == "price_limit_locked" for v in result.risk_violations)
        buys = [t for t in result.trades if t["side"] == "buy"]
        assert buys == []
