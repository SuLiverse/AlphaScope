"""Shared market snapshot construction for synchronous and async analysis."""

from __future__ import annotations

import logging
import math
from datetime import date
from typing import Any, Iterable

logger = logging.getLogger(__name__)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _as_of_string(as_of: date | str | None) -> str:
    if isinstance(as_of, date):
        return as_of.isoformat()
    return str(as_of or "")


def build_analysis_stock_data(
    symbol: str,
    stock_name: str,
    bars: Iterable[dict[str, Any]],
    *,
    as_of: date | str | None = None,
    research_question: str = "",
) -> dict[str, Any]:
    """Build the common report and Quant Referee snapshot from price bars."""
    ordered_bars = sorted((dict(bar) for bar in bars), key=lambda bar: str(bar.get("date") or ""))
    period_bars = ordered_bars[-30:]
    latest = period_bars[-1] if period_bars else {}
    previous = period_bars[-2] if len(period_bars) > 1 else {}

    latest_close = _as_float(latest.get("close"))
    previous_close = _as_float(previous.get("close"))
    first_close = _as_float(period_bars[0].get("close")) if period_bars else 0.0

    day_change = _as_float(latest.get("change_pct"))
    if not day_change and latest_close and previous_close:
        day_change = (latest_close - previous_close) / previous_close * 100
    period_change = (latest_close - first_close) / first_close * 100 if latest_close and first_close else 0.0

    technical: dict[str, Any] = {}
    try:
        from backend.indicators import calc_all

        numeric_bars = [
            {
                **bar,
                **{field: _as_float(bar.get(field)) for field in ("open", "close", "high", "low", "volume")},
            }
            for bar in ordered_bars
        ]
        technical = (calc_all(numeric_bars).get("summary") or {}) if numeric_bars else {}
    except Exception as exc:  # noqa: BLE001 - indicator degradation must not block report generation
        logger.debug("analysis technical snapshot unavailable: %s", exc)

    def indicator(name: str, minimum_bars: int) -> float | str:
        if len(ordered_bars) < minimum_bars:
            return "N/A"
        value = technical.get(name)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return "N/A"
        return number if math.isfinite(number) else "N/A"

    positive_lows = [_as_float(bar.get("low")) for bar in period_bars]
    positive_lows = [value for value in positive_lows if value > 0]
    total_amount = sum(_as_float(bar.get("amount")) for bar in period_bars) / 100_000_000

    return {
        "symbol": symbol,
        "name": stock_name,
        "close": round(latest_close, 4),
        "day_change": round(day_change, 4),
        "period_change": round(period_change, 4),
        "period_high": round(max((_as_float(bar.get("high")) for bar in period_bars), default=0.0), 4),
        "period_low": round(min(positive_lows, default=0.0), 4),
        "days": len(period_bars),
        "volume": _as_float(latest.get("volume")),
        "total_amount": round(total_amount, 4),
        "turnover": _as_float(latest.get("turnover")),
        "volatility": _as_float(latest.get("amplitude")),
        "ma5": indicator("ma5", 5),
        "ma20": indicator("ma20", 20),
        "ma60": indicator("ma60", 60),
        "rsi": indicator("rsi", 15),
        "dif": indicator("dif", 26),
        "dea": indicator("dea", 26),
        "macd": indicator("macd", 26),
        "vol_ratio": indicator("volume_ratio", 5),
        "data_status": "ok" if latest_close > 0 and ordered_bars else "missing",
        "fundamentals": "暂无",
        "as_of": _as_of_string(as_of),
        "price_data_date": str(latest.get("date") or ""),
        "research_question": research_question.strip(),
    }
