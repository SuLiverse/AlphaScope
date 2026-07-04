"""RSI overbought/oversold reversal strategy (Migrated from the monolith)."""

from __future__ import annotations

import math
from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class RSIStrategy(BaseStrategy):
    """RSI overbought/oversold strategy: buy when RSI < oversold, sell when RSI > overbought."""

    name = "rsi_reversal"
    description = "RSI 超买超卖策略: RSI<30 买入，RSI>70 卖出"
    default_params = {
        "period": 14,
        "oversold": 30,
        "overbought": 70,
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        if len(bars) < self.params["period"] + 1:
            return []

        closes = self._closes(bars)
        rsi_values = self._calc_rsi(closes, self.params["period"])

        signals = []
        for i in range(len(rsi_values)):
            rsi = rsi_values[i]
            if math.isnan(rsi):
                signals.append(Signal("hold", bars[i + 1].get("symbol", ""), reason="数据不足"))
                continue

            if rsi < self.params["oversold"]:
                shares = self._calc_shares(bars[i + 1]["close"], portfolio_state)
                signals.append(
                    Signal(
                        "buy",
                        bars[i + 1].get("symbol", ""),
                        shares=shares,
                        reason=f"RSI={rsi:.1f} 超卖",
                    )
                )
            elif rsi > self.params["overbought"]:
                signals.append(
                    Signal(
                        "sell",
                        bars[i + 1].get("symbol", ""),
                        reason=f"RSI={rsi:.1f} 超买",
                    )
                )
            else:
                signals.append(
                    Signal(
                        "hold",
                        bars[i + 1].get("symbol", ""),
                        reason=f"RSI={rsi:.1f} 中性",
                    )
                )

        return signals

    def _calc_rsi(self, closes: list[float], period: int) -> list[float]:
        if len(closes) < period + 1:
            return []
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [max(0, d) for d in deltas]
        losses = [max(0, -d) for d in deltas]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        rsi = []
        for i in range(period, len(deltas)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
            if avg_loss == 0:
                rsi.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi.append(100 - 100 / (1 + rs))

        return rsi


StrategyRegistry.register(RSIStrategy.name, RSIStrategy)
