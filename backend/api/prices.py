"""行情数据 API — K 线查询、最新价格、Provider 拉取"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/prices", tags=["prices"])
logger = logging.getLogger(__name__)

PRICE_PROVIDER_TIMEOUT_SECONDS = 8.0
MAX_PRICE_FETCH_DAYS = 3650


def _minimum_period_bars(frequency: str) -> int:
    if frequency == "1y":
        return 2
    if frequency == "1mo":
        return 6
    if frequency == "1w":
        return 12
    return 1


async def _fetch_provider_bars(sym: str, days: int) -> list[dict]:
    from backend.price_store import get_market
    from backend.providers.registry import get_registry

    registry = get_registry()
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=max(days * 2, 30))).strftime("%Y%m%d")
    return await asyncio.wait_for(
        asyncio.to_thread(
            registry.get,
            data_type="prices",
            market=get_market(sym),
            symbol=sym,
            limit=days,
            start_date=start_date,
            end_date=end_date,
            period="daily",
            frequency="1d",
            adjust="",
        ),
        timeout=PRICE_PROVIDER_TIMEOUT_SECONDS,
    )


def _provider_timeout_response(sym: str) -> ApiResponse:
    return ApiResponse(
        success=False,
        data={
            "symbol": sym,
            "fetched": 0,
            "degraded": True,
            "source_status": "timeout",
        },
        error="行情源响应超时，请稍后重试",
        error_code="PRICE_PROVIDER_TIMEOUT",
    )


# ============== Endpoints ==============


@router.get("/normalize/{symbol}")
async def normalize_symbol(symbol: str):
    """查看股票代码标准化结果"""
    from backend.price_store import get_market, normalize_symbol as _norm

    normalized = _norm(symbol)
    market = get_market(symbol)
    return ApiResponse(
        success=True,
        data={"original": symbol, "normalized": normalized, "market": market},
    )


@router.get("/{symbol}/latest")
async def get_latest_price(symbol: str):
    """获取最新价格"""
    from backend.price_periods import fetch_intraday_prices
    from backend.price_quality import filter_incompatible_price_bars
    from backend.price_store import (
        get_latest_price as _latest,
        get_market,
        get_prices as _get,
    )

    if get_market(symbol) == "CN":
        intraday_bars = fetch_intraday_prices(symbol, limit=1)
        if intraday_bars:
            return ApiResponse(success=True, data=intraday_bars[-1])

    fetch_result = None
    raw_daily_bars = _get(
        symbol=symbol, frequency="1d", limit=20, include_incompatible=True
    )
    daily_bars = filter_incompatible_price_bars(raw_daily_bars)
    if not daily_bars:
        fetch_result = await fetch_prices(symbol, days=120)
        raw_daily_bars = _get(
            symbol=symbol, frequency="1d", limit=20, include_incompatible=True
        )
        daily_bars = filter_incompatible_price_bars(raw_daily_bars)
    bar = daily_bars[0] if daily_bars else _latest(symbol)
    if not bar:
        if fetch_result is not None and not fetch_result.success:
            return ApiResponse(
                success=False,
                data=fetch_result.data,
                error=fetch_result.error or "无价格数据",
                error_code=fetch_result.error_code,
            )
        return ApiResponse(success=False, error="无价格数据")
    return ApiResponse(success=True, data=bar)


@router.get("/{symbol}")
async def get_prices(
    symbol: str,
    frequency: str = "1d",
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(250, ge=1, le=2000),
):
    """查询 K 线数据"""
    from backend.price_periods import (
        aggregate_price_bars,
        default_daily_window_days,
        fetch_intraday_prices,
        normalize_frequency,
    )
    from backend.price_quality import filter_incompatible_price_bars
    from backend.price_store import get_prices as _get

    normalized_frequency = normalize_frequency(frequency)
    if normalized_frequency == "intraday":
        bars = fetch_intraday_prices(symbol, limit=limit)
        return ApiResponse(
            success=True,
            data={
                "symbol": symbol,
                "frequency": normalized_frequency,
                "bars": bars,
                "total": len(bars),
            },
        )

    aggregated_frequencies = {"1w", "1mo", "1y"}
    store_frequency = (
        "1d" if normalized_frequency in aggregated_frequencies else normalized_frequency
    )
    fetch_days = default_daily_window_days(
        max(1, min(limit, 500)), normalized_frequency
    )
    raw_bars = _get(
        symbol=symbol,
        frequency=store_frequency,
        start_date=start,
        end_date=end,
        limit=fetch_days if normalized_frequency in aggregated_frequencies else limit,
        include_incompatible=True,
    )
    bars = filter_incompatible_price_bars(raw_bars)
    degraded = False
    source_status = "ok"
    error = None
    error_code = None
    should_extend_period_history = False
    if (
        normalized_frequency in aggregated_frequencies
        and bars
        and not start
        and not end
    ):
        should_extend_period_history = (
            len(aggregate_price_bars(bars, normalized_frequency)) < limit
        )

    if (not bars or should_extend_period_history) and not start and not end:
        fetch_result = await fetch_prices(
            symbol, days=max(1, min(fetch_days, MAX_PRICE_FETCH_DAYS))
        )
        if not fetch_result.success:
            degraded = True
            error = fetch_result.error
            error_code = fetch_result.error_code
            if error_code == "PRICE_PROVIDER_TIMEOUT":
                source_status = "timeout"
            else:
                source_status = "unavailable"
        raw_bars = _get(
            symbol=symbol,
            frequency=store_frequency,
            start_date=start,
            end_date=end,
            limit=fetch_days
            if normalized_frequency in aggregated_frequencies
            else limit,
            include_incompatible=True,
        )
        bars = filter_incompatible_price_bars(raw_bars)
    if normalized_frequency in aggregated_frequencies:
        bars = aggregate_price_bars(bars, normalized_frequency)[-limit:]
        if bars and len(bars) < _minimum_period_bars(normalized_frequency):
            degraded = True
            source_status = "short_history"
    return ApiResponse(
        success=True,
        data={
            "symbol": symbol,
            "frequency": normalized_frequency,
            "bars": bars,
            "total": len(bars),
            "degraded": degraded,
            "source_status": source_status,
        },
        error=error,
        error_code=error_code,
    )


@router.post("/{symbol}/fetch")
async def fetch_prices(symbol: str, days: int = 30):
    """从 Provider 拉取并存储 K 线数据"""
    if days < 1 or days > MAX_PRICE_FETCH_DAYS:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail=f"days 参数必须在 1-{MAX_PRICE_FETCH_DAYS} 之间",
        )
    from backend.price_store import normalize_symbol as _norm, save_price_bars

    sym = _norm(symbol)
    if not sym:
        return ApiResponse(success=False, error="无效的股票代码")

    try:
        bars = await _fetch_provider_bars(sym, days)
        if not bars:
            return ApiResponse(success=False, error="未从 Provider 获取到数据")

        # 标准化并保存
        count = save_price_bars(bars)
        return ApiResponse(
            success=True,
            data={"symbol": sym, "fetched": count},
            message=f"成功获取 {count} 条 K 线数据",
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Price provider timed out for %s after %.1fs",
            sym,
            PRICE_PROVIDER_TIMEOUT_SECONDS,
        )
        return _provider_timeout_response(sym)
    except Exception as e:
        return ApiResponse(success=False, error=f"获取数据失败: {e}")
