"""Tests for realistic A-share trading constraints (T+1, stamp duty, slippage,
price-limit filter, and look-ahead-free execution).

These tests target the honest-backtest layer added in v1.9.x:

* :mod:`backend.quant.constraints` - cost model, T+1, price-limit filter
* :class:`backend.quant.engine.BacktestEngine` - deferred (next-bar) execution
  that guarantees a signal computed from bar ``i``'s close is never filled on
  bar ``i``.

The whole module is pure / deterministic and needs no network or LLM.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ----------------------------------------------------------------
# Shared fixtures
# ----------------------------------------------------------------


def _trailing_bars() -> list[dict]:
    """Monotonically rising bars with explicit opens for next-bar execution."""
    return [
        {
            "date": "2025-01-01",
            "open": 10.0,
            "high": 10.5,
            "low": 9.8,
            "close": 10.0,
            "volume": 1000,
        },
        {
            "date": "2025-01-02",
            "open": 10.1,
            "high": 10.6,
            "low": 10.0,
            "close": 10.2,
            "volume": 1000,
        },
        {
            "date": "2025-01-03",
            "open": 10.3,
            "high": 10.7,
            "low": 10.2,
            "close": 10.4,
            "volume": 1000,
        },
        {
            "date": "2025-01-04",
            "open": 10.5,
            "high": 10.9,
            "low": 10.4,
            "close": 10.6,
            "volume": 1000,
        },
        {
            "date": "2025-01-05",
            "open": 10.7,
            "high": 11.1,
            "low": 10.6,
            "close": 10.8,
            "volume": 1000,
        },
    ]


def _zero_cost():
    """A cost model with no frictions, to isolate timing/look-ahead behaviour."""
    from backend.quant.constraints import TradingCostModel

    return TradingCostModel(slippage_rate=0.0, commission_rate=0.0, stamp_duty_rate=0.0)


def _fixturize(strategy_cls):
    """Register a fixture strategy so the engine's quick path also sees it."""
    from backend.quant.strategies import StrategyRegistry

    StrategyRegistry.register(strategy_cls.name, strategy_cls)
    return strategy_cls


# ----------------------------------------------------------------
# TradingCostModel
# ----------------------------------------------------------------


class TestTradingCostModel:
    def test_buy_cost_applies_adverse_slippage(self):
        from backend.quant.constraints import TradingCostModel

        m = TradingCostModel(slippage_rate=0.001)
        fill, turnover, commission = m.buy_cost(100, 10.0)
        # buyer pays more: 10 * (1+0.001) = 10.01
        assert abs(fill - 10.01) < 1e-9
        assert abs(turnover - 1000.999999) < 1e-3

    def test_sell_proceeds_apply_adverse_slippage_and_stamp(self):
        from backend.quant.constraints import TradingCostModel

        m = TradingCostModel(slippage_rate=0.001, stamp_duty_rate=0.0005)
        fill, turnover, commission, stamp = m.sell_proceeds(100, 10.0)
        # seller receives less: 10 * (1-0.001) = 9.99
        assert abs(fill - 9.99) < 1e-9
        assert abs(stamp - 100 * 9.99 * 0.0005) < 1e-9

    def test_commission_respects_minimum_charge(self):
        from backend.quant.constraints import TradingCostModel

        m = TradingCostModel(commission_rate=0.0003, commission_min=5.0)
        # tiny trade: turnover 100 * 0.0003 = 0.03 -> floored to 5.0
        assert m.commission(100.0) == 5.0
        # large trade: turnover 100000 * 0.0003 = 30 -> above min
        assert abs(m.commission(100000.0) - 30.0) < 1e-9

    def test_stamp_duty_charged_only_on_sell_path(self):
        from backend.quant.constraints import TradingCostModel

        m = TradingCostModel(stamp_duty_rate=0.0005)
        _, _, _ = m.buy_cost(100, 10.0)  # buy path
        _, _, _, stamp = m.sell_proceeds(100, 10.0)  # sell path
        assert stamp > 0


# ----------------------------------------------------------------
# T1Constraint
# ----------------------------------------------------------------


class TestT1Constraint:
    def test_cannot_sell_same_day(self):
        from backend.quant.constraints import T1Constraint

        t1 = T1Constraint(enabled=True)
        t1.record_buy("600519", 5)
        assert t1.can_sell("600519", 5) is False  # same bar
        assert t1.can_sell("600519", 6) is True  # next bar

    def test_pre_existing_holding_is_sellable(self):
        from backend.quant.constraints import T1Constraint

        t1 = T1Constraint(enabled=True)
        # A position carried into the backtest has no recorded acquisition bar.
        assert t1.can_sell("600519", 0) is True

    def test_disabled_allows_intraday_reversal(self):
        from backend.quant.constraints import T1Constraint

        t1 = T1Constraint(enabled=False)
        t1.record_buy("600519", 5)
        assert t1.can_sell("600519", 5) is True


