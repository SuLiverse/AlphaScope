"""Fund-flow API endpoints with graceful degradation at provider boundaries."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from backend.provider_timeout import call_with_timeout
from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/fund-flow", tags=["fund-flow"])

FUND_FLOW_TIMEOUT_SECONDS = 8.0


def _empty_summary(recent_days: int = 5) -> dict[str, Any]:
    return {
        "recent_days": recent_days,
        "main_total_yi": 0.0,
        "super_total_yi": 0.0,
        "large_total_yi": 0.0,
        "medium_total_yi": 0.0,
        "small_total_yi": 0.0,
        "last_date": "",
        "last_main_yi": 0.0,
        "last_main_pct": 0.0,
        "inflow_days": 0,
        "outflow_days": 0,
    }


def _degraded_response(
    payload: dict[str, Any],
    *,
    error: str,
    source_status: str,
) -> ApiResponse[dict[str, Any]]:
    payload.update(
        {
            "degraded": True,
            "source": payload.get("source") or "eastmoney",
            "source_status": source_status,
            "error": error,
        }
    )
    return ApiResponse(success=True, data=payload, error=error, error_code="FUND_FLOW_DEGRADED")


def _source_meta(df, default_source: str = "eastmoney") -> dict[str, Any]:
    return {
        "degraded": bool(getattr(df, "attrs", {}).get("degraded")),
        "source": getattr(df, "attrs", {}).get("source") or default_source,
        "source_status": getattr(df, "attrs", {}).get("source_status") or "ok",
        "error": getattr(df, "attrs", {}).get("error") or "",
        "cached_at": getattr(df, "attrs", {}).get("cached_at") or "",
    }


def _as_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


@router.get("/{symbol}")
def get_fund_flow(symbol: str, days: int = 30):
    """Individual-stock fund flow."""
    from backend.fund_flow import (
        fetch_individual_fund_flow,
        summarize_fund_flow,
    )

    base_payload = {
        "symbol": symbol,
        "summary": _empty_summary(),
        "records": [],
        "degraded": False,
        "source": "eastmoney",
        "source_status": "ok",
    }

    try:
        df = call_with_timeout(
            lambda: fetch_individual_fund_flow(symbol, days=days),
            FUND_FLOW_TIMEOUT_SECONDS,
            name="fund-flow-provider",
        )
    except TimeoutError as exc:
        return _degraded_response(
            base_payload,
            error=str(exc),
            source_status="timeout",
        )
    except Exception as exc:
        return _degraded_response(
            base_payload,
            error=str(exc),
            source_status="unavailable",
        )

    if df is None or len(df) == 0:
        return _degraded_response(
            base_payload,
            error="No fund-flow data returned by provider",
            source_status="empty",
        )

    try:
        summary = summarize_fund_flow(df, recent_days=5) or _empty_summary()
        meta = _source_meta(df, default_source="eastmoney")
        records = []
        for _, row in df.iterrows():
            raw_date = row.get("日期")
            records.append(
                {
                    "date": str(raw_date.date()) if hasattr(raw_date, "date") else str(raw_date or ""),
                    "close": _as_float(row.get("收盘价")),
                    "change_pct": _as_float(row.get("涨跌幅")),
                    "main_net_yi": _as_float(row.get("主力净流入-净额")) / 1e8,
                    "main_net_pct": _as_float(row.get("主力净流入-净占比")),
                    "super_net_yi": _as_float(row.get("超大单净流入-净额")) / 1e8,
                    "large_net_yi": _as_float(row.get("大单净流入-净额")) / 1e8,
                    "medium_net_yi": _as_float(row.get("中单净流入-净额")) / 1e8,
                    "small_net_yi": _as_float(row.get("小单净流入-净额")) / 1e8,
                }
            )
    except Exception as exc:
        return _degraded_response(
            base_payload,
            error=str(exc),
            source_status="parse_error",
        )

    return ApiResponse(
        success=True,
        data={
            "symbol": symbol,
            "summary": summary,
            "records": records,
            "degraded": meta["degraded"],
            "source": meta["source"],
            "source_status": meta["source_status"],
            "error": meta["error"],
            "cached_at": meta["cached_at"],
        },
        error=meta["error"] or None,
        error_code="FUND_FLOW_DEGRADED" if meta["degraded"] else None,
    )


@router.get("/market/overview")
def get_market_fund_flow(days: int = 30):
    """Market-wide fund flow."""
    from backend.fund_flow import fetch_market_fund_flow, summarize_fund_flow

    base_payload = {
        "summary": _empty_summary(),
        "records": [],
        "degraded": False,
        "source": "akshare",
        "source_status": "ok",
    }

    try:
        df = call_with_timeout(
            lambda: fetch_market_fund_flow(days=days),
            FUND_FLOW_TIMEOUT_SECONDS,
            name="fund-flow-provider",
        )
    except TimeoutError as exc:
        return _degraded_response(
            base_payload,
            error=str(exc),
            source_status="timeout",
        )
    except Exception as exc:
        return _degraded_response(
            base_payload,
            error=str(exc),
            source_status="unavailable",
        )

    if df is None or len(df) == 0:
        return _degraded_response(
            base_payload,
            error="No market fund-flow data returned by provider",
            source_status="empty",
        )

    try:
        summary = summarize_fund_flow(df, recent_days=5) or _empty_summary()
        meta = _source_meta(df, default_source="akshare")
        records = []
        for _, row in df.iterrows():
            raw_date = row.get("日期")
            records.append(
                {
                    "date": str(raw_date.date()) if hasattr(raw_date, "date") else str(raw_date or ""),
                    "close": _as_float(row.get("上证-收盘价")),
                    "main_net_yi": _as_float(row.get("主力净流入-净额")) / 1e8,
                }
            )
    except Exception as exc:
        return _degraded_response(
            base_payload,
            error=str(exc),
            source_status="parse_error",
        )

    return ApiResponse(
        success=True,
        data={
            "summary": summary,
            "records": records,
            "degraded": meta["degraded"],
            "source": meta["source"],
            "source_status": meta["source_status"],
            "error": meta["error"],
            "cached_at": meta["cached_at"],
        },
        error=meta["error"] or None,
        error_code="FUND_FLOW_DEGRADED" if meta["degraded"] else None,
    )
