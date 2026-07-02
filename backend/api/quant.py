"""量化实验室 API — 项目内置本地回测端点。

本模块默认不探测、不监听外部量化服务。参考外部量化项目的策略/回测/报告思路，
但运行链路固定使用当前项目内置策略、行情缓存、provider 取数和本地回测引擎。
"""

from __future__ import annotations

import asyncio
import csv
import io
import math
import re
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.provider_timeout import call_with_timeout
from backend.schemas.api import ApiResponse
from backend.stock_resolver import resolve_stock

router = APIRouter(prefix="/api/quant", tags=["quant"])

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

    return (
        _generate_preview_bars(
            normalized_symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=initial_capital,
        ),
        "local_preview",
    )


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

    bars, data_source = _load_local_bars(
        body.symbol,
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
        performance.get("final_equity")
        or (result.equity_curve[-1] if result.equity_curve else body.initial_capital)
    )
    equity_curve = [
        {"date": date, "equity": equity, "value": equity}
        for date, equity in zip(result.dates, result.equity_curve)
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
            "data_source": data_source,
            "data_source_label": (
                "本地样例行情"
                if data_source == "local_preview"
                else "实时数据源"
                if data_source == "provider"
                else "本地行情库"
            ),
        },
        "started_at": now.isoformat(),
        "finished_at": now.isoformat(),
        "source_status": "local",
        "data_source": data_source,
        "degraded": data_source == "local_preview",
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

    bars, data_source = _load_local_bars(
        body.symbol,
        start_date=body.start_date,
        end_date=body.end_date,
        initial_capital=1_000_000.0,
    )
    report = detect_patterns(bars, symbol=body.symbol, lookback=body.lookback)
    payload = report.to_dict()
    payload.update(
        {
            "data_source": data_source,
            "data_source_label": (
                "本地样例行情"
                if data_source == "local_preview"
                else "实时数据源"
                if data_source == "provider"
                else "本地行情库"
            ),
            "degraded": data_source == "local_preview" or report.status != "ok",
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
        raw, data_source = _load_local_bars(
            body.symbol,
            start_date=body.start_date,
            end_date=body.end_date,
            initial_capital=100000.0,
        )

    report = compute_chip_distribution(
        raw, symbol=body.symbol, price_levels=body.price_levels
    )
    now = datetime.now()
    run_id = f"chip-{now.strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:6]}"
    payload = report.to_dict()
    payload.update(
        {
            "run_id": run_id,
            "mode": "chip_distribution",
            "data_source": data_source,
            "data_source_label": (
                "本地样例行情"
                if data_source == "local_preview"
                else "实时数据源"
                if data_source == "provider"
                else "本地行情库"
            ),
            "bar_count": len(raw),
            "degraded": data_source == "local_preview" or report.status != "ok",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "message": (
                "已使用本地样例行情完成筹码分布,仅用于功能预览。"
                if data_source == "local_preview"
                else report.note
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
    bars, data_source = _load_local_bars(
        body.symbol,
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
        engine = BacktestEngine(
            initial_capital=body.initial_capital, commission_rate=0.001
        )
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
        assumptions = BacktestEngine(
            initial_capital=body.initial_capital
        )._assumptions()
    payload = {
        "run_id": run_id,
        "mode": "strategy_compare",
        "symbol": body.symbol,
        "rank_by": rank_by,
        "ranking": rows,
        "skipped": skipped,
        "evaluated": len(rows),
        "assumptions": assumptions,
        "data_source": data_source,
        "data_source_label": (
            "本地样例行情"
            if data_source == "local_preview"
            else "实时数据源"
            if data_source == "provider"
            else "本地行情库"
        ),
        "bar_count": len(bars),
        "degraded": data_source == "local_preview",
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


# ============================================================
# 请求模型
# ============================================================


def _run_walk_forward_local(body: "WalkForwardRequestBody") -> dict[str, Any]:
    """加载本地行情并运行样本外走查分析，返回 API 载荷。

    复用回测的取数链路(_load_local_bars)与策略注册表；走查本身是纯确定性计算
    (backend.quant.walk_forward)，不触网、失败安全。
    """
    from backend.quant.strategies import StrategyRegistry
    from backend.quant.walk_forward import run_walk_forward

    if StrategyRegistry.get(body.strategy_id) is None:
        raise ValueError(f"策略不存在: {body.strategy_id}")

    bars, data_source = _load_local_bars(
        body.symbol,
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
            "data_source": data_source,
            "data_source_label": (
                "本地样例行情"
                if data_source == "local_preview"
                else "实时数据源"
                if data_source == "provider"
                else "本地行情库"
            ),
            "bar_count": len(bars),
            "degraded": data_source == "local_preview" or report.status != "ok",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "message": (
                "已使用本地样例行情完成走查，仅用于功能预览。"
                if data_source == "local_preview"
                else report.note
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

    bars, data_source = _load_local_bars(
        body.symbol,
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
            "data_source": data_source,
            "data_source_label": (
                "本地样例行情"
                if data_source == "local_preview"
                else "实时数据源"
                if data_source == "provider"
                else "本地行情库"
            ),
            "bar_count": len(bars),
            "degraded": data_source == "local_preview" or report.status != "ok",
            "started_at": now.isoformat(),
            "finished_at": now.isoformat(),
            "message": (
                "已使用本地样例行情完成寻优，仅用于功能预览。"
                if data_source == "local_preview"
                else report.message
            ),
        }
    )
    _persist_experiment(payload)
    return payload


class BacktestRequestBody(BaseModel):
    """回测请求体"""

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数覆盖")


class WalkForwardRequestBody(BaseModel):
    """走查(walk-forward)样本外稳健性分析请求体。

    复用回测的取数与策略，额外指定样本外窗口数与切分方案。
    """

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数覆盖")
    n_splits: int = Field(
        default=5, description="样本外窗口数(2-12, 数据不足时自动收敛)"
    )
    scheme: str = Field(
        default="anchored", description="切分方案: anchored(锚定) | rolling(滚动)"
    )


class ChipDistributionRequestBody(BaseModel):
    """筹码(成本)分布请求体。"""

    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    price_levels: int = Field(default=100, description="价位离散桶数(20-400)")


class PatternsRequestBody(BaseModel):
    """K 线形态识别请求体。"""

    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    lookback: int = Field(default=60, description="蜡烛形态扫描窗口(最近 N 根)")


class StrategyCompareRequestBody(BaseModel):
    """策略横向对比请求体:同一标的/区间跑全部内置策略并排名。"""

    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    rank_by: str = Field(
        default="sharpe_ratio",
        description="排名指标: sharpe_ratio|total_return|calmar_ratio",
    )


class ExperimentCompareBody(BaseModel):
    """实验横向对比请求体。"""

    run_ids: list[str] = Field(
        default_factory=list, description="要对比的实验 run_id 列表"
    )


class EvolveRequestBody(BaseModel):
    """遗传算法策略参数寻优请求体。

    复用回测的取数与策略;在策略的数值参数空间内用确定性 GA 搜索更优组合。
    样本内寻优极易过拟合,结果附强免责并建议再做样本外走查。
    """

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    params: dict[str, Any] = Field(
        default_factory=dict, description="固定基底参数(不被进化)"
    )
    param_space: dict[str, Any] = Field(
        default_factory=dict, description="可选显式搜索空间;缺省由默认参数推断"
    )
    population_size: int = Field(default=16, description="种群规模(4-40, 自动夹紧)")
    generations: int = Field(default=8, description="进化代数(1-20, 受算力预算约束)")
    fitness_metric: str = Field(
        default="sharpe_ratio",
        description="适应度指标: sharpe_ratio|calmar_ratio|sortino_ratio|total_return|annualized_return|profit_factor|win_rate",
    )
    seed: int = Field(default=42, description="随机种子(决定可复现性)")


class TdxCompileRequestBody(BaseModel):
    """通达信公式编译(语法检查/预览)请求体。"""

    formula: str = Field(description="通达信(TDX)公式源码")


class LiveStartBody(BaseModel):
    """实盘启动请求体"""

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数覆盖")
    capital: float = Field(default=1000000.0, description="投入资金")


class LiveStopBody(BaseModel):
    """实盘停止请求体"""

    run_id: str = Field(description="运行ID")


class StockPoolExportRequest(BaseModel):
    """Stock pool CSV export request."""

    text: str = Field(description="Stock pool text containing symbols")


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


# ============================================================
# 端点
# ============================================================


@router.get("/status")
async def get_status():
    """获取回测能力状态"""
    data = _local_status_payload()
    return ApiResponse(
        success=True,
        data=data,
        message="本地回测引擎可用。",
    )


@router.get("/strategies")
async def list_strategies():
    """获取策略列表"""
    return ApiResponse(
        success=True,
        data={
            "strategies": _builtin_strategy_data(),
            "can_run_backtest": True,
            "local_backtest_available": True,
            "execution_mode": "local",
            "source_status": "local",
            "degraded": False,
        },
    )


@router.get("/strategies/{strategy_name}")
async def get_strategy(strategy_name: str):
    """获取本地内置策略详情"""
    for strategy in _builtin_strategy_data():
        if strategy.get("name") == strategy_name:
            return ApiResponse(success=True, data=strategy)
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_name}")


@router.get("/builtin-strategies")
async def list_builtin_strategies():
    """列出本地内置策略"""
    return ApiResponse(success=True, data=_builtin_strategy_data())


@router.post("/strategies/reload")
async def reload_strategies():
    """重载策略"""
    strategies = _builtin_strategy_data()
    return ApiResponse(
        success=True,
        data={
            "reloaded": len(strategies),
            "strategies": strategies,
            "can_run_backtest": True,
            "local_backtest_available": True,
            "execution_mode": "local",
            "source_status": "local",
            "degraded": False,
        },
        message=f"已加载 {len(strategies)} 个本地策略。",
    )


@router.post("/stock-pool/export")
async def export_stock_pool(body: StockPoolExportRequest):
    """Export a parsed stock pool as a testable server-side CSV file."""
    symbols = _extract_stock_pool_symbols(body.text)
    if not symbols:
        return ApiResponse(
            success=False,
            error="No valid stock symbols found",
            error_code="STOCK_POOL_EMPTY",
        )

    csv_text = _stock_pool_csv(symbols)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="alphascope-stock-pool.csv"'
        },
    )


@router.post("/backtest")
async def run_backtest(body: BacktestRequestBody):
    """发起回测（同步重计算丢线程池，避免阻塞事件循环）"""
    try:
        result = await asyncio.to_thread(_run_local_backtest, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_BACKTEST_ERROR",
        )


@router.post("/walk-forward")
async def run_walk_forward_endpoint(body: WalkForwardRequestBody):
    """样本外走查(walk-forward)稳健性分析。

    把历史切成锚定/滚动的 IS+OOS 窗口，逐窗用同一策略回测，评估策略在不同
    历史区间的稳健性(而非单一窗口的运气)。纯确定性、失败安全。
    同步重计算丢线程池，避免阻塞事件循环。
    """
    try:
        result = await asyncio.to_thread(_run_walk_forward_local, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_WALK_FORWARD_ERROR",
        )


@router.post("/chip-distribution")
async def run_chip_distribution_endpoint(body: ChipDistributionRequestBody):
    """筹码(成本)分布分析。

    用换手率扩散模型重建当前持仓成本分布,读出获利盘/平均成本/集中度/上下方
    筹码密集价。纯确定性、失败安全;描述历史成本结构,不预测价格、不构成建议。
    同步重计算丢线程池,避免阻塞事件循环。
    """
    try:
        result = await asyncio.to_thread(_run_chip_distribution_local, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_CHIP_DISTRIBUTION_ERROR",
        )


@router.post("/patterns")
async def run_patterns_endpoint(body: PatternsRequestBody):
    """K 线形态识别。确定性检出蜡烛形态(吞没/锤子/十字星/启明星-黄昏星/红三兵-三只乌鸦)
    与结构信号(跳空/N 日突破/均线金叉死叉/双顶双底)。纯本地、失败安全;描述历史形态,
    不预测涨跌、不构成任何投资建议。同步重计算丢线程池,避免阻塞事件循环。
    """
    try:
        result = await asyncio.to_thread(_run_patterns_local, body)
        return ApiResponse(
            success=True, data=result, message=result.get("note") or None
        )
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_PATTERNS_ERROR",
        )


@router.post("/compare-strategies")
async def run_strategy_comparison_endpoint(body: StrategyCompareRequestBody):
    """策略横向对比:同一标的/区间跑全部内置策略并按指标排名。

    一次取数、复用已测回测引擎逐策略回测,帮助快速看哪些策略在该标的上历史表现更好。
    纯本地、确定性;同步重计算丢线程池,避免阻塞事件循环。结果仅供历史研究,不构成选股建议。
    """
    try:
        result = await asyncio.to_thread(_run_strategy_comparison_local, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_STRATEGY_COMPARE_ERROR",
        )


@router.post("/evolve")
async def run_evolution_endpoint(body: EvolveRequestBody):
    """遗传算法策略参数寻优。

    在策略的数值参数空间内用**确定性**遗传算法(同 seed 同结果)搜索更优组合,
    适应度=复用回测引擎跑一遍的某项绩效(默认夏普)。纯本地、失败安全。
    同步重计算丢线程池,避免阻塞事件循环。

    合规:样本内寻优极易过拟合,样本内最优≠未来有效;响应附强免责并建议对最优
    参数再做样本外走查验证。不构成任何投资建议。
    """
    try:
        result = await asyncio.to_thread(_run_evolution_local, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_EVOLUTION_ERROR",
        )


@router.get("/param-space/{strategy_name}")
async def get_param_space_endpoint(strategy_name: str):
    """返回某策略可寻优的数值参数空间(供进化面板预填默认范围)。"""
    from backend.quant.evolution import infer_param_space

    space = await asyncio.to_thread(infer_param_space, strategy_name)
    return ApiResponse(
        success=True,
        data={
            "strategy_id": strategy_name,
            "param_space": space,
            "evolvable": bool(space),
        },
    )


@router.get("/experiments")
async def list_experiments_endpoint(mode: str = "", symbol: str = "", limit: int = Query(50, ge=1, le=500)):
    """列举已持久化的量化实验(回测/走查/筹码/策略榜),按时间倒序,可按 mode/symbol 过滤。"""
    from backend.quant.experiment_store import count_experiments, list_experiments

    items = await asyncio.to_thread(
        list_experiments, limit=limit, mode=mode or None, symbol=symbol or None
    )
    return ApiResponse(
        success=True,
        data={"experiments": items, "total": count_experiments()},
    )


@router.get("/experiments/{run_id}")
async def get_experiment_endpoint(run_id: str):
    """取一次实验的完整载荷。"""
    from backend.quant.experiment_store import get_experiment

    result = await asyncio.to_thread(get_experiment, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"实验记录不存在: {run_id}")
    return ApiResponse(success=True, data=result)


@router.delete("/experiments/{run_id}")
async def delete_experiment_endpoint(run_id: str):
    """删除一次实验记录。"""
    from backend.quant.experiment_store import delete_experiment

    ok = await asyncio.to_thread(delete_experiment, run_id)
    return ApiResponse(success=ok, data={"run_id": run_id, "deleted": ok})


@router.post("/experiments/compare")
async def compare_experiments_endpoint(body: ExperimentCompareBody):
    """取若干实验的摘要并排,供横向对比。"""
    from backend.quant.experiment_store import compare_experiments

    rows = await asyncio.to_thread(compare_experiments, body.run_ids)
    return ApiResponse(success=True, data={"items": rows, "count": len(rows)})


@router.post("/tdx/compile")
async def compile_tdx_endpoint(body: TdxCompileRequestBody):
    """编译/校验通达信(TDX)公式(不回测),返回解析结构、买卖信号与错误/告警。

    用于前端「编译」按钮即时反馈语法是否合法、识别出哪些买卖信号。要回测时,用
    `/api/quant/backtest` 传 strategy_id="tdx", params={"formula": ...}。
    """
    from backend.quant.tdx_compiler import compile_formula

    compiled = compile_formula(body.formula)
    return ApiResponse(
        success=compiled.ok,
        data=compiled.to_dict(),
        message=("公式编译通过。" if compiled.ok else "公式有错误,请查看 errors。"),
    )


@router.post("/live/start")
async def start_live(body: LiveStartBody):
    """启动实盘"""
    return ApiResponse(
        success=False,
        error="本地量化实验室暂未接入实盘执行，只支持历史回测。",
        error_code="LOCAL_LIVE_NOT_IMPLEMENTED",
        data={"strategy_id": body.strategy_id, "symbol": body.symbol},
    )


@router.post("/live/stop")
async def stop_live(body: LiveStopBody):
    """停止实盘"""
    return ApiResponse(
        success=False,
        error="本地量化实验室暂未接入实盘执行，无需停止实盘任务。",
        error_code="LOCAL_LIVE_NOT_IMPLEMENTED",
        data={"run_id": body.run_id},
    )


@router.get("/runs")
async def list_runs():
    """获取运行记录"""
    return ApiResponse(
        success=True,
        data={
            "runs": _local_runs,
            "can_run_backtest": True,
            "local_backtest_available": True,
            "execution_mode": "local",
            "source_status": "local",
            "degraded": False,
        },
    )


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """获取运行详情"""
    result = _local_run_details.get(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"运行记录不存在: {run_id}")
    return ApiResponse(success=True, data=result)
