"""Quant API core helpers — bars, local runs, strategy execution (no HTTP routes).

Extracted from quant.py to keep the FastAPI router thin. Public HTTP paths and
payload shapes are unchanged; backend.api.quant re-exports symbols tests import.
"""

from __future__ import annotations

import csv
import io
import math
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from backend.api.quant_schemas import (
    BacktestRequestBody,
    ChipDistributionRequestBody,
    EvolveRequestBody,
    PatternsRequestBody,
    StrategyCompareRequestBody,
    WalkForwardRequestBody,
)
from backend.provider_timeout import call_with_timeout
from backend.stock_resolver import resolve_stock

_local_runs: list[dict[str, Any]] = []
_local_run_details: dict[str, dict[str, Any]] = {}
QUANT_PROVIDER_TIMEOUT_SECONDS = 8.0


def _infer_param_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    return "string"


def _builtin_strategy_data() -> list[dict[str, Any]]:
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
                        "type": _infer_param_type(default),
                        "default": default,
                        "description": "",
                    }
                    for name, default in defaults.items()
                ],
            }
        )
    return strategies


def _local_status_payload() -> dict[str, Any]:
    builtin_count = len(_builtin_strategy_data())
    return {
        "connected": True,
        "external_connected": False,
        "can_run_backtest": True,
        "local_backtest_available": True,
        "execution_mode": "local",
        "version": "local",
        "strategy_count": builtin_count,
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


def _load_local_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float,
    *,
    allow_preview_data: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    from backend.price_store import (
        get_market,
        get_prices,
        normalize_symbol,
        save_price_bars,
    )

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

    # 默认不自动灌合成样例行情，避免用户误以为是真实行情（审查 P0）。
    # 前端勾选「允许演示样例行情」或 API 传 allow_preview_data=true 时才生成。
    if not allow_preview_data:
        return [], "unavailable"

    return (
        _generate_preview_bars(
            normalized_symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
        ),
        "local_preview",
    )


_MSG_NEED_REAL_OR_PREVIEW = (
    "真实行情不足（本地库与数据源均无可用 K 线）。"
    "请检查网络/数据源，或在请求中设置 allow_preview_data=true 使用演示样例行情（仅预览，非真实）。"
)


def _require_bars(
    body: PreviewOptIn,
    *,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 1_000_000.0,
    min_bars: int = 30,
) -> tuple[list[dict[str, Any]], str]:
    """统一取数 + 守卫：不足且未 opt-in preview 时 raise，供各 quant runner 复用。"""
    bars, data_source = _load_local_bars(
        symbol,
        start_date=start_date,
        end_date=end_date,
        initial_capital=initial_capital,
        allow_preview_data=body.allow_preview_data,
    )
    if data_source == "unavailable" or len(bars) < min_bars:
        raise ValueError(_MSG_NEED_REAL_OR_PREVIEW)
    return bars, data_source


def _source_fields(data_source: str, *, extra_degraded: bool = False) -> dict[str, Any]:
    """统一 data_source / label / is_preview / degraded，避免各 runner 复制三元表达式。"""
    is_preview = data_source == "local_preview"
    if is_preview:
        label = "本地样例行情"
    elif data_source == "provider":
        label = "实时数据源"
    elif data_source == "unavailable":
        label = "无可用行情"
    else:
        label = "本地行情库"
    return {
        "data_source": data_source,
        "data_source_label": label,
        "is_preview": is_preview,
        "degraded": is_preview or extra_degraded,
    }


def _persist_experiment(payload: dict[str, Any]) -> None:
    """失败安全地把运行载荷落库(experiment_store),供跨会话查询/对比。

    持久化失败绝不影响运行本身(诚实降级:没存就是没存,不假装成功)。
    """
    try:
        from backend.quant.experiment_store import save_experiment

        save_experiment(payload)
    except Exception:
        pass


def _run_local_backtest(body: BacktestRequestBody) -> dict[str, Any]:
    from backend.quant.engine import BacktestEngine
    from backend.quant.strategies import StrategyRegistry

    strategy_id = body.strategy_id
    if StrategyRegistry.get(strategy_id) is None:
        raise ValueError(f"策略不存在: {body.strategy_id}")
    strategy = StrategyRegistry.create(strategy_id, body.params)
    if strategy is None:
        raise ValueError(f"策略不存在: {body.strategy_id}")

    bars, data_source = _require_bars(
        body,
        symbol=body.symbol,
        start_date=body.start_date,
        end_date=body.end_date,
        initial_capital=body.initial_capital,
    )
    engine = BacktestEngine(initial_capital=body.initial_capital, commission_rate=0.001)
    result = engine.run(strategy, bars, body.symbol)
    performance = result.performance or {}
    now = datetime.now()
    run_id = f"local-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    final_equity = float(
        performance.get("final_equity") or (result.equity_curve[-1] if result.equity_curve else body.initial_capital)
    )
    equity_curve = [
        {"date": date, "equity": equity, "value": equity} for date, equity in zip(result.dates, result.equity_curve)
    ]
    payload = {
        "run_id": run_id,
        "strategy_id": strategy.name,
        "symbol": body.symbol,
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
            "initial_capital": body.initial_capital,
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
            "start_date": bars[0]["date"] if bars else body.start_date,
            "end_date": bars[-1]["date"] if bars else body.end_date,
            **_source_fields(data_source),
        },
        "started_at": now.isoformat(),
        "finished_at": now.isoformat(),
        "source_status": "local",
        **_source_fields(data_source),
        "engine": "local",
        "params": strategy.params,
        "message": (
            "已使用本地样例行情完成回测，仅用于功能预览。"
            if data_source == "local_preview"
            else "已使用本地回测引擎完成回测。"
        ),
    }
    _local_runs.insert(
        0,
        {
            "run_id": run_id,
            "strategy_id": strategy.name,
            "symbol": body.symbol,
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
    _persist_experiment(payload)
    return payload


def _run_patterns_local(body: "PatternsRequestBody") -> dict[str, Any]:
    """加载本地行情并做 K 线形态识别, 返回 API 载荷。形态识别纯确定性、不触网。"""
    from backend.quant.patterns import detect_patterns

    bars, data_source = _require_bars(
        body,
        symbol=body.symbol,
        start_date=body.start_date,
        end_date=body.end_date,
        min_bars=1,
    )
    report = detect_patterns(bars, symbol=body.symbol, lookback=body.lookback)
    payload = report.to_dict()
    payload.update(
        {
            **_source_fields(data_source, extra_degraded=report.status != "ok"),
        }
    )
    return payload


def _run_chip_distribution_local(body: "ChipDistributionRequestBody") -> dict[str, Any]:
    """加载本地行情并计算筹码(成本)分布,返回 API 载荷。

    优先直接取**原始** bar(含换手率, 走真实换手扩散模型); 不足时退回带 provider/
    preview 兜底的清洗取数(无换手 → 量能代理)。筹码分布本身纯确定性、不触网。
    """
    from backend.price_store import get_prices, normalize_symbol
    from backend.quant.chip_distribution import compute_chip_distribution

    sym = normalize_symbol(body.symbol) or body.symbol
    start_dt = _parse_date(body.start_date, datetime.now() - timedelta(days=365))
    end_dt = _parse_date(body.end_date, datetime.now())
    limit = max(120, min(1000, (end_dt - start_dt).days + 30))

    raw = (
        get_prices(
            sym,
            start_date=body.start_date,
            end_date=body.end_date,
            limit=limit,
            include_incompatible=True,
        )
        or []
    )
    data_source = "local_price_store"
    if len(raw) < 20:
        # 退回清洗取数(带 provider/preview 兜底)。换手率会被剥离 → 走量能代理。
        raw, data_source = _require_bars(
            body,
            symbol=body.symbol,
            start_date=body.start_date,
            end_date=body.end_date,
            initial_capital=100000.0,
            min_bars=1,
        )

    report = compute_chip_distribution(raw, symbol=body.symbol, price_levels=body.price_levels)
    now = datetime.now()
    run_id = f"chip-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    payload = report.to_dict()
    payload.update(
        {
            "run_id": run_id,
            "mode": "chip_distribution",
            **_source_fields(data_source, extra_degraded=report.status != "ok"),
            "bar_count": len(raw),
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "message": (
                "已使用本地样例行情完成筹码分布,仅用于功能预览。" if data_source == "local_preview" else report.note
            ),
        }
    )
    _persist_experiment(payload)
    return payload


# 策略横向对比不参与对比的模板策略(需用户配置规则/公式才有信号)。
_COMPARE_SKIP_STRATEGIES = {"custom_rule", "tdx"}
_COMPARE_RANK_KEYS = {
    "sharpe_ratio",
    "total_return",
    "calmar_ratio",
    "annual_return",
    "win_rate",
}


def _run_strategy_comparison_local(
    body: "StrategyCompareRequestBody",
) -> dict[str, Any]:
    """同一标的/区间跑全部内置策略并按指标排名,返回 API 载荷。

    只取一次行情,所有策略复用同一份 bar(各自拷贝避免互相污染),复用已测回测引擎。
    纯本地、确定性;模板策略(custom_rule)无默认信号,跳过并在 skipped 中标注。
    """
    from backend.quant.engine import BacktestEngine
    from backend.quant.strategies import StrategyRegistry

    rank_by = body.rank_by if body.rank_by in _COMPARE_RANK_KEYS else "sharpe_ratio"
    bars, data_source = _require_bars(
        body,
        symbol=body.symbol,
        start_date=body.start_date,
        end_date=body.end_date,
        initial_capital=body.initial_capital,
    )

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for meta in StrategyRegistry.list_strategies():
        name = meta.get("name", "")
        if not name or name in _COMPARE_SKIP_STRATEGIES:
            if name:
                skipped.append(name)
            continue
        strategy = StrategyRegistry.create(name, {})
        if strategy is None:
            continue
        engine = BacktestEngine(initial_capital=body.initial_capital, commission_rate=0.001)
        result = engine.run(strategy, [dict(b) for b in bars], body.symbol)
        perf = result.performance or {}
        rows.append(
            {
                "strategy_id": name,
                "strategy_name": name,
                "description": meta.get("description", ""),
                "total_return": perf.get("total_return", 0.0),
                "annual_return": perf.get("annualized_return", 0.0),
                "sharpe_ratio": perf.get("sharpe_ratio", 0.0),
                "sortino_ratio": perf.get("sortino_ratio", 0.0),
                "calmar_ratio": perf.get("calmar_ratio", 0.0),
                "max_drawdown": perf.get("max_drawdown", 0.0),
                "win_rate": perf.get("win_rate", 0.0),
                "profit_factor": perf.get("profit_factor", 0.0),
                "trade_count": perf.get("total_trades", len(result.trades)),
                "risk_violations": len(result.risk_violations),
            }
        )

    # 排名:指标越大越好(max_drawdown 是负数,这里不作为默认排名键)。
    rows.sort(key=lambda r: r.get(rank_by, 0.0), reverse=True)
    for i, row in enumerate(rows):
        row["rank"] = i + 1

    now = datetime.now()
    run_id = f"cmp-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    assumptions: dict[str, Any] = {}
    if bars:
        # 任一引擎实例的假设都一致,取一次披露给前端。
        assumptions = BacktestEngine(initial_capital=body.initial_capital)._assumptions()
    payload = {
        "run_id": run_id,
        "mode": "strategy_compare",
        "symbol": body.symbol,
        "rank_by": rank_by,
        "ranking": rows,
        "skipped": skipped,
        "evaluated": len(rows),
        "assumptions": assumptions,
        **_source_fields(data_source),
        "bar_count": len(bars),
        "started_at": now.isoformat(),
        "finished_at": now.isoformat(),
        "message": (
            "已使用本地样例行情完成策略对比,仅用于功能预览。"
            if data_source == "local_preview"
            else f"已对 {len(rows)} 个内置策略完成横向对比(按 {rank_by} 排名)。"
        ),
        "disclaimer": "对比基于历史回测,不代表未来表现,不构成投资建议或选股推荐。",
    }
    _persist_experiment(payload)
    return payload


def _run_walk_forward_local(body: "WalkForwardRequestBody") -> dict[str, Any]:
    """加载本地行情并运行样本外走查分析，返回 API 载荷。

    复用回测的取数链路(_load_local_bars)与策略注册表；走查本身是纯确定性计算
    (backend.quant.walk_forward)，不触网、失败安全。
    """
    from backend.quant.strategies import StrategyRegistry
    from backend.quant.walk_forward import run_walk_forward

    if StrategyRegistry.get(body.strategy_id) is None:
        raise ValueError(f"策略不存在: {body.strategy_id}")

    bars, data_source = _require_bars(
        body,
        symbol=body.symbol,
        start_date=body.start_date,
        end_date=body.end_date,
        initial_capital=body.initial_capital,
    )
    report = run_walk_forward(
        body.strategy_id,
        bars,
        symbol=body.symbol,
        n_splits=body.n_splits,
        scheme=body.scheme,
        initial_capital=body.initial_capital,
        params=body.params,
    )
    now = datetime.now()
    run_id = f"wf-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    payload = report.to_dict()
    payload.update(
        {
            "run_id": run_id,
            "strategy_id": body.strategy_id,
            "mode": "walk_forward",
            **_source_fields(data_source, extra_degraded=report.status != "ok"),
            "bar_count": len(bars),
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "message": (
                "已使用本地样例行情完成走查，仅用于功能预览。" if data_source == "local_preview" else report.note
            ),
        }
    )
    _persist_experiment(payload)
    return payload


def _run_evolution_local(body: "EvolveRequestBody") -> dict[str, Any]:
    """加载本地行情并运行遗传算法参数寻优,返回 API 载荷。

    复用回测取数链路(_load_local_bars)与策略注册表;GA 本身纯确定性(同 seed
    同结果)、失败安全(backend.quant.evolution),适应度=复用回测引擎。
    """
    from backend.quant.evolution import run_evolution
    from backend.quant.strategies import StrategyRegistry

    if StrategyRegistry.get(body.strategy_id) is None:
        raise ValueError(f"策略不存在: {body.strategy_id}")

    bars, data_source = _require_bars(
        body,
        symbol=body.symbol,
        start_date=body.start_date,
        end_date=body.end_date,
        initial_capital=body.initial_capital,
    )
    report = run_evolution(
        body.strategy_id,
        bars,
        symbol=body.symbol,
        param_space=body.param_space or None,
        population_size=body.population_size,
        generations=body.generations,
        fitness_metric=body.fitness_metric,
        initial_capital=body.initial_capital,
        seed=body.seed,
        base_params=body.params or None,
    )
    now = datetime.now()
    run_id = f"evo-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    payload = report.to_dict()
    payload.update(
        {
            "run_id": run_id,
            "mode": "evolution",
            **_source_fields(data_source, extra_degraded=report.status != "ok"),
            "bar_count": len(bars),
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "message": (
                "已使用本地样例行情完成寻优，仅用于功能预览。" if data_source == "local_preview" else report.message
            ),
        }
    )
    _persist_experiment(payload)
    return payload


def _extract_stock_pool_symbols(text: str, limit: int = 200) -> list[str]:
    seen: set[str] = set()
    symbols: list[str] = []
    for match in re.finditer(r"\b\d{5,6}\b", text or ""):
        code = match.group(0)
        if code not in seen:
            seen.add(code)
            symbols.append(code)
        if len(symbols) >= limit:
            break
    return symbols


def _stock_pool_csv(symbols: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["symbol", "name", "market", "exchange", "source"])
    for symbol in symbols:
        identity = resolve_stock(symbol)
        writer.writerow(
            [
                identity.get("symbol") or symbol,
                identity.get("name") or "",
                identity.get("market") or "",
                identity.get("exchange") or "",
                identity.get("source") or "",
            ]
        )
    return buffer.getvalue()


def run_local_backtest_payload(
    strategy_id: str,
    symbol: str,
    start_date: str,
    end_date: str,
    initial_capital: float = 1000000.0,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the built-in local backtest engine and return the API payload."""
    return _run_local_backtest(
        BacktestRequestBody(
            strategy_id=strategy_id,
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
            params=params or {},
        )
    )

