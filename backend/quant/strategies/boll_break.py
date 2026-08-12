"""Bollinger Band breakout strategy.

Buy when close breaks above the upper band (momentum expansion); sell when it
falls back below the middle band (mean). A classic volatility-breakout template.
"""

from __future__ import annotations

import math
from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class BollingerBreakStrategy(BaseStrategy):
    """Bollinger Band breakout: 上轨突破买入，回到中轨卖出。"""

    name = "boll_break"
    description = "布林带突破策略: 收盘突破上轨买入，回落跌破中轨卖出"
    default_params = {
        "period": 20,
        "std_mult": 2.0,
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        period = self.params["period"]

        closes = self._closes(bars)
        signals: list[Signal] = []
        for i in range(len(bars)):
            if i < period - 1:
                # warm-up: band needs `period` closes through bar i.
                signals.append(Signal("hold", bars[i].get("symbol", ""), reason="数据不足"))
                continue
            window = closes[i - period + 1 : i + 1]
            mid = sum(window) / period
            var = sum((v - mid) ** 2 for v in window) / period
            std = math.sqrt(var)
            upper = mid + self.params["std_mult"] * std

            close = closes[i]
            symbol = bars[i].get("symbol", "")
            if close > upper and std > 0:
                shares = self._calc_shares(close, portfolio_state)
                signals.append(
                    Signal(
                        "buy",
                        symbol,
                        shares=shares,
                        reason=f"突破布林上轨 ({close:.2f}>{upper:.2f})",
                    )
                )
            elif close < mid:
                signals.append(Signal("sell", symbol, reason=f"跌破布林中轨 ({close:.2f}<{mid:.2f})"))
            else:
                signals.append(Signal("hold", symbol, reason="轨道内运行"))
        assert len(signals) == len(bars)
        return signals


StrategyRegistry.register(BollingerBreakStrategy.name, BollingerBreakStrategy)
