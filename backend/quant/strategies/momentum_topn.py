"""Momentum strategy: trend-following via rate-of-change (ROC).

Buy when short-term momentum turns positive and accelerating; sell when it
rolls over negative. A simple, robust trend template (distinct from MA cross).
"""

from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class MomentumStrategy(BaseStrategy):
    """动量策略: 短期 ROC 上穿 0 买入，下穿 0 卖出。"""

    name = "momentum"
    description = "动量策略: 短期变动率(ROC)转正买入，转负卖出"
    default_params = {
        "roc_period": 12,
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        n = self.params["roc_period"]
        if len(bars) <= n:
            return []

        closes = self._closes(bars)
        signals: list[Signal] = []
        for i in range(n, len(bars)):
            roc = (closes[i] - closes[i - n]) / closes[i - n] if closes[i - n] else 0.0
            prev_roc = (closes[i - 1] - closes[i - 1 - n]) / closes[i - 1 - n] if closes[i - 1 - n] else 0.0
            symbol = bars[i].get("symbol", "")
            if prev_roc <= 0 < roc:
                shares = self._calc_shares(closes[i], portfolio_state)
                signals.append(
                    Signal(
                        "buy",
                        symbol,
                        shares=shares,
                        reason=f"ROC 由负转正 ({roc * 100:.2f}%)",
                    )
                )
            elif prev_roc >= 0 > roc:
                signals.append(Signal("sell", symbol, reason=f"ROC 由正转负 ({roc * 100:.2f}%)"))
            else:
                signals.append(Signal("hold", symbol, reason=f"ROC={roc * 100:.2f}%"))
        return signals


StrategyRegistry.register(MomentumStrategy.name, MomentumStrategy)
