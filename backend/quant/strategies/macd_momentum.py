"""MACD momentum strategy (Migrated from the legacy monolith)."""

from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class MACDMomentumStrategy(BaseStrategy):
    """MACD momentum strategy - buy on golden cross, sell on death cross."""

    name = "macd_momentum"
    description = "MACD 动量策略: 金叉买入，死叉卖出"
    default_params = {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        if len(bars) < self.params["slow_period"] + self.params["signal_period"]:
            return []

        closes = self._closes(bars)
        fast_ema = self._ema(closes, self.params["fast_period"])
        slow_ema = self._ema(closes, self.params["slow_period"])

        macd_line = [fast_ema[i] - slow_ema[i] for i in range(len(closes))]
        signal_line = self._ema(macd_line, self.params["signal_period"])

        signals = []
        for i in range(1, len(bars)):
            if i < self.params["slow_period"] + self.params["signal_period"]:
                signals.append(Signal("hold", bars[i].get("symbol", ""), reason="数据不足"))
                continue

            prev_macd = macd_line[i - 1]
            curr_macd = macd_line[i]
            prev_signal = signal_line[i - 1]
            curr_signal = signal_line[i]

            # Golden cross: MACD crosses above signal line
            if prev_macd <= prev_signal and curr_macd > curr_signal:
                shares = self._calc_shares(bars[i]["close"], portfolio_state)
                signals.append(
                    Signal(
                        "buy",
                        bars[i].get("symbol", ""),
                        shares=shares,
                        reason="MACD 金叉",
                    )
                )
            # Death cross: MACD crosses below signal line
            elif prev_macd >= prev_signal and curr_macd < curr_signal:
                signals.append(Signal("sell", bars[i].get("symbol", ""), reason="MACD 死叉"))
            else:
                signals.append(Signal("hold", bars[i].get("symbol", ""), reason="无信号"))

        return signals


StrategyRegistry.register(MACDMomentumStrategy.name, MACDMomentumStrategy)
