"""Turtle-style Donchian-channel breakout strategy.

Buy on a breakout above the N-day high (new high water mark); sell on a break
below the M-day low. Optional extras (off by default so legacy backtests stay
comparable): System-2 55-day entry, ATR/N stop, 0.5N pyramid.

ATR / N uses TR = max(H-L, |H-PDC|, |L-PDC|) and the SMA of the *previous*
``atr_period`` TRs (today's TR is excluded — unlike the trend-tool ``calc_n``).
The Donchian channel also excludes the current bar. Signals stay aligned to
``len(bars)`` (plan 003: ``signals[i]`` uses bar ``i`` and earlier only).
"""

from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


def _true_ranges(highs: list[float], lows: list[float], closes: list[float]) -> list[float]:
    """True range per bar. Bar 0 has no prior close, so TR = H-L."""
    trs: list[float] = []
    for i in range(len(closes)):
        hl = highs[i] - lows[i]
        if i == 0:
            trs.append(max(hl, 0.0))
            continue
        pdc = closes[i - 1]
        trs.append(max(hl, abs(highs[i] - pdc), abs(lows[i] - pdc)))
    return trs


def _n_excluding_today(trs: list[float], i: int, period: int) -> float:
    """N at bar ``i`` = SMA of TR[i-period:i] (does not include today's TR)."""
    if period <= 0 or i < period:
        return 0.0
    window = trs[i - period : i]
    if not window:
        return 0.0
    return sum(window) / len(window)


class TurtleBreakoutStrategy(BaseStrategy):
    """海龟(唐奇安通道)突破策略: 突破N日高点买入，跌破M日低点卖出。"""

    name = "turtle"
    description = "海龟突破策略: 突破N日新高买入，跌破M日新低卖出(唐奇安通道)"
    default_params = {
        "entry_period": 20,  # System 1
        "exit_period": 10,
        "system2_period": 55,  # 0 = disable System 2
        "use_atr_stop": False,  # default off — keep legacy backtests comparable
        "atr_period": 20,
        "stop_n_mult": 2.0,
        "pyramid": False,  # default off
        "pyramid_step_n": 0.5,
        "max_units": 4,
        "allow_short": False,  # A-share default: no short open
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        entry = int(self.params["entry_period"])
        exit_p = int(self.params["exit_period"])
        system2 = int(self.params.get("system2_period") or 0)
        use_atr_stop = bool(self.params.get("use_atr_stop", False))
        atr_period = int(self.params.get("atr_period") or 20)
        stop_n_mult = float(self.params.get("stop_n_mult") or 2.0)
        pyramid = bool(self.params.get("pyramid", False))
        pyramid_step_n = float(self.params.get("pyramid_step_n") or 0.5)
        max_units = int(self.params.get("max_units") or 4)
        # allow_short is accepted so callers can pass it, but A-share default
        # forbids short-open and forbids mapping a short cover to buy.
        _allow_short = bool(self.params.get("allow_short", False))  # noqa: F841

        highs = [b.get("high", b["close"]) for b in bars]
        lows = [b.get("low", b["close"]) for b in bars]
        closes = self._closes(bars)
        trs = _true_ranges(highs, lows, closes)
        signals: list[Signal] = []

        # Default path (no ATR stop, no pyramid): identical to the pre-027 loop
        # so existing backtest numbers stay put. System-2 is an extra *entry*
        # predicate; with entry=20 and system2=55 it cannot fire without System-1.
        if not use_atr_stop and not pyramid:
            for i in range(len(bars)):
                if i < entry:
                    signals.append(Signal("hold", bars[i].get("symbol", ""), reason="数据不足"))
                    continue
                prev_high = max(highs[i - entry : i])
                prev_low = min(lows[i - exit_p : i])
                s2_break = False
                if system2 > 0 and i >= system2:
                    s2_high = max(highs[i - system2 : i])
                    s2_break = closes[i] > s2_high
                symbol = bars[i].get("symbol", "")
                close = closes[i]
                if close > prev_high or s2_break:
                    shares = self._calc_shares(close, portfolio_state)
                    if s2_break and close <= prev_high:
                        s2_high = max(highs[i - system2 : i])
                        why = f"突破 {system2}日高点 {s2_high:.2f}"
                    else:
                        why = f"突破 {entry}日高点 {prev_high:.2f}"
                    signals.append(Signal("buy", symbol, shares=shares, reason=why))
                elif close < prev_low:
                    signals.append(Signal("sell", symbol, reason=f"跌破 {exit_p}日低点 {prev_low:.2f}"))
                else:
                    signals.append(Signal("hold", symbol, reason="通道内"))
            assert len(signals) == len(bars)
            return signals

        units = 0
        entry_px = 0.0
        last_add_px = 0.0
        for i in range(len(bars)):
            symbol = bars[i].get("symbol", "")
            close = closes[i]
            if i < entry:
                signals.append(Signal("hold", symbol, reason="数据不足"))
                continue
            prev_high = max(highs[i - entry : i])
            prev_low = min(lows[i - exit_p : i])
            n_val = _n_excluding_today(trs, i, atr_period)
            s2_break = False
            if system2 > 0 and i >= system2:
                s2_high = max(highs[i - system2 : i])
                s2_break = close > s2_high

            if use_atr_stop and units > 0 and n_val > 0 and close < last_add_px - stop_n_mult * n_val:
                signals.append(
                    Signal(
                        "sell",
                        symbol,
                        reason=f"ATR止损 收盘跌破入场- {stop_n_mult:g}N ({last_add_px - stop_n_mult * n_val:.2f})",
                    )
                )
                units = 0
                entry_px = 0.0
                last_add_px = 0.0
                continue

            if units > 0 and close < prev_low:
                signals.append(Signal("sell", symbol, reason=f"跌破 {exit_p}日低点 {prev_low:.2f}"))
                units = 0
                entry_px = 0.0
                last_add_px = 0.0
                continue

            if units == 0 and (close > prev_high or s2_break):
                shares = self._calc_shares(close, portfolio_state)
                if s2_break and not close > prev_high:
                    why = f"突破 {system2}日高点"
                else:
                    why = f"突破 {entry}日高点 {prev_high:.2f}"
                signals.append(Signal("buy", symbol, shares=shares, reason=why))
                units = 1
                entry_px = close
                last_add_px = close
                continue

            if pyramid and units > 0 and units < max_units and n_val > 0 and pyramid_step_n > 0:
                next_add = entry_px + units * pyramid_step_n * n_val
                if close >= next_add:
                    units += 1
                    last_add_px = close
                    shares = self._calc_shares(close, portfolio_state)
                    signals.append(
                        Signal(
                            "buy",
                            symbol,
                            shares=shares,
                            reason=f"加仓 第 {units} 单位 (0.5N 阶梯, 触发价 {next_add:.2f})",
                        )
                    )
                    continue

            signals.append(Signal("hold", symbol, reason="通道内" if units == 0 else f"持仓 {units} 单位"))

        assert len(signals) == len(bars)
        return signals


StrategyRegistry.register(TurtleBreakoutStrategy.name, TurtleBreakoutStrategy)
