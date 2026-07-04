"""Dollar-Cost Averaging (DCA) simulator for fund investment analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


@dataclass
class DCAResult:
    """Result of a DCA simulation."""

    total_invested: float
    total_shares: float
    average_cost: float
    final_value: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    volatility_pct: float
    sharpe_ratio: float
    monthly_records: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_invested": round(self.total_invested, 2),
            "total_shares": round(self.total_shares, 4),
            "average_cost": round(self.average_cost, 4),
            "final_value": round(self.final_value, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "annualized_return_pct": round(self.annualized_return_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "volatility_pct": round(self.volatility_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "monthly_records": self.monthly_records,
        }


class DCASimulator:
    """Simulates dollar-cost averaging investment strategy."""

    def simulate(
        self,
        prices: list[float],
        dates: list[str],
        amount_per_period: float,
        frequency: str = "monthly",
        risk_free_rate: float = 0.03,
    ) -> DCAResult:
        """Run a DCA simulation.

        Args:
            prices: List of fund NAV prices (chronological order)
            dates: Corresponding dates
            amount_per_period: Investment amount per period
            frequency: "monthly", "weekly", or "daily"
            risk_free_rate: Annual risk-free rate for Sharpe calculation

        Returns:
            DCAResult with simulation metrics
        """
        if not prices or len(prices) < 2:
            return DCAResult(
                total_invested=0,
                total_shares=0,
                average_cost=0,
                final_value=0,
                total_return_pct=0,
                annualized_return_pct=0,
                max_drawdown_pct=0,
                volatility_pct=0,
                sharpe_ratio=0,
                monthly_records=[],
            )

        step = self._get_step(frequency)
        total_shares = 0.0
        total_invested = 0.0
        records = []
        portfolio_values = []

        for i in range(0, len(prices), step):
            price = prices[i]
            date = dates[i] if i < len(dates) else f"period_{i}"
            shares_bought = amount_per_period / price
            total_shares += shares_bought
            total_invested += amount_per_period

            current_value = total_shares * price
            avg_cost = total_invested / total_shares if total_shares > 0 else 0

            records.append(
                {
                    "date": date,
                    "price": round(price, 4),
                    "invested": round(amount_per_period, 2),
                    "shares_bought": round(shares_bought, 4),
                    "total_shares": round(total_shares, 4),
                    "total_invested": round(total_invested, 2),
                    "current_value": round(current_value, 2),
                    "return_pct": round((current_value - total_invested) / total_invested * 100, 2)
                    if total_invested > 0
                    else 0,
                }
            )
            portfolio_values.append(current_value)

        final_price = prices[-1]
        final_value = total_shares * final_price
        avg_cost = total_invested / total_shares if total_shares > 0 else 0
        total_return = (final_value - total_invested) / total_invested if total_invested > 0 else 0

        # Calculate volatility from period returns
        period_returns = []
        for i in range(1, len(portfolio_values)):
            if portfolio_values[i - 1] > 0:
                period_returns.append((portfolio_values[i] - portfolio_values[i - 1]) / portfolio_values[i - 1])

        volatility = self._calc_volatility(period_returns)
        max_dd = self._calc_max_drawdown(portfolio_values)

        # Annualized return
        periods_per_year = self._periods_per_year(frequency)
        total_periods = len(records)
        years = total_periods / periods_per_year if periods_per_year > 0 else 1
        ann_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

        # Sharpe ratio
        mean_ret = sum(period_returns) / len(period_returns) if period_returns else 0
        std_ret = volatility
        daily_rf = risk_free_rate / periods_per_year if periods_per_year > 0 else 0
        sharpe = (mean_ret - daily_rf) / std_ret * math.sqrt(periods_per_year) if std_ret > 0 else 0

        return DCAResult(
            total_invested=total_invested,
            total_shares=total_shares,
            average_cost=avg_cost,
            final_value=final_value,
            total_return_pct=total_return * 100,
            annualized_return_pct=ann_return * 100,
            max_drawdown_pct=max_dd * 100,
            volatility_pct=volatility * 100 * math.sqrt(periods_per_year),
            sharpe_ratio=sharpe,
            monthly_records=records,
        )

    @staticmethod
    def _get_step(frequency: str) -> int:
        if frequency == "weekly":
            return 5
        if frequency == "daily":
            return 1
        return 20  # monthly (approx trading days)

    @staticmethod
    def _periods_per_year(frequency: str) -> int:
        if frequency == "weekly":
            return 52
        if frequency == "daily":
            return 252
        return 12  # monthly

    @staticmethod
    def _calc_volatility(returns: list[float]) -> float:
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
        return math.sqrt(variance)

    @staticmethod
    def _calc_max_drawdown(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        peak = values[0]
        max_dd = 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (v - peak) / peak if peak > 0 else 0
            if dd < max_dd:
                max_dd = dd
        return max_dd


def compare_dca_vs_lumpsum(
    prices: list[float],
    total_amount: float,
    frequency: str = "monthly",
) -> dict[str, Any]:
    """Compare DCA vs lump-sum investment.

    Returns dict with dca and lumpsum results for comparison.
    """
    if not prices:
        return {"dca": {}, "lumpsum": {}, "winner": "none"}

    step = DCASimulator._get_step(frequency)
    periods = len(range(0, len(prices), step))
    amount_per_period = total_amount / periods if periods > 0 else total_amount

    simulator = DCASimulator()
    dca_result = simulator.simulate(prices, [f"d{i}" for i in range(len(prices))], amount_per_period, frequency)

    # Lump sum: buy all at first price
    first_price = prices[0]
    final_price = prices[-1]
    lump_shares = total_amount / first_price
    lump_value = lump_shares * final_price
    lump_return = (lump_value - total_amount) / total_amount * 100

    return {
        "dca": dca_result.to_dict(),
        "lumpsum": {
            "total_invested": round(total_amount, 2),
            "shares": round(lump_shares, 4),
            "buy_price": round(first_price, 4),
            "final_value": round(lump_value, 2),
            "return_pct": round(lump_return, 2),
        },
        "winner": "dca" if dca_result.total_return_pct > lump_return else "lumpsum",
    }
