"""组合计算 API — 持久化研究持仓 + 组合优化器 + QuantStats 绩效报告。

接出三个沉睡模块:
- backend/research_portfolio_store.py: 持久化研究持仓(替代前端 localStorage)
- backend/portfolio_optimizer.py: skfolio/riskfolio/pypfopt 组合优化(研究草案权重)
- backend/performance_report.py: quantstats 卖方级绩效指标

端点:
- GET  /api/portfolio/positions         列出持久化持仓
- POST /api/portfolio/positions         新增/更新持仓(upsert)
- DELETE /api/portfolio/positions/{sym} 删除持仓
- POST /api/portfolio/optimize          组合优化(拉行情→收益→优化器→权重草案)
- POST /api/portfolio/performance       QuantStats 绩效报告(输入净值曲线或收益序列)

纯新增,不改动 portfolio_new.py 的现金组合模型。
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.schemas.api import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio-calc"])


# ============================================================
# 持久化持仓
# ============================================================


class PositionUpsertRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    name: str = Field(default="", max_length=80)
    sector: str = Field(default="", max_length=40)
    shares: float = Field(default=0, ge=0)
    cost: float = Field(default=0, ge=0)


@router.get("/positions")
def list_positions():
    from backend import research_portfolio_store

    return ApiResponse(success=True, data={"items": research_portfolio_store.list_positions()})


@router.post("/positions")
def upsert_position(req: PositionUpsertRequest):
    from backend import research_portfolio_store

    research_portfolio_store.upsert_position(
        symbol=req.symbol,
        name=req.name,
        sector=req.sector,
        shares=req.shares,
        cost=req.cost,
    )
    return ApiResponse(
        success=True, data={"items": research_portfolio_store.list_positions()}
    )


@router.delete("/positions/{symbol}")
def delete_position(symbol: str):
    from backend import research_portfolio_store

    ok = research_portfolio_store.remove_position(symbol)
    return ApiResponse(success=ok, data={"items": research_portfolio_store.list_positions()})


# ============================================================
# 组合优化
# ============================================================


class OptimizeRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list, description="持仓代码(6位)")
    method: str = Field(
        default="max_sharpe", description="max_sharpe / min_variance / equal_weight"
    )
    days: int = Field(default=120, ge=30, le=500, description="回看交易日数")
    rf: float = Field(default=0.02, ge=0, le=0.2, description="无风险利率(年化)")


def _build_returns_frame(symbols: list[str], days: int):
    """拉取多标的近 days 个交易日收盘价, 对齐成日收益 DataFrame(列=资产)。

    失败安全:任一标的拉取失败跳过;对齐后样本不足返回 None。
    """
    import pandas as pd

    from backend.price_fetcher import get_price_range

    # 用一个足够近的「起始日」(今天往前 days+缓冲)取序列
    from datetime import datetime, timedelta

    start = (datetime.now() - timedelta(days=days * 2 + 30)).strftime("%Y-%m-%d")
    series_map: dict[str, "pd.Series"] = {}
    for sym in symbols:
        sym = (sym or "").strip().split(".")[0]
        if not sym:
            continue
        try:
            seq = get_price_range(sym, start, days)
        except Exception as e:  # noqa: BLE001
            logger.debug("拉取 %s 行情失败: %s", sym, e)
            continue
        if len(seq) < 30:
            continue
        dates = [d for d, _ in seq]
        closes = [c for _, c in seq]
        series_map[sym] = pd.Series(closes, index=dates, name=sym)

    if len(series_map) < 2:
        return None, []

    df = pd.DataFrame(series_map)
    df = df.dropna()  # 对齐到公共交易日
    if df.shape[0] < 30:
        return None, list(series_map.keys())
    returns = df.pct_change().dropna()
    return returns, list(returns.columns)


@router.post("/optimize")
def optimize(req: OptimizeRequest):
    from backend.portfolio_optimizer import optimize_portfolio

    if not req.symbols or len(req.symbols) < 2:
        raise HTTPException(status_code=400, detail="至少需要 2 个标的")
    returns, names = _build_returns_frame(req.symbols, req.days)
    if returns is None:
        raise HTTPException(
            status_code=400,
            detail="行情数据不足:需 ≥2 个标的且每个 ≥30 个公共交易日",
        )
    result = optimize_portfolio(
        returns=returns,
        method=req.method,
        asset_names=names,
        rf=req.rf,
    )
    return ApiResponse(success=True, data=result)


@router.get("/optimizers")
def available_optimizers():
    from backend.portfolio_optimizer import available_optimizers as _avail

    return ApiResponse(success=True, data={"optimizers": _avail()})


# ============================================================
# QuantStats 绩效报告
# ============================================================


class PerformanceRequest(BaseModel):
    equity_curve: list[float] | None = Field(
        default=None, description="净值曲线(与 returns 二选一)"
    )
    returns: list[float] | None = Field(
        default=None, description="收益序列(与 equity_curve 二选一)"
    )


@router.post("/performance")
def performance_report(req: PerformanceRequest):
    from backend.performance_report import build_report

    if not req.equity_curve and not req.returns:
        raise HTTPException(status_code=400, detail="需提供 equity_curve 或 returns")
    result: dict[str, Any] = build_report(
        equity_curve=req.equity_curve, returns=req.returns
    )
    return ApiResponse(success=True, data=result)


@router.get("/performance/available")
def performance_available():
    from backend.performance_report import is_available

    return ApiResponse(success=True, data={"available": is_available()})
