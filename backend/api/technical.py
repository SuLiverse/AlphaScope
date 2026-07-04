"""技术分析 API — 均线/MACD/RSI/KDJ/支撑压力"""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/technical", tags=["technical"])

MAX_TECH_LIMIT = 500
MAX_SUPPORT_LOOKBACK = 120


def _get_bars(symbol: str, limit: int = MAX_TECH_LIMIT) -> list[dict]:
    from backend.price_store import get_prices

    bars = get_prices(symbol, limit=limit)
    return sorted(bars, key=lambda b: b.get("date", ""))


# ============== Endpoints ==============


@router.get("/{symbol}")
async def get_all_indicators(symbol: str, limit: int = Query(default=250, ge=1, le=MAX_TECH_LIMIT)):
    """计算所有技术指标"""
    from backend.indicators import calc_all

    bars = _get_bars(symbol, limit)
    if not bars:
        return ApiResponse(success=False, error="无价格数据，请先获取行情")
    result = calc_all(bars)
    return ApiResponse(success=True, data=result)


@router.get("/{symbol}/ma")
async def get_ma(symbol: str, limit: int = Query(default=250, ge=1, le=MAX_TECH_LIMIT)):
    """均线"""
    from backend.indicators import calc_ma

    bars = _get_bars(symbol, limit)
    if not bars:
        return ApiResponse(success=False, error="无价格数据")
    result = calc_ma(bars)
    latest = result[-1] if result else {}
    return ApiResponse(
        success=True,
        data={"symbol": symbol, "ma": latest, "total": len(result)},
    )


@router.get("/{symbol}/macd")
async def get_macd(symbol: str, limit: int = Query(default=250, ge=1, le=MAX_TECH_LIMIT)):
    """MACD"""
    from backend.indicators import calc_macd

    bars = _get_bars(symbol, limit)
    if not bars:
        return ApiResponse(success=False, error="无价格数据")
    result = calc_macd(bars)
    latest = result[-1] if result else {}
    return ApiResponse(
        success=True,
        data={"symbol": symbol, "macd": latest, "total": len(result)},
    )


@router.get("/{symbol}/rsi")
async def get_rsi(symbol: str, limit: int = Query(default=250, ge=1, le=MAX_TECH_LIMIT)):
    """RSI"""
    from backend.indicators import calc_rsi

    bars = _get_bars(symbol, limit)
    if not bars:
        return ApiResponse(success=False, error="无价格数据")
    result = calc_rsi(bars)
    latest = result[-1] if result else {}
    return ApiResponse(
        success=True,
        data={"symbol": symbol, "rsi": latest.get("rsi", 0), "total": len(result)},
    )


@router.get("/{symbol}/kdj")
async def get_kdj(symbol: str, limit: int = Query(default=250, ge=1, le=MAX_TECH_LIMIT)):
    """KDJ"""
    from backend.indicators import calc_kdj

    bars = _get_bars(symbol, limit)
    if not bars:
        return ApiResponse(success=False, error="无价格数据")
    result = calc_kdj(bars)
    latest = result[-1] if result else {}
    return ApiResponse(
        success=True,
        data={"symbol": symbol, "kdj": latest, "total": len(result)},
    )


@router.get("/{symbol}/support-resistance")
async def get_support_resistance(symbol: str, lookback: int = Query(default=20, ge=1, le=MAX_SUPPORT_LOOKBACK)):
    """支撑压力位"""
    from backend.indicators import calc_support_resistance

    bars = _get_bars(symbol, lookback + 5)
    if not bars:
        return ApiResponse(success=False, error="无价格数据")
    sr = calc_support_resistance(bars, lookback=lookback)
    return ApiResponse(success=True, data={"symbol": symbol, **sr})
