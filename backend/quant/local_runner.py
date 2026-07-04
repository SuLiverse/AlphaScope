"""Local-only quant backtest runner.

This module intentionally has no FastAPI or Pydantic dependency so it can be used
by CLI/tooling paths and by minimal CI environments.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

QUANT_PROVIDER_TIMEOUT_SECONDS = 8.0

_local_runs: list[dict[str, Any]] = []
_local_run_details: dict[str, dict[str, Any]] = {}


def infer_param_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    return "string"


def builtin_strategy_data() -> list[dict[str, Any]]:
    from backend.quant.strategies import StrategyRegistry

    strategies: list[dict[str, Any]] = []
    for item in StrategyRegistry.list_strategies():
        defaults = item.get("default_params") or item.get("params") or {}
        strategy_id = str(item.get("id") or item.get("name") or "")
        strategies.append(
            {
                "id": strategy_id,
                "name": strategy_id,
                "description": item.get("description", ""),
                "status": "active",
                "version": "local",
                "source": "local",
                "params": [
                    {
                        "name": name,
                        "type": infer_param_type(default),
                        "default": default,
                        "description": "",
                    }
                    for name, default in defaults.items()
                ],
            }
        )
    return strategies


def local_status_payload() -> dict[str, Any]:
    return {
        "connected": True,
        "external_connected": False,
        "can_run_backtest": True,
        "local_backtest_available": True,
        "execution_mode": "local",
        "version": "local",
        "strategy_count": len(builtin_strategy_data()),
        "active_runs": 0,
        "run_count": len(_local_runs),
        "error": None,
        "external_error": None,
        "degraded": False,
        "source_status": "local",
        "data_sources": ["local_price_store", "provider", "local_preview"],
        "capabilities": {
            "strategy_params": True,
            "single_symbol_backtest": True,
            "run_history": True,
            "risk_audit": True,
            "live_trading": False,
            "tdx_compile": True,
            "strategy_evolution": True,
            "pattern_recognition": True,
            "stock_pool_parse": True,
        },
    }


def list_local_runs() -> list[dict[str, Any]]:
    return list(_local_runs)


def get_local_run_detail(run_id: str) -> dict[str, Any] | None:
    return _local_run_details.get(run_id)


def _parse_date(value: str, fallback: datetime) -> datetime:
    try:
        return datetime.fromisoformat(str(value)[:10])
    except Exception:
        return fallback


def _clean_bars(bars: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for bar in bars:
        close = float(bar.get("close") or 0)
        if close <= 0:
            continue
        open_price = float(bar.get("open") or close)
        high = float(bar.get("high") or max(open_price, close))
        low = float(bar.get("low") or min(open_price, close))
        cleaned.append(
            {
                "symbol": bar.get("symbol") or symbol,
                "date": str(bar.get("date") or ""),
                "open": open_price,
                "high": max(high, open_price, close),
                "low": min(low, open_price, close),
                "close": close,
                "volume": float(bar.get("volume") or 0),
            }
        )
    return sorted(cleaned, key=lambda item: item["date"])


def _generate_preview_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
) -> list[dict[str, Any]]:
    end_dt = _parse_date(end_date, datetime.now())
    start_dt = _parse_date(start_date, end_dt - timedelta(days=365))
    if start_dt >= end_dt:
        start_dt = end_dt - timedelta(days=365)

    total_days = max((end_dt - start_dt).days, 90)
    target_points = max(90, min(520, int(total_days * 5 / 7)))
    step = max(1, total_days // target_points)
    seed = sum(ord(ch) for ch in symbol)
    price = max(8.0, min(initial_capital / 1000, 80.0 + (seed % 1200) / 10))
    bars: list[dict[str, Any]] = []

    current_date = start_dt
    index = 0
    while current_date <= end_dt and len(bars) < target_points:
        if current_date.weekday() < 5:
            drift = 0.00035 + ((seed % 17) - 8) * 0.00001
            wave = math.sin((index + seed % 29) / 9) * 0.012
            pulse = math.cos((index + seed % 13) / 5) * 0.006
            open_price = price
            close = max(1.0, open_price * (1 + drift + wave + pulse))
            high = max(open_price, close) * (1.006 + abs(wave) * 0.2)
            low = min(open_price, close) * (0.994 - abs(pulse) * 0.15)
            bars.append(
                {
                    "symbol": symbol,
                    "date": current_date.date().isoformat(),
                    "open": round(open_price, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": 200000 + (seed % 1000) * 100 + index * 37,
                }
            )
            price = close
            index += 1
        current_date += timedelta(days=step)

    return bars


def load_local_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
) -> tuple[list[dict[str, Any]], str]:
    try:
        from backend.price_store import (
            get_market,
            get_prices,
            normalize_symbol,
            save_price_bars,
        )
    except Exception:
        normalized_symbol = symbol
    else:
        normalized_symbol = normalize_symbol(symbol) or symbol
        start_dt = _parse_date(start_date, datetime.now() - timedelta(days=365))
        end_dt = _parse_date(end_date, datetime.now())
        limit = max(120, min(1000, (end_dt - start_dt).days + 30))

        bars = _clean_bars(
            get_prices(
                normalized_symbol,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
                include_incompatible=True,
            ),
            normalized_symbol,
        )
        if len(bars) >= 30:
            return bars, "local_price_store"

        try:
            from backend.provider_timeout import call_with_timeout
            from backend.providers.registry import get_registry

            provider_bars = call_with_timeout(
                lambda: get_registry().get(
                    data_type="prices",
                    market=get_market(normalized_symbol),
                    symbol=normalized_symbol,
                    limit=limit,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    period="daily",
                    frequency="1d",
                    adjust="",
                ),
                QUANT_PROVIDER_TIMEOUT_SECONDS,
                name="quant-price-provider",
            )
            if provider_bars:
                save_price_bars(provider_bars)
                bars = _clean_bars(provider_bars, normalized_symbol)
                if len(bars) >= 30:
                    return bars, "provider"
        except Exception:
            pass

    return (
        _generate_preview_bars(
            normalized_symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
        ),
        "local_preview",
    )


def run_local_backtest_payload(
    strategy_id: str,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 1000000.0,
    params: dict[str, Any] | None = None,
    benchmark_symbol: str = "",
) -> dict[str, Any]:
    from backend.quant.engine import BacktestEngine
    from backend.quant.strategies import StrategyRegistry

    if StrategyRegistry.get(strategy_id) is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")
    strategy = StrategyRegistry.create(strategy_id, params)
    if strategy is None:
        raise ValueError(f"Unknown strategy: {strategy_id}")

    bars, data_source = load_local_bars(
        symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
    )
    # 可选基准(如沪深300 sh000300): 取不到数据则优雅降级, 基准指标为 0。
    benchmark_bars = None
    bench_name = ""
    if benchmark_symbol:
        try:
            benchmark_bars, _ = load_local_bars(
                benchmark_symbol,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
            )
            bench_name = benchmark_symbol
        except Exception:
            benchmark_bars = None
    engine = BacktestEngine(initial_capital=initial_capital, commission_rate=0.001)
    result = engine.run(strategy, bars, symbol, benchmark_bars=benchmark_bars, benchmark_name=bench_name)
    performance = result.performance or {}
    now = datetime.now()
    run_id = f"local-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    final_equity = float(
        performance.get("final_equity") or (result.equity_curve[-1] if result.equity_curve else initial_capital)
    )
    equity_curve = [
        {"date": date, "equity": equity, "value": equity} for date, equity in zip(result.dates, result.equity_curve)
    ]
    payload = {
        "run_id": run_id,
        "strategy_id": strategy.name,
        "symbol": symbol,
        "status": "completed",
        "assumptions": getattr(result, "assumptions", {}) or {},
        "metrics": {
            "total_return": performance.get("total_return", 0.0),
            "annual_return": performance.get("annualized_return", 0.0),
            "sharpe_ratio": performance.get("sharpe_ratio", 0.0),
            "max_drawdown": performance.get("max_drawdown", 0.0),
            "win_rate": performance.get("win_rate", 0.0),
            "trade_count": performance.get("total_trades", len(result.trades)),
            "profit_factor": performance.get("profit_factor", 0.0),
            "sortino_ratio": performance.get("sortino_ratio", 0.0),
            "calmar_ratio": performance.get("calmar_ratio", 0.0),
            "volatility": performance.get("volatility", 0.0),
            "initial_capital": initial_capital,
            "final_equity": final_equity,
            "trading_days": performance.get("trading_days", len(bars)),
        },
        "equity_curve": equity_curve,
        "trades": result.trades,
        "risk_violations": result.risk_violations,
        "summary": {
            "bar_count": len(bars),
            "trade_count": performance.get("total_trades", len(result.trades)),
            "risk_violation_count": len(result.risk_violations),
            "start_date": bars[0]["date"] if bars else start_date,
            "end_date": bars[-1]["date"] if bars else end_date,
            "data_source": data_source,
            "data_source_label": data_source,
        },
        "started_at": now.isoformat(),
        "finished_at": now.isoformat(),
        "source_status": "local",
        "data_source": data_source,
        "degraded": data_source == "local_preview",
        "engine": "local",
        "params": strategy.params,
        "message": (
            "Used deterministic local preview bars for this backtest."
            if data_source == "local_preview"
            else "Local backtest completed."
        ),
    }
    _local_runs.insert(
        0,
        {
            "run_id": run_id,
            "strategy_id": strategy.name,
            "symbol": symbol,
            "mode": "backtest",
            "status": "completed",
            "total_return": payload["metrics"]["total_return"],
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "source_status": payload["source_status"],
            "data_source": data_source,
        },
    )
    del _local_runs[20:]
    _local_run_details[run_id] = payload
    for stale_run_id in list(_local_run_details.keys())[50:]:
        _local_run_details.pop(stale_run_id, None)
    return payload
