"""Turtle strategy parameter contract (plan 027).

Locks default Donchian behaviour and the optional ATR-stop / dual-channel /
no-short extras. Offline and deterministic.

Plan 032 additions: parameter validation (entry/exit/atr/system2 bounds) and
a warm-up lower bound so ``exit_period > entry_period`` no longer produces
negative-start slices (empty-slice ``ValueError`` or a wrongly wrapped channel).
"""

from __future__ import annotations

import pytest

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


class TestParamGuardsPlan032:
    """Plan 032: 参数校验 + warmup 下界保护。

    旧代码只有 ``i < entry`` 守卫: exit_period > entry_period 时
    ``lows[i - exit_p : i]`` 负起点回卷 → 空切片 ``min() ValueError``
    (遗传优化器按独立区间采样 routinely 采到该区域后被 _safe_eval 静默记 _WORST)。
    """

    def test_exit_greater_than_entry_no_crash_and_first_25_bars_hold(self):
        # 旧代码: i=20 时 lows[20-25:20] 负起点回卷 → min() iterable is empty。
        bars = [_flat(i, 20.0) for i in range(40)]
        sigs = TurtleBreakoutStrategy(
            {"entry_period": 20, "exit_period": 25, "system2_period": 0}
        ).generate_signals(bars)
        assert len(sigs) == len(bars)
        assert all(s.action == "hold" for s in sigs[:25])
        assert all("数据不足" in s.reason for s in sigs[:25])
        # warmup 恰为 max(entry, exit)=25: 第 25 根起已按通道评估(横盘 → 通道内)。
        assert sigs[25].reason == "通道内"

    def test_entry_period_zero_raises_value_error(self):
        bars = [_flat(i, 20.0) for i in range(30)]
        with pytest.raises(ValueError, match="entry"):
            TurtleBreakoutStrategy({"entry_period": 0}).generate_signals(bars)

    def test_exit_period_zero_raises_value_error(self):
        bars = [_flat(i, 20.0) for i in range(30)]
        with pytest.raises(ValueError, match="exit"):
            TurtleBreakoutStrategy({"exit_period": 0}).generate_signals(bars)

    def test_atr_path_exit_greater_than_entry_no_crash(self):
        bars = [_flat(i, 20.0, width=0.3) for i in range(40)]
        sigs = TurtleBreakoutStrategy(
            {
                "use_atr_stop": True,
                "entry_period": 20,
                "exit_period": 25,
                "atr_period": 20,
                "system2_period": 0,
            }
        ).generate_signals(bars)
        assert len(sigs) == len(bars)
        assert all(s.action == "hold" for s in sigs[:25])
        assert all("数据不足" in s.reason for s in sigs[:25])
        assert sigs[25].reason == "通道内"

    def test_atr_path_entry_period_zero_raises_value_error(self):
        bars = [_flat(i, 20.0, width=0.3) for i in range(30)]
        with pytest.raises(ValueError, match="entry"):
            TurtleBreakoutStrategy({"use_atr_stop": True, "entry_period": 0}).generate_signals(bars)


class TestWarmupSemanticsPlan032:
    def test_default_warmup_equals_entry_system2_must_not_inflate_it(self):
        """Plan 032: 默认参数下 warmup 必须等于旧 entry(=20)。

        027 承诺「默认路径数字保持不变」: system2 通道自带 ``i >= system2``
        守卫, 不得计入 warmup——否则默认 system2=55 会把 20..54 根变成
        「数据不足」, 改变默认回测数字。第 entry 根就应按通道评估(此处卖出)。
        """
        bars = [_flat(i, 20.0) for i in range(21)]
        bars[20] = _bar(20, 20.0, 20.1, 10.0, 10.5)  # 第 entry 根大跌破下轨
        sigs = TurtleBreakoutStrategy().generate_signals(bars)  # system2 默认 55
        assert sigs[20].action == "sell"
        assert "数据不足" not in sigs[20].reason
