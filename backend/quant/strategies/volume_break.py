"""Volume-price breakout strategy.

Buy when volume surges (≥ N× average) together with a price up-move; this is a
classic "量价齐升" breakout template. Sell when volume contracts on weakness.
"""

from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class VolumeBreakStrategy(BaseStrategy):
    """量价突破策略: 放量上涨买入，缩量下跌卖出。"""

    name = "volume_break"
    description = "量价突破策略: 放量上涨(≥1.5倍均量)买入，缩量下跌卖出"
    default_params = {
        "vol_period": 20,
        "vol_mult": 1.5,
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        n = self.params["vol_period"]

        closes = self._closes(bars)
        volumes = self._volumes(bars)
        mult = self.params["vol_mult"]
        signals: list[Signal] = []
        for i in range(len(bars)):
            if i < n:
                signals.append(Signal("hold", bars[i].get("symbol", ""), reason="数据不足"))
                continue
            avg_vol = sum(volumes[i - n : i]) / n
            vol = volumes[i]
            symbol = bars[i].get("symbol", "")
            price_up = closes[i] > closes[i - 1] if closes[i - 1] else False
            price_down = closes[i] < closes[i - 1] if closes[i - 1] else False
            if avg_vol > 0 and vol >= avg_vol * mult and price_up:
                shares = self._calc_shares(closes[i], portfolio_state)
                signals.append(
                    Signal(
                        "buy",
                        symbol,
                        shares=shares,
                        reason=f"放量上涨 (量比 {vol / avg_vol:.2f}×)",
                    )
                )
            elif avg_vol > 0 and vol < avg_vol * 0.7 and price_down:
                signals.append(Signal("sell", symbol, reason=f"缩量下跌 (量比 {vol / avg_vol:.2f}×)"))
            else:
                signals.append(Signal("hold", symbol, reason="量价未触发"))
        assert len(signals) == len(bars)
        return signals


StrategyRegistry.register(VolumeBreakStrategy.name, VolumeBreakStrategy)
