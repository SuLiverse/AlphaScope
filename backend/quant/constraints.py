"""Realistic A-share trading constraints for the backtesting engine.

This module models the frictions that the raw :class:`Portfolio` does not:

* **Commission** (broker fee, charged on both buy and sell legs)
* **Stamp duty** (印花税, charged on the *sell* leg only, A-share rule)
* **Slippage** (成交价偏离, executed price deviates from the signal price)
* **T+1 settlement** (买入当日不得卖出, A-share rule)
* **Price-limit filter** (涨跌停板无法成交)

Everything here is pure and deterministic so it can be unit-tested without any
LLM / network / market data dependency. The intent is to make backtest results
honest: without these frictions a backtest systematically overstates returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class TradingCostModel:
    """Trading cost model: commission + stamp duty + slippage.

    Defaults follow typical A-share retail assumptions:

    * ``commission_rate`` 0.0003 (万三), double-sided, minimum 5 yuan per trade
    * ``stamp_duty_rate`` 0.0005 (万五), **sell side only**
    * ``slippage_rate`` 0.001 (10 bps) applied as adverse price movement

    All rates are expressed as fractions (0.001 == 0.1%).
    """

    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_duty_rate: float = 0.0005
    slippage_rate: float = 0.001

    def commission(self, turnover: float) -> float:
        """Broker commission for a single leg. Double-sided, min 5 yuan."""
        if turnover <= 0:
            return 0.0
        return max(turnover * self.commission_rate, self.commission_min)

    def stamp_duty(self, turnover: float) -> float:
        """Stamp duty, charged on the sell leg only (A-share rule)."""
        if turnover <= 0:
            return 0.0
        return turnover * self.stamp_duty_rate

    def buy_cost(self, shares: int, price: float) -> tuple[float, float, float]:
        """Return (fill_price, turnover, commission) for a buy order.

        Slippage moves the executed price *up* for the buyer (pays more).
        """
        fill_price = price * (1.0 + self.slippage_rate)
        turnover = shares * fill_price
        return fill_price, turnover, self.commission(turnover)

    def sell_proceeds(self, shares: int, price: float) -> tuple[float, float, float, float]:
        """Return (fill_price, turnover, commission, stamp_duty) for a sell order.

        Slippage moves the executed price *down* for the seller (receives less).
        """
        fill_price = price * (1.0 - self.slippage_rate)
        turnover = shares * fill_price
        return (
            fill_price,
            turnover,
            self.commission(turnover),
            self.stamp_duty(turnover),
        )


@dataclass
class T1Constraint:
    """A-share T+1 settlement: a position bought on day D cannot be sold on day D.

    ``acquired_dates`` maps symbol -> the bar index on which the *current* lot was
    bought. A sell is allowed only when the current bar index is strictly greater
    than the acquired index.
    """

    enabled: bool = True
    # symbol -> latest buy bar index (kept by the engine on each fill)
    _acquired: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self._acquired is None:
            self._acquired = {}

    def record_buy(self, symbol: str, bar_index: int) -> None:
        """Record that ``symbol`` was acquired at ``bar_index``."""
        # Keep the most recent acquisition; for T+1 the binding lot is the
        # latest purchase, which is the conservative interpretation.
        self._acquired[symbol] = bar_index

    def can_sell(self, symbol: str, bar_index: int) -> bool:
        """Whether ``symbol`` may be sold at ``bar_index`` (T+1 rule)."""
        if not self.enabled:
            return True
        acquired = self._acquired.get(symbol)
        if acquired is None:
            # Holding carried into the backtest (pre-existing position): allow.
            return True
        return bar_index > acquired


@dataclass
class PriceLimitFilter:
    """A-share 涨跌停 filter: a ±10% (ST ±5%) limit-locked bar cannot be traded.

    Detection is conservative and best-effort: if the close equals the limit-up
    or limit-down price implied by ``prev_close`` and the configured band, the
    bar is treated as limit-locked and orders are rejected. This avoids the
    classic backtest cheat of "buying at the limit-up close".
    """

    enabled: bool = True
    band: float = 0.10  # 10% for normal A-shares; set 0.05 for ST
    # tolerance for float equality when comparing to the limit price
    tol: float = 1e-4

    @staticmethod
    def _round2(x: float) -> float:
        return round(x + 1e-8, 2)

    def is_limit_up(self, bar: dict[str, Any], prev_close: float | None) -> bool:
        if not self.enabled or prev_close is None or prev_close <= 0:
            return False
        limit_price = self._round2(prev_close * (1.0 + self.band))
        return abs(bar.get("close", 0) - limit_price) <= self.tol

    def is_limit_down(self, bar: dict[str, Any], prev_close: float | None) -> bool:
        if not self.enabled or prev_close is None or prev_close <= 0:
            return False
        limit_price = self._round2(prev_close * (1.0 - self.band))
        return abs(bar.get("close", 0) - limit_price) <= self.tol

    def tradable(self, bar: dict[str, Any], prev_close: float | None, side: str) -> bool:
        """Return False when the bar is limit-locked against ``side``.

        * limit-up  -> cannot buy (demand exceeds supply, fills unlikely)
        * limit-down -> cannot sell
        """
        if self.is_limit_up(bar, prev_close) and side == "buy":
            return False
        if self.is_limit_down(bar, prev_close) and side == "sell":
            return False
        return True


# Sensible shared default. Engines construct their own copies so this is just a
# convenience for callers that want the canonical A-share cost assumptions.
DEFAULT_COST_MODEL = TradingCostModel()
