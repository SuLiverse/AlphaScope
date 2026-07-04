"""Portfolio tracker for backtesting - tracks cash, positions, and trades."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Position:
    """A single position in the portfolio."""

    symbol: str
    shares: int
    avg_cost: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.shares * self.current_price

    @property
    def cost_basis(self) -> float:
        return self.shares * self.avg_cost

    @property
    def pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def pnl_percent(self) -> float:
        if self.cost_basis == 0:
            return 0.0
        return (self.pnl / self.cost_basis) * 100


@dataclass
class Trade:
    """A completed trade record."""

    symbol: str
    side: str  # "buy" or "sell"
    shares: int
    price: float
    commission: float
    timestamp: str
    pnl: float = 0.0


class Portfolio:
    """Portfolio tracker with cash, positions, and trade history."""

    def __init__(self, initial_capital: float = 100000.0, commission_rate: float = 0.001):
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_rate = commission_rate
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_history: list[float] = [initial_capital]
        self.date_history: list[str] = []

    def execute_buy(
        self,
        symbol: str,
        shares: int,
        price: float,
        timestamp: str = "",
        commission: float | None = None,
    ) -> bool:
        """Execute a buy order. Returns True if successful.

        ``commission`` lets the engine pass a pre-computed fee (e.g. with a
        minimum-charge rule from :class:`constraints.TradingCostModel`). When
        omitted, the legacy ``commission_rate`` fallback is used.
        """
        cost = shares * price
        if commission is None:
            commission = cost * self.commission_rate
        total_cost = cost + commission

        if total_cost > self.cash:
            return False

        self.cash -= total_cost

        if symbol in self.positions:
            pos = self.positions[symbol]
            # Weighted-average cost of the combined holding, fee excluded (the
            # commission is already deducted from cash, not capitalised).
            total_shares = pos.shares + shares
            pos.avg_cost = (pos.cost_basis + cost) / total_shares
            pos.shares = total_shares
            pos.current_price = price
        else:
            self.positions[symbol] = Position(symbol=symbol, shares=shares, avg_cost=price, current_price=price)

        self.trades.append(
            Trade(
                symbol=symbol,
                side="buy",
                shares=shares,
                price=price,
                commission=commission,
                timestamp=timestamp,
                pnl=0.0,
            )
        )
        return True

    def execute_sell(
        self,
        symbol: str,
        shares: int,
        price: float,
        timestamp: str = "",
        commission: float | None = None,
        stamp_duty: float = 0.0,
    ) -> bool:
        """Execute a sell order. Returns True if successful.

        ``commission`` and ``stamp_duty`` are the pre-computed fees. When
        ``commission`` is omitted the legacy ``commission_rate`` fallback applies;
        ``stamp_duty`` defaults to 0 (A-share stamp duty is paid by the seller).
        """
        if symbol not in self.positions:
            return False

        pos = self.positions[symbol]
        if shares > pos.shares:
            return False

        proceeds = shares * price
        if commission is None:
            commission = proceeds * self.commission_rate
        pnl = (price - pos.avg_cost) * shares - commission - stamp_duty

        self.cash += proceeds - commission - stamp_duty

        if shares == pos.shares:
            del self.positions[symbol]
        else:
            pos.shares -= shares
            pos.current_price = price

        self.trades.append(
            Trade(
                symbol=symbol,
                side="sell",
                shares=shares,
                price=price,
                commission=commission,
                timestamp=timestamp,
                pnl=pnl,
            )
        )
        return True

    def update_prices(self, prices: dict[str, float]) -> None:
        """Update current prices for all positions."""
        for symbol, price in prices.items():
            if symbol in self.positions:
                self.positions[symbol].current_price = price

    def record_equity(self, timestamp: str = "") -> float:
        """Record current equity to history and return it."""
        equity = self.get_equity()
        self.equity_history.append(equity)
        self.date_history.append(timestamp)
        return equity

    def get_equity(self) -> float:
        """Total portfolio equity = cash + sum of position market values."""
        return self.cash + sum(pos.market_value for pos in self.positions.values())

    def get_allocation(self) -> dict[str, float]:
        """Get allocation percentages by symbol."""
        equity = self.get_equity()
        if equity == 0:
            return {}
        alloc = {}
        for sym, pos in self.positions.items():
            alloc[sym] = pos.market_value / equity * 100
        alloc["_cash"] = self.cash / equity * 100
        return alloc

    def get_metrics(self) -> dict[str, Any]:
        """Get current portfolio metrics."""
        equity = self.get_equity()
        return {
            "equity": round(equity, 2),
            "cash": round(self.cash, 2),
            "positions_count": len(self.positions),
            "total_trades": len(self.trades),
            "total_return_pct": round((equity - self.initial_capital) / self.initial_capital * 100, 2),
        }
