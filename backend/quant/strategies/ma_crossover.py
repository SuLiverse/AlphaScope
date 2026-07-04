"""Moving-average crossover strategy (Migrated from the legacy monolith)."""

from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class MAStrategy(BaseStrategy):
    """Moving average crossover strategy.

    Buy when the short MA crosses above the long MA; sell on the reverse cross.
    """

    name = "ma_crossover"
    description = "均线交叉策略: 短期均线上穿长期均线买入，下穿卖出"
    default_params = {
        "short_period": 5,
        "long_period": 20,
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        if len(bars) < self.params["long_period"]:
            return []

        closes = self._closes(bars)
        short_ma = self._sma(closes, self.params["short_period"])
        long_ma = self._sma(closes, self.params["long_period"])

        signals = []
        for i in range(1, len(bars)):
            if i < self.params["long_period"]:
                signals.append(Signal("hold", bars[i].get("symbol", ""), reason="数据不足"))
                continue

            prev_short = short_ma[i - 1]
            curr_short = short_ma[i]
            prev_long = long_ma[i - 1]
            curr_long = long_ma[i]

            if prev_short <= prev_long and curr_short > curr_long:
                shares = self._calc_shares(bars[i]["close"], portfolio_state)
                signals.append(
                    Signal(
                        "buy",
                        bars[i].get("symbol", ""),
                        shares=shares,
                        reason=f"MA{self.params['short_period']} 上穿 MA{self.params['long_period']}",
                    )
                )
            elif prev_short >= prev_long and curr_short < curr_long:
                signals.append(
                    Signal(
                        "sell",
                        bars[i].get("symbol", ""),
                        reason=f"MA{self.params['short_period']} 下穿 MA{self.params['long_period']}",
                    )
                )
            else:
                signals.append(Signal("hold", bars[i].get("symbol", ""), reason="无信号"))

        return signals


StrategyRegistry.register(MAStrategy.name, MAStrategy)
