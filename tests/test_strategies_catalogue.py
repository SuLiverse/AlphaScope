"""Tests for the strategy catalogue (one-file-per-strategy + auto-discovery).

Covers:
* Auto-discovery picks up every strategy module (>= 8 strategies, including the
  5 new ones: boll_break, momentum, dip_reversal, volume_break, turtle).
* Each strategy generates well-formed signals (actions in {buy,sell,hold}) and
  runs end-to-end through the engine without error on deterministic bars.

Pure / deterministic - no network or LLM.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ----------------------------------------------------------------
# Deterministic bar generators that force both buy and sell conditions
# ----------------------------------------------------------------


def _trending_bars(n: int = 60, drift: float = 0.004) -> list[dict]:
    """Steadily rising bars - good for momentum buys."""
    bars = []
    p = 20.0
    for i in range(n):
        o = p
        c = round(p * (1 + drift + (i % 3 - 1) * 0.001), 2)
        bars.append(
            {
                "date": f"2025-01-{(i % 28) + 1:02d}",
                "open": o,
                "high": round(max(o, c) * 1.01, 2),
                "low": round(min(o, c) * 0.99, 2),
                "close": c,
                "volume": 500000,
            }
        )
        p = c
    return bars


def _breakout_bars(n: int = 60) -> list[dict]:
    """Flat consolidation then a clean upside breakout - forces boll/turtle buys.

    The first 40 bars are range-bound (so highs/lows are stable); bars 40+ gap
    up decisively so the close clears the prior high band.
    """
    bars = []
    for i in range(n):
        if i < 40:
            o = c = round(20.0 + (i % 5) * 0.05, 2)  # tight range ~20.0-20.2
        else:
            o = c = round(20.2 + (i - 40) * 0.5, 2)  # sharp breakout up
        bars.append(
            {
                "date": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
                "open": o,
                "high": round(max(o, c) * 1.005, 2),
                "low": round(min(o, c) * 0.995, 2),
                "close": c,
                "volume": 500000,
            }
        )
    return bars


def _oscillating_bars(n: int = 80) -> list[dict]:
    """Sinusoidal bars - drives MA/RSI/Bollinger crossovers both ways."""
    import math

    bars = []
    p = 30.0
    for i in range(n):
        wave = math.sin(i / 5.0) * 0.05
        o = p
        c = round(p * (1 + wave), 2)
        bars.append(
            {
                "date": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
                "open": o,
                "high": round(max(o, c) * 1.01, 2),
                "low": round(min(o, c) * 0.99, 2),
                "close": c,
                "volume": 500000,
            }
        )
        p = c
    return bars


def _dip_bars(n: int = 60) -> list[dict]:
    """Bars with a sharp drop then recovery - exercises dip_reversal."""
    bars = []
    p = 50.0
    for i in range(n):
        # drop hard in the middle, then recover
        if 15 <= i <= 25:
            change = -0.02
        elif 26 <= i <= 45:
            change = 0.012
        else:
            change = 0.0
        o = p
        c = round(p * (1 + change), 2)
        bars.append(
            {
                "date": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
                "open": o,
                "high": round(max(o, c) * 1.01, 2),
                "low": round(min(o, c) * 0.99, 2),
                "close": c,
                "volume": 500000,
            }
        )
        p = c
    return bars


def _volume_spike_bars(n: int = 50) -> list[dict]:
    """Bars with a volume spike on an up-day - exercises volume_break."""
    bars = []
    p = 20.0
    for i in range(n):
        o = p
        up = 1 if i % 2 == 0 else -1
        c = round(p * (1 + up * 0.005), 2)
        # huge volume on day 30 with an up move
        vol = 5_000_000 if (i == 30 and up == 1) else 300_000
        bars.append(
            {
                "date": f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}",
                "open": o,
                "high": round(max(o, c) * 1.01, 2),
                "low": round(min(o, c) * 0.99, 2),
                "close": c,
                "volume": vol,
            }
        )
        p = c
    return bars


# ----------------------------------------------------------------
# Auto-discovery
# ----------------------------------------------------------------


class TestStrategyAutoDiscovery:
    def test_at_least_eight_strategies_registered(self):
        from backend.quant.strategies import StrategyRegistry

        names = {s["name"] for s in StrategyRegistry.list_strategies()}
        expected = {
            "macd_momentum",
            "ma_crossover",
            "rsi_reversal",
            "boll_break",
            "momentum",
            "dip_reversal",
            "volume_break",
            "turtle",
        }
        missing = expected - names
        assert not missing, f"missing strategies: {missing}"
        assert len(names) >= 8

    def test_get_and_create_each_strategy(self):
        from backend.quant.strategies import StrategyRegistry

        for name in (
            "macd_momentum",
            "ma_crossover",
            "rsi_reversal",
            "boll_break",
            "momentum",
            "dip_reversal",
            "volume_break",
            "turtle",
        ):
            cls = StrategyRegistry.get(name)
            assert cls is not None, f"{name} not registered"
            inst = StrategyRegistry.create(name)
            assert inst is not None and inst.name == name

    def test_registry_is_idempotent(self):
        from backend.quant.strategies import StrategyRegistry

        n1 = len(StrategyRegistry.list_strategies())
        # Trigger discovery again indirectly via get() on an unknown name.
        StrategyRegistry.get("__definitely_not_a_strategy__")
        n2 = len(StrategyRegistry.list_strategies())
        assert n1 == n2  # no duplicate registration


# ----------------------------------------------------------------
# Per-strategy signal sanity
# ----------------------------------------------------------------


class TestNewStrategiesGenerateSignals:
    def test_boll_break_on_breakout(self):
        from backend.quant.strategies import BollingerBreakStrategy

        sigs = BollingerBreakStrategy().generate_signals(_breakout_bars())
        assert len(sigs) > 0
        assert all(s.action in {"buy", "sell", "hold"} for s in sigs)
        # a clean upside breakout must break the upper band
        assert any(s.action == "buy" for s in sigs)

    def test_momentum_on_trend(self):
        from backend.quant.strategies import MomentumStrategy

        sigs = MomentumStrategy().generate_signals(_trending_bars())
        assert len(sigs) > 0
        assert any(s.action == "buy" for s in sigs)

    def test_dip_reversal_buys_on_dip(self):
        from backend.quant.strategies import DipReversalStrategy

        sigs = DipReversalStrategy().generate_signals(_dip_bars())
        assert len(sigs) > 0
        assert any(s.action == "buy" for s in sigs)

    def test_volume_break_on_spike(self):
        from backend.quant.strategies import VolumeBreakStrategy

        sigs = VolumeBreakStrategy().generate_signals(_volume_spike_bars())
        assert len(sigs) > 0
        assert any(s.action == "buy" for s in sigs)

    def test_turtle_on_breakout(self):
        from backend.quant.strategies import TurtleBreakoutStrategy

        sigs = TurtleBreakoutStrategy().generate_signals(_breakout_bars())
        assert len(sigs) > 0
        # a clean breakout clears the prior 20-day high
        assert any(s.action == "buy" for s in sigs)

    def test_all_strategies_run_through_engine(self):
        """Every registered strategy must run end-to-end via the engine."""
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import StrategyRegistry

        for item in StrategyRegistry.list_strategies():
            strategy = StrategyRegistry.create(item["name"])
            result = BacktestEngine(initial_capital=100000).run(strategy, _oscillating_bars(), "TEST")
            assert result.strategy_name == item["name"]
            assert "total_return" in result.performance
            assert len(result.equity_curve) > 0

    def test_strategies_handle_insufficient_bars(self):
        """All strategies must degrade gracefully when bars are too few.

        New contract (plan 003): signals stay aligned to len(bars), warm-up
        positions are padded with hold — the engine treats them as no orders.
        """
        from backend.quant.strategies import (
            BollingerBreakStrategy,
            DipReversalStrategy,
            MomentumStrategy,
            TurtleBreakoutStrategy,
            VolumeBreakStrategy,
        )

        tiny = _trending_bars(5)
        for cls in (
            BollingerBreakStrategy,
            MomentumStrategy,
            DipReversalStrategy,
            VolumeBreakStrategy,
            TurtleBreakoutStrategy,
        ):
            sigs = cls().generate_signals(tiny)
            assert len(sigs) == len(tiny)
            assert all(s.action == "hold" for s in sigs)
