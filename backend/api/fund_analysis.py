"""Fund analysis API (v1.1.3)

Provides fund search and DCA simulation endpoints.
"""

from __future__ import annotations

import math
import random
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/funds", tags=["funds"])


class DCASimRequest(BaseModel):
    symbol: str
    amount_per_period: float = 1000.0
    frequency: str = Field(default="monthly", pattern="^(daily|weekly|monthly)$")
    periods: int = Field(default=36, ge=1, le=120)
    initial_price: float = 1.0
    annual_growth_pct: float = 8.0
    volatility_pct: float = 15.0


# Mock fund database
_MOCK_FUNDS = [
    {
        "symbol": "110011",
        "name": "易方达中小盘混合",
        "type": "混合型",
        "risk": "R3",
        "manager": "张坤",
        "size_yi": 67.5,
    },
    {
        "symbol": "161725",
        "name": "招商中证白酒指数",
        "type": "指数型",
        "risk": "R4",
        "manager": "侯昊",
        "size_yi": 120.3,
    },
    {
        "symbol": "005827",
        "name": "易方达蓝筹精选混合",
        "type": "混合型",
        "risk": "R3",
        "manager": "张坤",
        "size_yi": 89.2,
    },
    {
        "symbol": "003834",
        "name": "华夏能源革新股票",
        "type": "股票型",
        "risk": "R4",
        "manager": "郑泽鸿",
        "size_yi": 45.8,
    },
    {
        "symbol": "001938",
        "name": "中欧时代先锋股票",
        "type": "股票型",
        "risk": "R4",
        "manager": "周应波",
        "size_yi": 32.1,
    },
    {
        "symbol": "001549",
        "name": "天弘永利债券",
        "type": "债券型",
        "risk": "R2",
        "manager": "姚文涛",
        "size_yi": 28.6,
    },
    {
        "symbol": "320007",
        "name": "诺安成长混合",
        "type": "混合型",
        "risk": "R3",
        "manager": "蔡嵩松",
        "size_yi": 55.0,
    },
    {
        "symbol": "260108",
        "name": "景顺长城新兴成长混合",
        "type": "混合型",
        "risk": "R3",
        "manager": "刘彦春",
        "size_yi": 72.4,
    },
]


@router.get("/search")
def search_funds(
    q: str = "", risk: str = "", fund_type: str = "", limit: int = Query(20, ge=1, le=200)
) -> dict[str, Any]:
    """Search funds by name, symbol, risk level, or type."""
    results = _MOCK_FUNDS
    if q:
        q_lower = q.lower()
        results = [
            f for f in results if q_lower in f["name"].lower() or q_lower in f["symbol"]
        ]
    if risk:
        results = [f for f in results if f["risk"] == risk]
    if fund_type:
        results = [f for f in results if f["type"] == fund_type]
    return {"success": True, "data": results[:limit]}


@router.get("/detail/{symbol}")
def get_fund_detail(symbol: str) -> dict[str, Any]:
    """Get fund details."""
    fund = next((f for f in _MOCK_FUNDS if f["symbol"] == symbol), None)
    if not fund:
        return {"success": False, "error": f"基金不存在: {symbol}"}
    return {"success": True, "data": fund}


@router.post("/dca/simulate")
def simulate_dca(req: DCASimRequest) -> dict[str, Any]:
    """Simulate a DCA investment plan with synthetic price data."""
    # Generate synthetic price data
    random.seed(hash(req.symbol) % 2**32)
    prices = _generate_synthetic_prices(
        req.initial_price,
        req.periods,
        req.annual_growth_pct / 100,
        req.volatility_pct / 100,
    )
    dates = [f"2024-{(i % 12) + 1:02d}-01" for i in range(req.periods)]

    # Run DCA simulation
    from backend.fund_analysis.dca_simulator import DCASimulator

    simulator = DCASimulator()
    result = simulator.simulate(
        prices=prices,
        dates=dates,
        amount_per_period=req.amount_per_period,
        frequency=req.frequency,
    )

    # Lump sum comparison
    total_invested = req.amount_per_period * (
        len(prices) // simulator._get_step(req.frequency)
    )
    lump_shares = total_invested / prices[0] if prices[0] > 0 else 0
    lump_value = lump_shares * prices[-1]
    lump_return = (
        (lump_value - total_invested) / total_invested * 100
        if total_invested > 0
        else 0
    )

    return {
        "success": True,
        "data": {
            "dca": result.to_dict(),
            "lumpsum": {
                "total_invested": round(total_invested, 2),
                "shares": round(lump_shares, 4),
                "buy_price": round(prices[0], 4),
                "final_value": round(lump_value, 2),
                "return_pct": round(lump_return, 2),
            },
            "winner": "dca" if result.total_return_pct > lump_return else "lumpsum",
            "prices": [round(p, 4) for p in prices],
        },
    }


def _generate_synthetic_prices(
    initial: float, periods: int, annual_growth: float, volatility: float
) -> list[float]:
    """Generate synthetic NAV prices using geometric Brownian motion."""
    dt = 1 / 12  # monthly
    prices = [initial]
    for _ in range(periods - 1):
        drift = (annual_growth - 0.5 * volatility**2) * dt
        shock = volatility * math.sqrt(dt) * random.gauss(0, 1)
        prices.append(prices[-1] * math.exp(drift + shock))
    return prices
