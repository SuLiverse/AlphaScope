"""Optional Chanlun structure-breakout strategy.

A single executable rule, sent through the existing backtest engine:

* Buy on the bar where a pullback stroke finishes still above a zhongshu that
  has already broken upward.
* Sell when the close falls back into that zhongshu band.
* Hold otherwise.

Each ``signals[i]`` is computed from ``bars[:i+1]`` only (plan 003). This is a
research annotation-to-rule, not a default UI strategy.
"""

from __future__ import annotations

from typing import Any

from backend.quant.chanlun import analyze_chanlun

from .base import BaseStrategy, Signal, StrategyRegistry


class ChanlunStructureStrategy(BaseStrategy):
    """中枢向上离开后回抽不破上沿买入, 收盘跌回中枢卖出。"""

    name = "chanlun_structure"
    description = "缠论结构突破: 中枢上破回抽不破上沿买入, 收盘跌回中枢卖出"
    default_params = {
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        signals: list[Signal] = []
        in_pos = False
        band: tuple[float, float] | None = None
        for i in range(len(bars)):
            symbol = bars[i].get("symbol", "")
            close = float(bars[i].get("close") or 0)
            report = analyze_chanlun(bars[: i + 1], symbol)
            action = "hold"
            reason = "无结构规则触发"
            if report.status == "ok":
                # Stroke.end_date is the fractal date; the stroke only becomes
                # visible on the confirming bar after it. Treat "this bar" as
                # any of the last 3 dates so we buy on confirmation, not on a
                # look-ahead close of the fractal bar itself.
                recent = {str(b.get("date") or "") for b in bars[max(0, i - 2) : i + 1]}
                for z in report.zhongshus:
                    if z.is_broken and z.break_direction == "up":
                        if report.strokes:
                            last = report.strokes[-1]
                            if (
                                not in_pos
                                and last.direction == "down"
                                and last.end_date in recent
                                and last.end_price > z.zg
                            ):
                                action = "buy"
                                reason = f"中枢向上突破后回抽结束仍在上沿 {z.zg:.2f} 之上"
                                band = (z.zd, z.zg)
                if in_pos and band is not None:
                    lo, hi = band
                    if lo <= close <= hi:
                        action = "sell"
                        reason = f"收盘跌回中枢区间 [{lo:.2f}-{hi:.2f}]"

            if action == "buy":
                in_pos = True
                shares = self._calc_shares(close, portfolio_state)
                signals.append(Signal("buy", symbol, shares=shares, reason=reason))
            elif action == "sell":
                in_pos = False
                band = None
                signals.append(Signal("sell", symbol, reason=reason))
            else:
                signals.append(Signal("hold", symbol, reason=reason))
        assert len(signals) == len(bars)
        return signals


StrategyRegistry.register(ChanlunStructureStrategy.name, ChanlunStructureStrategy)
