"""Portfolio management API (v1.1.3)

Provides portfolio CRUD, position tracking, and trade recording.
Does not overlap with existing /api/backtest/* routes.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])

# In-memory store (lightweight, per-process)
_portfolios: dict[str, dict[str, Any]] = {}


class PortfolioCreate(BaseModel):
    name: str
    initial_capital: float = 100000.0


class TradeCreate(BaseModel):
    symbol: str
    side: str = Field(pattern="^(buy|sell)$")
    shares: int
    price: float
    timestamp: str = ""


def _get_portfolio(portfolio_id: str) -> dict[str, Any]:
    if portfolio_id not in _portfolios:
        raise HTTPException(status_code=404, detail=f"组合不存在: {portfolio_id}")
    return _portfolios[portfolio_id]


@router.post("")
def create_portfolio(req: PortfolioCreate) -> dict[str, Any]:
    """Create a new portfolio."""
    pid = str(uuid.uuid4())[:8]
    portfolio = {
        "id": pid,
        "name": req.name,
        "initial_capital": req.initial_capital,
        "cash": req.initial_capital,
        "positions": {},
        "trades": [],
        "equity_history": [req.initial_capital],
        "created_at": datetime.now().isoformat(),
    }
    _portfolios[pid] = portfolio
    return {"success": True, "data": portfolio}


@router.get("")
def list_portfolios() -> dict[str, Any]:
    """List all portfolios."""
    summaries = []
    for pid, p in _portfolios.items():
        equity = p["cash"] + sum(pos["shares"] * pos["current_price"] for pos in p["positions"].values())
        summaries.append(
            {
                "id": pid,
                "name": p["name"],
                "equity": round(equity, 2),
                "cash": round(p["cash"], 2),
                "positions_count": len(p["positions"]),
                "total_trades": len(p["trades"]),
            }
        )
    return {"success": True, "data": summaries}


@router.get("/{portfolio_id}")
def get_portfolio(portfolio_id: str) -> dict[str, Any]:
    """Get portfolio details."""
    p = _get_portfolio(portfolio_id)
    equity = p["cash"] + sum(pos["shares"] * pos["current_price"] for pos in p["positions"].values())
    return {
        "success": True,
        "data": {
            **p,
            "equity": round(equity, 2),
            "total_return_pct": round((equity - p["initial_capital"]) / p["initial_capital"] * 100, 2),
        },
    }


@router.post("/{portfolio_id}/trade")
def record_trade(portfolio_id: str, req: TradeCreate) -> dict[str, Any]:
    """Record a buy or sell trade."""
    p = _get_portfolio(portfolio_id)
    commission_rate = 0.001

    if req.side == "buy":
        cost = req.shares * req.price
        commission = cost * commission_rate
        total_cost = cost + commission
        if total_cost > p["cash"]:
            raise HTTPException(status_code=400, detail="现金不足")

        p["cash"] -= total_cost
        positions = p["positions"]
        if req.symbol in positions:
            pos = positions[req.symbol]
            total_shares = pos["shares"] + req.shares
            pos["avg_cost"] = (pos["shares"] * pos["avg_cost"] + cost) / total_shares
            pos["shares"] = total_shares
            pos["current_price"] = req.price
        else:
            positions[req.symbol] = {
                "shares": req.shares,
                "avg_cost": req.price,
                "current_price": req.price,
            }

        p["trades"].append(
            {
                "symbol": req.symbol,
                "side": "buy",
                "shares": req.shares,
                "price": req.price,
                "commission": round(commission, 2),
                "pnl": 0,
                "timestamp": req.timestamp or datetime.now().isoformat(),
            }
        )

    elif req.side == "sell":
        positions = p["positions"]
        if req.symbol not in positions:
            raise HTTPException(status_code=400, detail=f"无持仓: {req.symbol}")
        pos = positions[req.symbol]
        if req.shares > pos["shares"]:
            raise HTTPException(status_code=400, detail="卖出数量超过持仓")

        proceeds = req.shares * req.price
        commission = proceeds * commission_rate
        pnl = (req.price - pos["avg_cost"]) * req.shares - commission
        p["cash"] += proceeds - commission

        if req.shares == pos["shares"]:
            del positions[req.symbol]
        else:
            pos["shares"] -= req.shares
            pos["current_price"] = req.price

        p["trades"].append(
            {
                "symbol": req.symbol,
                "side": "sell",
                "shares": req.shares,
                "price": req.price,
                "commission": round(commission, 2),
                "pnl": round(pnl, 2),
                "timestamp": req.timestamp or datetime.now().isoformat(),
            }
        )

    # Record equity
    equity = p["cash"] + sum(pos["shares"] * pos["current_price"] for pos in p["positions"].values())
    p["equity_history"].append(equity)

    return {
        "success": True,
        "data": {"equity": round(equity, 2), "cash": round(p["cash"], 2)},
    }


@router.get("/{portfolio_id}/allocation")
def get_allocation(portfolio_id: str) -> dict[str, Any]:
    """Get portfolio allocation percentages."""
    p = _get_portfolio(portfolio_id)
    equity = p["cash"] + sum(pos["shares"] * pos["current_price"] for pos in p["positions"].values())
    if equity == 0:
        return {"success": True, "data": {}}

    alloc = {}
    for sym, pos in p["positions"].items():
        alloc[sym] = round(pos["shares"] * pos["current_price"] / equity * 100, 2)
    alloc["_cash"] = round(p["cash"] / equity * 100, 2)
    return {"success": True, "data": alloc}


@router.get("/{portfolio_id}/trades")
def get_trades(portfolio_id: str) -> dict[str, Any]:
    """Get trade history."""
    p = _get_portfolio(portfolio_id)
    return {"success": True, "data": p["trades"]}
