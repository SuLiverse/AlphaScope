"""Turtle-style Donchian-channel breakout strategy.

Buy on a breakout above the N-day high (new high water mark); sell on a break
below the M-day low. The canonical trend-following rule (Richard Dennis /
Turtles), parameterised for daily A-share bars.
"""

from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class TurtleBreakoutStrategy(BaseStrategy):
    """海龟(唐奇安通道)突破策略: 突破N日高点买入，跌破M日低点卖出。"""

    name = "turtle"
    description = "海龟突破策略: 突破N日新高买入，跌破M日新低卖出(唐奇安通道)"
    default_params = {
        "entry_period": 20,  # breakout above 20-day high
        "exit_period": 10,  # exit below 10-day low
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        entry = self.params["entry_period"]
        exit_p = self.params["exit_period"]

        highs = [b.get("high", b["close"]) for b in bars]
        lows = [b.get("low", b["close"]) for b in bars]
        closes = self._closes(bars)
        signals: list[Signal] = []
        for i in range(len(bars)):
            if i < entry:
                # warm-up: no Donchian channel yet (signals[i] uses bar i only).
                signals.append(Signal("hold", bars[i].get("symbol", ""), reason="数据不足"))
                continue
            prev_high = max(highs[i - entry : i])  # exclude today's high (no look-ahead)
            prev_low = min(lows[i - exit_p : i])
            symbol = bars[i].get("symbol", "")
            close = closes[i]
            if close > prev_high:
                shares = self._calc_shares(close, portfolio_state)
                signals.append(
                    Signal(
                        "buy",
                        symbol,
                        shares=shares,
                        reason=f"突破 {entry}日高点 {prev_high:.2f}",
                    )
                )
            elif close < prev_low:
                signals.append(Signal("sell", symbol, reason=f"跌破 {exit_p}日低点 {prev_low:.2f}"))
            else:
                signals.append(Signal("hold", symbol, reason="通道内"))
        assert len(signals) == len(bars)
        return signals


StrategyRegistry.register(TurtleBreakoutStrategy.name, TurtleBreakoutStrategy)
