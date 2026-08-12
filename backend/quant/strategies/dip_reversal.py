"""Dip-reversal (mean-reversion) strategy.

Buy when price drops sharply in a short window (capitulation) and then
stabilises; sell after a rebound. A counter-trend template balancing the
momentum strategy.
"""

from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class DipReversalStrategy(BaseStrategy):
    """超跌反弹策略: 短期跌幅超过阈值后企稳买入，反弹止盈卖出。"""

    name = "dip_reversal"
    description = "超跌反弹策略: 短期跌幅超阈值企稳后买入，反弹至目标卖出"
    default_params = {
        "lookback": 5,
        "dip_threshold": -0.05,  # -5% over the lookback window
        "rebound_target": 0.05,  # +5% off the dip entry
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        n = self.params["lookback"]

        closes = self._closes(bars)
        dip_thr = self.params["dip_threshold"]
        target = self.params["rebound_target"]
        signals: list[Signal] = []
        dip_ref: float | None = None  # reference close at last dip entry
        for i in range(len(bars)):
            if i < n:
                signals.append(Signal("hold", bars[i].get("symbol", ""), reason="数据不足"))
                continue
            change = (closes[i] - closes[i - n]) / closes[i - n] if closes[i - n] else 0.0
            symbol = bars[i].get("symbol", "")
            if change <= dip_thr and dip_ref is None:
                shares = self._calc_shares(closes[i], portfolio_state)
                signals.append(
                    Signal(
                        "buy",
                        symbol,
                        shares=shares,
                        reason=f"超跌企稳 ({n}日{change * 100:.2f}%≤{dip_thr * 100:.0f}%)",
                    )
                )
                dip_ref = closes[i]
            elif dip_ref is not None and closes[i] >= dip_ref * (1 + target):
                gain = (closes[i] - dip_ref) / dip_ref
                signals.append(Signal("sell", symbol, reason=f"反弹止盈 (+{gain * 100:.2f}%)"))
                dip_ref = None
            elif dip_ref is not None and closes[i] < dip_ref:
                # 更新参考低点，跟踪更深的底部
                dip_ref = closes[i]
                signals.append(Signal("hold", symbol, reason="持有等待反弹"))
            else:
                signals.append(Signal("hold", symbol, reason="观望"))
        assert len(signals) == len(bars)
        return signals


StrategyRegistry.register(DipReversalStrategy.name, DipReversalStrategy)