# ----------------------------------------------------------------
# PriceLimitFilter
# ----------------------------------------------------------------


class TestPriceLimitFilter:
    def test_limit_up_blocks_buy(self):
        from backend.quant.constraints import PriceLimitFilter

        pl = PriceLimitFilter(band=0.10)
        # prev close 10 -> limit up 11.00
        bar = {"close": 11.00}
        assert pl.is_limit_up(bar, 10.0) is True
        assert pl.tradable(bar, 10.0, "buy") is False
        assert pl.tradable(bar, 10.0, "sell") is True

    def test_limit_down_blocks_sell(self):
        from backend.quant.constraints import PriceLimitFilter

        pl = PriceLimitFilter(band=0.10)
        # prev close 10 -> limit down 9.00
        bar = {"close": 9.00}
        assert pl.is_limit_down(bar, 10.0) is True
        assert pl.tradable(bar, 10.0, "sell") is False
        assert pl.tradable(bar, 10.0, "buy") is True

    def test_normal_bar_is_tradable_both_sides(self):
        from backend.quant.constraints import PriceLimitFilter

        pl = PriceLimitFilter(band=0.10)
        bar = {"close": 10.50}
        assert pl.tradable(bar, 10.0, "buy") is True
        assert pl.tradable(bar, 10.0, "sell") is True

    def test_st_band(self):
        from backend.quant.constraints import PriceLimitFilter

        pl = PriceLimitFilter(band=0.05)
        # prev close 10 -> ST limit up 10.50
        assert pl.is_limit_up({"close": 10.50}, 10.0) is True
        # 11.00 is beyond ST band -> not a limit-up lock
        assert pl.is_limit_up({"close": 11.00}, 10.0) is False


# ----------------------------------------------------------------
# Engine: look-ahead-free execution
# ----------------------------------------------------------------


@_fixturize
class _BuyOnBar1:
    """Toy strategy emitting a single BUY on bar index 1."""

    from backend.quant.strategies import BaseStrategy as _Base

    name = "buy_on_bar1"
    description = "test fixture: buy once on bar 1"
    default_params: dict = {}

    def __init__(self, params=None):
        self.params = {}

    def generate_signals(self, bars, portfolio_state=None):
        from backend.quant.strategies import Signal

        out = []
        for i in range(len(bars)):
            if i == 1:
                out.append(Signal("buy", "TEST", shares=100, reason="fixture"))
            else:
                out.append(Signal("hold", "TEST"))
        return out


@_fixturize
class _SignalOnLastBar:
    """Emits a BUY only on the final bar (no next bar to fill on)."""

    name = "signal_on_last"
    description = "fixture"
    default_params: dict = {}

    def __init__(self, params=None):
        self.params = {}

    def generate_signals(self, bars, portfolio_state=None):
        from backend.quant.strategies import Signal

        last = len(bars) - 1
        out = []
        for i in range(len(bars)):
            if i == last:
                out.append(Signal("buy", "TEST", shares=100, reason="last"))
            else:
                out.append(Signal("hold", "TEST"))
        return out


@_fixturize
class _RoundTrip:
    """Buy on bar 1, sell on bar 3."""

    name = "round_trip"
    description = "fixture"
    default_params: dict = {}

    def __init__(self, params=None):
        self.params = {}

    def generate_signals(self, bars, portfolio_state=None):
        from backend.quant.strategies import Signal

        out = []
        for i in range(len(bars)):
            if i == 1:
                out.append(Signal("buy", "TEST", shares=1000, reason="b"))
            elif i == 3:
                out.append(Signal("sell", "TEST", reason="s"))
            else:
                out.append(Signal("hold", "TEST"))
        return out


class TestEngineLookAheadSafety:
    def test_signal_fills_next_bar_not_same_bar(self):
        """A BUY generated at bar 1 fills at bar 2's OPEN, never bar 1's CLOSE."""
        from backend.quant.engine import BacktestEngine

        engine = BacktestEngine(
            initial_capital=100000,
            enable_t_plus_1=False,
            enable_price_limit=False,
            execution_price="open",
            cost_model=_zero_cost(),
        )
        result = engine.run(_BuyOnBar1(), _trailing_bars(), "TEST")
        buys = [t for t in result.trades if t["side"] == "buy"]
        assert len(buys) == 1
        # Zero slippage + next-bar open: bar index 2 open = 10.3
        assert abs(buys[0]["price"] - 10.3) < 1e-9
        # Fill date is bar index 2, not the signal bar index 1.
        assert buys[0]["timestamp"] == "2025-01-03"

    def test_no_hindsight_fill_on_last_bar(self):
        """A signal on the very last bar has no next bar, so the order is dropped."""
        from backend.quant.engine import BacktestEngine

        engine = BacktestEngine(
            initial_capital=100000,
            enable_t_plus_1=False,
            enable_price_limit=False,
            execution_price="open",
            cost_model=_zero_cost(),
        )
        result = engine.run(_SignalOnLastBar(), _trailing_bars(), "TEST")
        assert [t for t in result.trades if t["side"] == "buy"] == []


