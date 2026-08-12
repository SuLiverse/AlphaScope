"""Turtle strategy parameter contract (plan 027).

Locks default Donchian behaviour and the optional ATR-stop / dual-channel /
no-short extras. Offline and deterministic.
"""

from __future__ import annotations

from backend.quant.strategies.turtle import TurtleBreakoutStrategy


def _bar(i: int, o: float, h: float, lo: float, c: float) -> dict:
    month = (i // 28) + 1
    day = (i % 28) + 1
    return {
        "date": f"2025-{month:02d}-{day:02d}",
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": 500000,
        "symbol": "TEST",
    }


def _flat(i: int, price: float = 20.0, width: float = 0.2) -> dict:
    return _bar(i, price, price + width, price - width, price)


def _breakout_bars(n: int = 60) -> list[dict]:
    """Same generator as tests.test_strategies_catalogue._breakout_bars."""
    bars = []
    for i in range(n):
        if i < 40:
            o = c = round(20.0 + (i % 5) * 0.05, 2)
        else:
            o = c = round(20.2 + (i - 40) * 0.5, 2)
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


def _legacy_actions(bars: list[dict], entry: int = 20, exit_p: int = 10) -> list[str]:
    """Pre-upgrade turtle rule: close vs prior channel, no ATR / pyramid."""
    highs = [b.get("high", b["close"]) for b in bars]
    lows = [b.get("low", b["close"]) for b in bars]
    closes = [b["close"] for b in bars]
    out: list[str] = []
    for i in range(len(bars)):
        if i < entry:
            out.append("hold")
            continue
        prev_high = max(highs[i - entry : i])
        prev_low = min(lows[i - exit_p : i])
        if closes[i] > prev_high:
            out.append("buy")
        elif closes[i] < prev_low:
            out.append("sell")
        else:
            out.append("hold")
    return out


class TestDefaultRegression:
    def test_default_matches_legacy_breakout_bars(self):
        bars = _breakout_bars()
        sigs = TurtleBreakoutStrategy().generate_signals(bars)
        assert [s.action for s in sigs] == _legacy_actions(bars)

    def test_default_params_keep_new_flags_off(self):
        p = TurtleBreakoutStrategy.default_params
        assert p["use_atr_stop"] is False
        assert p["pyramid"] is False
        assert p["allow_short"] is False
        assert p["entry_period"] == 20
        assert p["exit_period"] == 10


class TestNoLookahead:
    def test_today_high_only_is_hold(self):
        """Wick prints a new high; close stays inside the prior channel → hold."""
        bars = [_flat(i, 20.0) for i in range(20)]
        # Prior 20-day high is 20.2. Today high=22 (new high) but close=20.1.
        bars.append(_bar(20, 20.0, 22.0, 19.8, 20.1))
        sigs = TurtleBreakoutStrategy().generate_signals(bars)
        assert len(sigs) == len(bars)
        assert sigs[-1].action == "hold"

    def test_signal_length_matches_bars(self):
        bars = _breakout_bars(45)
        sigs = TurtleBreakoutStrategy().generate_signals(bars)
        assert len(sigs) == len(bars)


class TestAtrStop:
    def test_atr_stop_sells_after_entry(self):
        """After a 20-day breakout, a close below entry-2N must emit sell."""
        bars = [_flat(i, 20.0, width=0.3) for i in range(25)]
        # Clean upside breakout (close clears prior 20-day high ~20.3).
        bars.append(_bar(25, 20.4, 22.0, 20.3, 21.8))
        # Subsequent bars collapse well below any reasonable entry-2N.
        for j in range(8):
            px = 21.8 - (j + 1) * 1.2
            bars.append(_bar(26 + j, px + 0.2, px + 0.3, px - 0.4, px))

        sigs = TurtleBreakoutStrategy(
            {
                "use_atr_stop": True,
                "atr_period": 20,
                "stop_n_mult": 2.0,
                "system2_period": 0,
            }
        ).generate_signals(bars)
        assert len(sigs) == len(bars)
        assert any(s.action == "buy" for s in sigs)
        buy_i = next(i for i, s in enumerate(sigs) if s.action == "buy")
        assert any(s.action == "sell" for s in sigs[buy_i + 1 :])
        sell = next(s for s in sigs[buy_i + 1 :] if s.action == "sell")
        assert "止损" in sell.reason or "2N" in sell.reason or "ATR" in sell.reason


class TestAllowShort:
    def test_breakdown_is_flatten_not_short_open(self):
        """allow_short=False: a crash through the lower rail is only a long exit."""
        bars = [_flat(i, 20.0) for i in range(20)]
        bars.append(_bar(20, 20.0, 20.1, 10.0, 10.5))  # large down bar
        sigs = TurtleBreakoutStrategy({"allow_short": False}).generate_signals(bars)
        assert all(s.action in {"buy", "sell", "hold"} for s in sigs)
        last = sigs[-1]
        # May be sell (flatten) or hold; must not describe a short open.
        assert last.action != "buy"
        blob = " ".join(s.reason for s in sigs)
        assert "开空" not in blob
        assert "做空" not in blob
        assert "sell-to-open" not in blob.lower()
        assert "空头平仓" not in blob