class TestEngineFrictions:
    def test_t_plus_1_allows_next_day_exit(self):
        """Buy fills on bar 2 (acquired index 2); a sell emitted on bar 2 fills
        on bar 3, which is > 2, so T+1 allows it."""
        from backend.quant.engine import BacktestEngine

        engine = BacktestEngine(
            initial_capital=100000,
            enable_t_plus_1=True,
            enable_price_limit=False,
            execution_price="open",
            cost_model=_zero_cost(),
        )
        result = engine.run(_RoundTrip(), _trailing_bars(), "TEST")
        sells = [t for t in result.trades if t["side"] == "sell"]
        assert len(sells) == 1
        # No T+1 violation should be recorded on the happy path.
        assert [v for v in result.risk_violations if v["rule"] == "t_plus_1"] == []

    def test_stamp_duty_and_slippage_reduce_pnl(self):
        """Frictions must strictly reduce a round-trip's realised PnL."""
        from backend.quant.constraints import TradingCostModel
        from backend.quant.engine import BacktestEngine

        bars = _trailing_bars()
        common = dict(
            initial_capital=100000,
            enable_t_plus_1=False,
            enable_price_limit=False,
            execution_price="open",
        )
        zero = BacktestEngine(
            cost_model=TradingCostModel(slippage_rate=0.0, commission_rate=0.0, stamp_duty_rate=0.0),
            **common,
        ).run(_RoundTrip(), bars, "TEST")
        costly = BacktestEngine(
            cost_model=TradingCostModel(slippage_rate=0.002, commission_rate=0.0003, stamp_duty_rate=0.0005),
            **common,
        ).run(_RoundTrip(), bars, "TEST")

        zero_sell = [t for t in zero.trades if t["side"] == "sell"][0]
        costly_sell = [t for t in costly.trades if t["side"] == "sell"][0]
        assert costly_sell["pnl"] < zero_sell["pnl"]
        assert costly.equity_curve[-1] < zero.equity_curve[-1]

    def test_assumptions_are_disclosed(self):
        """The result must declare its friction assumptions (auditability)."""
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import MAStrategy

        engine = BacktestEngine(initial_capital=100000)
        bars = [
            {
                "date": f"2025-01-{i + 1:02d}",
                "open": 10.0 + i,
                "high": 10.5 + i,
                "low": 9.8 + i,
                "close": 10.0 + i,
                "volume": 1000,
            }
            for i in range(30)
        ]
        result = engine.run(MAStrategy(), bars, "TEST")
        d = result.to_dict()
        assert "assumptions" in d
        a = result.assumptions
        assert a["t_plus_1"] is True
        assert a["price_limit_filter"] is True
        assert "stamp_duty_rate" in a
        assert "slippage_rate" in a
        assert a["execution_price"] == "open"


# ----------------------------------------------------------------
# Backward compatibility
# ----------------------------------------------------------------


class TestBackwardCompat:
    def test_legacy_construction_still_works(self):
        """Old callers passing only (initial_capital, commission_rate) keep working."""
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import MACDMomentumStrategy

        engine = BacktestEngine(initial_capital=100000, commission_rate=0.001)
        bars = [
            {
                "date": f"2025-01-{i + 1:02d}",
                "open": 10.0,
                "high": 10.5,
                "low": 9.8,
                "close": 10.0 + (i % 5) * 0.2,
                "volume": 1000,
            }
            for i in range(60)
        ]
        result = engine.run(MACDMomentumStrategy(), bars, "TEST")
        assert "total_return" in result.performance
        assert "sharpe_ratio" in result.performance

    def test_portfolio_accepts_optional_fees(self):
        """execute_buy/execute_sell accept optional fee kwargs and fall back when omitted."""
        from backend.quant.portfolio import Portfolio

        # legacy call (no kwargs)
        p = Portfolio(initial_capital=100000)
        assert p.execute_buy("600519", 100, 10.0, "2025-01-01") is True
        # new call with explicit commission + stamp duty
        p2 = Portfolio(initial_capital=100000)
        assert p2.execute_buy("600519", 100, 10.0, "2025-01-01", commission=5.0) is True
        assert p2.execute_sell("600519", 100, 11.0, "2025-01-02", commission=5.0, stamp_duty=0.55) is True
        sell_trade = [t for t in p2.trades if t.side == "sell"][0]
        assert abs(sell_trade.pnl - ((11.0 - 10.0) * 100 - 5.0 - 0.55)) < 1e-9
