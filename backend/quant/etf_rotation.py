"""Research-only multi-asset ETF momentum and RSRS rotation backtest.

The native ``BacktestEngine`` is intentionally a single-symbol engine.  This
module keeps portfolio rotation separate instead of overloading that contract:
it consumes aligned daily OHLCV bars for several ETFs, calculates signals only
from data available at a close, and executes the resulting target weights at
the next available open.

It is a clean-room research baseline, not a live-trading system.  The caller
provides a universe and its historical data; point-in-time universe membership,
ETF premiums/discounts, suspensions, corporate actions, price limits, and
settlement differences are all surfaced as assumptions rather than guessed.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable

from .metrics import build_performance_summary


STRATEGY_ID = "etf_momentum_rsrs"
_EPSILON = 1e-12


@dataclass(frozen=True)
class RotationConfig:
    """Parameters for a deterministic ETF momentum + RSRS research baseline."""

    momentum_window: int = 63
    ma_window: int = 100
    rsrs_window: int = 18
    rsrs_history: int = 252
    rsrs_entry: float = 0.7
    rsrs_exit: float = -0.7
    rebalance_interval: int = 5
    top_k: int = 2
    commission_rate: float = 0.00025
    commission_min: float = 5.0
    slippage_rate: float = 0.0005
    lot_size: int = 100
    require_positive_momentum: bool = True
    require_above_ma: bool = True

    @property
    def warmup_bars(self) -> int:
        return max(self.momentum_window, self.ma_window, self.rsrs_window + self.rsrs_history - 1)


def make_config(params: dict[str, Any] | None = None) -> RotationConfig:
    """Merge request parameters with conservative defaults and validate them."""
    values = {**RotationConfig().__dict__, **(params or {})}
    int_fields = (
        "momentum_window",
        "ma_window",
        "rsrs_window",
        "rsrs_history",
        "rebalance_interval",
        "top_k",
        "lot_size",
    )
    float_fields = ("rsrs_entry", "rsrs_exit", "commission_rate", "commission_min", "slippage_rate")
    for field in int_fields:
        values[field] = int(values[field])
    for field in float_fields:
        values[field] = float(values[field])
    values["require_positive_momentum"] = bool(values["require_positive_momentum"])
    values["require_above_ma"] = bool(values["require_above_ma"])
    config = RotationConfig(**values)
    if config.momentum_window < 2 or config.ma_window < 2 or config.rsrs_window < 2 or config.rsrs_history < 2:
        raise ValueError("Momentum, moving-average, and RSRS windows must all be at least 2")
    if config.rebalance_interval < 1 or config.top_k < 1 or config.lot_size < 1:
        raise ValueError("rebalance_interval, top_k, and lot_size must be positive")
    if config.rsrs_exit > config.rsrs_entry:
        raise ValueError("rsrs_exit must not exceed rsrs_entry")
    if config.commission_rate < 0 or config.commission_min < 0 or config.slippage_rate < 0:
        raise ValueError("Trading costs cannot be negative")
    return config


def _coerce_bar(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        date = str(raw.get("date") or "")[:10]
        open_price = float(raw.get("open") or 0)
        high = float(raw.get("high") or 0)
        low = float(raw.get("low") or 0)
        close = float(raw.get("close") or 0)
    except (AttributeError, TypeError, ValueError):
        return None
    if not date or min(open_price, high, low, close) <= 0:
        return None
    return {
        "date": date,
        "open": open_price,
        "high": max(high, open_price, close),
        "low": min(low, open_price, close),
        "close": close,
        "volume": float(raw.get("volume") or 0),
    }


def align_portfolio_bars(
    bars_by_symbol: dict[str, list[dict[str, Any]]],
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    """Return the date intersection and normalized bars for every non-empty symbol.

    Using the intersection avoids silently forward-filling a missing asset into
    a ranking calculation.  A caller can therefore see exactly how many common
    observations its supplied universe supports.
    """
    per_symbol: dict[str, dict[str, dict[str, Any]]] = {}
    for raw_symbol, raw_bars in sorted((bars_by_symbol or {}).items()):
        symbol = str(raw_symbol).strip()
        if not symbol:
            continue
        dated: dict[str, dict[str, Any]] = {}
        for raw in raw_bars or []:
            bar = _coerce_bar(raw)
            if bar:
                dated[bar["date"]] = bar
        if dated:
            per_symbol[symbol] = dated
    if len(per_symbol) < 2:
        return [], {}
    common = set.intersection(*(set(rows) for rows in per_symbol.values()))
    dates = sorted(common)
    return dates, {symbol: [rows[date] for date in dates] for symbol, rows in per_symbol.items()}


def linear_regression_slope_r2(x_values: Iterable[float], y_values: Iterable[float]) -> tuple[float, float] | None:
    """Ordinary least-squares slope and R-squared without optional dependencies."""
    xs = [float(value) for value in x_values]
    ys = [float(value) for value in y_values]
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    denominator = sum((value - mean_x) ** 2 for value in xs)
    if denominator <= _EPSILON:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    intercept = mean_y - slope * mean_x
    ss_total = sum((value - mean_y) ** 2 for value in ys)
    if ss_total <= _EPSILON:
        return slope, 0.0
    ss_residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys))
    return slope, max(0.0, min(1.0, 1.0 - ss_residual / ss_total))


def momentum_score(closes: list[float], index: int, window: int) -> float | None:
    """Annualized log-price regression momentum weighted by its R-squared."""
    start = index - window + 1
    if start < 0:
        return None
    sample = closes[start : index + 1]
    if len(sample) != window or any(value <= 0 for value in sample):
        return None
    regression = linear_regression_slope_r2(range(window), (math.log(value) for value in sample))
    if regression is None:
        return None
    slope, r_squared = regression
    # Limit the exponent to avoid an invalid value from malformed input while
    # preserving the order of practical daily momentum scores.
    annualized = math.exp(max(-20.0, min(20.0, slope * 252.0))) - 1.0
    return annualized * r_squared


def rsrs_score(highs: list[float], lows: list[float], index: int, window: int, history: int) -> float | None:
    """Calculate standard RSRS: z-score(beta) multiplied by current R-squared."""
    if len(highs) != len(lows) or index < history + window - 2:
        return None
    betas: list[float] = []
    current_r_squared = 0.0
    for end in range(index - history + 1, index + 1):
        start = end - window + 1
        regression = linear_regression_slope_r2(lows[start : end + 1], highs[start : end + 1])
        if regression is None:
            return None
        beta, r_squared = regression
        betas.append(beta)
        current_r_squared = r_squared
    if len(betas) < 2:
        return None
    std = statistics.pstdev(betas)
    if std <= _EPSILON:
        return None
    return ((betas[-1] - statistics.fmean(betas)) / std) * max(0.0, current_r_squared)


def _sma(values: list[float], index: int, window: int) -> float | None:
    start = index - window + 1
    if start < 0:
        return None
    sample = values[start : index + 1]
    return sum(sample) / len(sample) if sample else None


def _scores_for_date(
    aligned: dict[str, list[dict[str, Any]]],
    index: int,
    config: RotationConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in sorted(aligned):
        bars = aligned[symbol]
        closes = [bar["close"] for bar in bars]
        highs = [bar["high"] for bar in bars]
        lows = [bar["low"] for bar in bars]
        momentum = momentum_score(closes, index, config.momentum_window)
        rsrs = rsrs_score(highs, lows, index, config.rsrs_window, config.rsrs_history)
        ma = _sma(closes, index, config.ma_window)
        positive = momentum is not None and momentum > 0
        above_ma = ma is not None and closes[index] > ma
        eligible = (
            momentum is not None
            and rsrs is not None
            and (not config.require_positive_momentum or positive)
            and (not config.require_above_ma or above_ma)
            and rsrs >= config.rsrs_entry
        )
        rows.append(
            {
                "symbol": symbol,
                "momentum": round(momentum, 8) if momentum is not None else None,
                "rsrs": round(rsrs, 8) if rsrs is not None else None,
                "eligible": eligible,
            }
        )
    return rows


def _target_symbols(
    scores: list[dict[str, Any]],
    holdings: dict[str, dict[str, float]],
    config: RotationConfig,
    *,
    rebalance: bool,
) -> tuple[list[str], str]:
    held = set(holdings)
    risk_exits = {
        str(row["symbol"])
        for row in scores
        if row.get("symbol") in held and row.get("rsrs") is not None and float(row["rsrs"]) <= config.rsrs_exit
    }
    if rebalance:
        ranked = sorted(
            (row for row in scores if row.get("eligible")),
            key=lambda row: (
                -float(row["momentum"]) if row.get("momentum") is not None else float("inf"),
                str(row["symbol"]),
            ),
        )
        return [str(row["symbol"]) for row in ranked[: config.top_k]], "scheduled_rebalance"
    if risk_exits:
        return sorted(held - risk_exits), "rsrs_risk_exit"
    return sorted(held), "hold"


def _trade_fee(turnover: float, config: RotationConfig) -> float:
    return max(config.commission_min, turnover * config.commission_rate) if turnover > 0 else 0.0


def _fee_aware_equal_weight_targets(
    *,
    holdings: dict[str, dict[str, float]],
    cash: float,
    bars_at_open: dict[str, dict[str, Any]],
    target_symbols: set[str],
    config: RotationConfig,
) -> dict[str, int]:
    """Return lot-rounded equal-value targets whose aggregate trades can settle."""
    if not target_symbols:
        return {}
    equity_at_open = cash + sum(
        position["shares"] * bars_at_open[symbol]["open"] for symbol, position in holdings.items()
    )
    max_target_value = equity_at_open / len(target_symbols)

    def desired_shares(target_value: float) -> dict[str, int]:
        return {
            symbol: int(target_value / bars_at_open[symbol]["open"] / config.lot_size) * config.lot_size
            for symbol in sorted(target_symbols)
        }

    def can_settle(desired: dict[str, int]) -> bool:
        available_cash = cash
        for symbol in sorted(holdings):
            position = holdings[symbol]
            current = int(position["shares"])
            to_sell = max(0, current - desired.get(symbol, 0))
            if not to_sell:
                continue
            fill_price = bars_at_open[symbol]["open"] * (1.0 - config.slippage_rate)
            turnover = to_sell * fill_price
            available_cash += turnover - _trade_fee(turnover, config)

        required_cash = 0.0
        for symbol in sorted(target_symbols):
            current = int(holdings.get(symbol, {}).get("shares", 0))
            to_buy = max(0, desired[symbol] - current)
            if not to_buy:
                continue
            fill_price = bars_at_open[symbol]["open"] * (1.0 + config.slippage_rate)
            turnover = to_buy * fill_price
            required_cash += turnover + _trade_fee(turnover, config)
        return required_cash <= available_cash + _EPSILON

    lower, upper = 0.0, max_target_value
    best = desired_shares(0.0)
    # The target is monotonic in the common value. Bisection avoids letting
    # symbol order decide which leg absorbs fees after lot rounding.
    for _ in range(48):
        midpoint = (lower + upper) / 2.0
        candidate = desired_shares(midpoint)
        if can_settle(candidate):
            best = candidate
            lower = midpoint
        else:
            upper = midpoint
    return best


def _execute_targets(
    *,
    holdings: dict[str, dict[str, float]],
    cash: float,
    bars_at_open: dict[str, dict[str, Any]],
    target_symbols: list[str],
    config: RotationConfig,
    execution_date: str,
    signal_date: str,
    reason: str,
    trades: list[dict[str, Any]],
) -> float:
    """Sell first, then rebalance target assets to equal opening-value weights."""
    target_set = set(target_symbols)
    desired = _fee_aware_equal_weight_targets(
        holdings=holdings,
        cash=cash,
        bars_at_open=bars_at_open,
        target_symbols=target_set,
        config=config,
    )

    # Sells are executed before buys so released cash can fund the new selection.
    for symbol in sorted(list(holdings)):
        current = int(holdings[symbol]["shares"])
        target = desired.get(symbol, 0)
        to_sell = max(0, current - target)
        if not to_sell:
            continue
        fill_price = bars_at_open[symbol]["open"] * (1.0 - config.slippage_rate)
        turnover = to_sell * fill_price
        fee = _trade_fee(turnover, config)
        basis_per_share = holdings[symbol]["cost_basis"]
        proceeds = turnover - fee
        cash += proceeds
        holdings[symbol]["shares"] = current - to_sell
        trades.append(
            {
                "date": execution_date,
                "signal_date": signal_date,
                "symbol": symbol,
                "side": "sell",
                "shares": to_sell,
                "price": round(fill_price, 6),
                "fee": round(fee, 6),
                "reason": reason,
                "pnl": round(proceeds - to_sell * basis_per_share, 6),
            }
        )
        if holdings[symbol]["shares"] <= 0:
            holdings.pop(symbol, None)

    for symbol in sorted(target_set):
        current = int(holdings.get(symbol, {}).get("shares", 0))
        wanted = max(0, desired[symbol] - current)
        if not wanted:
            continue
        to_buy = wanted
        fill_price = bars_at_open[symbol]["open"] * (1.0 + config.slippage_rate)
        turnover = to_buy * fill_price
        fee = _trade_fee(turnover, config)
        total_cost = turnover + fee
        if total_cost > cash + _EPSILON:
            raise RuntimeError("Fee-aware target planner produced an unfundable buy order")
        existing_cost = holdings.get(symbol, {}).get("cost_basis", 0.0) * current
        cash -= total_cost
        holdings[symbol] = {
            "shares": current + to_buy,
            "cost_basis": (existing_cost + total_cost) / (current + to_buy),
        }
        trades.append(
            {
                "date": execution_date,
                "signal_date": signal_date,
                "symbol": symbol,
                "side": "buy",
                "shares": to_buy,
                "price": round(fill_price, 6),
                "fee": round(fee, 6),
                "reason": reason,
            }
        )
    return cash


def _assumptions(config: RotationConfig, universe: list[str]) -> dict[str, Any]:
    return {
        "strategy": STRATEGY_ID,
        "signal_timing": "Uses close[t] data only; targets execute at open[t+1].",
        "momentum": {"window": config.momentum_window, "method": "annualized_log_regression_times_r_squared"},
        "rsrs": {
            "window": config.rsrs_window,
            "history": config.rsrs_history,
            "entry": config.rsrs_entry,
            "exit": config.rsrs_exit,
        },
        "rebalance_interval_days": config.rebalance_interval,
        "top_k": config.top_k,
        "commission_rate": config.commission_rate,
        "commission_min": config.commission_min,
        "stamp_duty_rate": 0.0,
        "slippage_rate": config.slippage_rate,
        "lot_size": config.lot_size,
        "price_limit_filter": False,
        "settlement": "Not modeled; this daily research engine does not fill a same-bar signal.",
        "universe": universe,
        "universe_bias": "Caller-provided ETF universe is not point-in-time screened.",
        "data_alignment": "Only dates available for every supplied symbol are used; no forward-filled ranking inputs.",
        "unmodeled": ["suspensions", "ETF premium/discount", "corporate actions", "price limits", "market impact"],
    }


def _empty_result(
    *,
    config: RotationConfig,
    universe: list[str],
    initial_capital: float,
    note: str,
) -> dict[str, Any]:
    return {
        "status": "insufficient_data",
        "strategy_name": STRATEGY_ID,
        "universe": universe,
        "dates": [],
        "equity_curve": [initial_capital],
        "trades": [],
        "decisions": [],
        "performance": build_performance_summary([initial_capital], [], initial_capital, 0),
        "assumptions": _assumptions(config, universe),
        "note": note,
        "disclaimer": "Historical portfolio research only; it does not predict returns or constitute investment advice.",
    }


def run_etf_rotation_backtest(
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    initial_capital: float = 1_000_000.0,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a deterministic, next-open ETF momentum + RSRS rotation backtest."""
    if initial_capital <= 0:
        raise ValueError("initial_capital must be positive")
    config = make_config(params)
    dates, aligned = align_portfolio_bars(bars_by_symbol)
    universe = sorted(aligned)
    if len(universe) < 2:
        return _empty_result(
            config=config,
            universe=universe,
            initial_capital=initial_capital,
            note="At least two symbols with aligned OHLCV history are required.",
        )
    if len(dates) < config.warmup_bars + 2:
        return _empty_result(
            config=config,
            universe=universe,
            initial_capital=initial_capital,
            note=(
                f"Need at least {config.warmup_bars + 2} aligned bars for the configured momentum and RSRS windows; "
                f"received {len(dates)}."
            ),
        )

    cash = float(initial_capital)
    holdings: dict[str, dict[str, float]] = {}
    trades: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    equity_curve = [float(initial_capital)]
    pending: dict[str, Any] | None = None

    for index, date in enumerate(dates):
        bars_at_date = {symbol: aligned[symbol][index] for symbol in universe}
        if pending:
            cash = _execute_targets(
                holdings=holdings,
                cash=cash,
                bars_at_open=bars_at_date,
                target_symbols=pending["target_symbols"],
                config=config,
                execution_date=date,
                signal_date=pending["signal_date"],
                reason=pending["reason"],
                trades=trades,
            )
            pending = None

        if index >= config.warmup_bars - 1:
            scheduled = (index - (config.warmup_bars - 1)) % config.rebalance_interval == 0
            scores = _scores_for_date(aligned, index, config)
            target_symbols, reason = _target_symbols(scores, holdings, config, rebalance=scheduled)
            # A close on the final supplied bar has no next-open execution. Do
            # not report it as an actionable rebalance decision.
            if (scheduled or reason == "rsrs_risk_exit") and index + 1 < len(dates):
                pending = {
                    "target_symbols": target_symbols,
                    "signal_date": date,
                    "reason": reason,
                }
                decisions.append(
                    {
                        "signal_date": date,
                        "execution_date": dates[index + 1],
                        "reason": reason,
                        "target_symbols": target_symbols,
                        "scores": scores,
                    }
                )

        equity = cash + sum(position["shares"] * bars_at_date[symbol]["close"] for symbol, position in holdings.items())
        equity_curve.append(round(equity, 8))

    closed_trades = [trade for trade in trades if trade.get("side") == "sell"]
    performance = build_performance_summary(equity_curve, closed_trades, initial_capital, len(dates))
    performance["total_orders"] = len(trades)
    performance["total_round_trips"] = len(closed_trades)
    return {
        "status": "ok",
        "strategy_name": STRATEGY_ID,
        "universe": universe,
        "dates": dates,
        "equity_curve": equity_curve,
        "trades": trades,
        "decisions": decisions,
        "performance": performance,
        "assumptions": _assumptions(config, universe),
        "note": "Signals use only closing data available on the decision date and execute at the next open.",
        "disclaimer": "Historical portfolio research only; it does not predict returns or constitute investment advice.",
    }


def _rotation_windows(
    n_bars: int, warmup: int, requested: int, scheme: str
) -> tuple[list[tuple[int, int, int, int]], int]:
    """Build chronological IS/OOS windows whose first IS segment can warm up RSRS."""
    requested = max(1, min(12, int(requested)))
    mode = scheme if scheme in {"anchored", "rolling"} else "anchored"
    minimum_fold = max(20, warmup + 1)
    for splits in range(requested, 0, -1):
        fold = n_bars // (splits + 1)
        if fold < minimum_fold:
            continue
        windows: list[tuple[int, int, int, int]] = []
        for index in range(splits):
            oos_start = (index + 1) * fold
            oos_end = (index + 2) * fold if index < splits - 1 else n_bars
            is_start = index * fold if mode == "rolling" else 0
            windows.append((is_start, oos_start, oos_start, oos_end))
        return windows, splits
    return [], 0


def _curve_performance(
    curve: list[float],
    trades: list[dict[str, Any]],
    days: int,
) -> dict[str, Any]:
    if not curve:
        return build_performance_summary([], [], 0.0, 0)
    closed = [trade for trade in trades if trade.get("side") == "sell"]
    return build_performance_summary(curve, closed, curve[0], days)


def _aggregate_walk_forward(windows: list[dict[str, Any]]) -> dict[str, Any]:
    if not windows:
        return {
            "windows_evaluated": 0,
            "mean_oos_return": 0.0,
            "median_oos_return": 0.0,
            "std_oos_return": 0.0,
            "best_oos_return": 0.0,
            "worst_oos_return": 0.0,
            "pct_profitable_windows": 0.0,
            "mean_wfe": 0.0,
            "consistency_score": 0.0,
            "robustness": "insufficient_data",
        }
    returns = [float(window["oos_return"]) for window in windows]
    profitable = sum(1 for value in returns if value > 0)
    std = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    pct = profitable / len(returns) * 100.0
    mean_return = statistics.fmean(returns)
    consistency = max(0.0, min(100.0, pct * 0.7 + (30.0 if mean_return > 0 else 0.0) - min(20.0, std)))
    if pct >= 70 and mean_return > 0:
        robustness = "historically_consistent"
    elif mean_return > 0:
        robustness = "mixed"
    else:
        robustness = "weak"
    return {
        "windows_evaluated": len(windows),
        "mean_oos_return": round(mean_return, 4),
        "median_oos_return": round(statistics.median(returns), 4),
        "std_oos_return": round(std, 4),
        "best_oos_return": round(max(returns), 4),
        "worst_oos_return": round(min(returns), 4),
        "pct_profitable_windows": round(pct, 2),
        "mean_wfe": round(statistics.fmean(float(window["wfe"]) for window in windows), 4),
        "consistency_score": round(consistency, 2),
        "robustness": robustness,
    }


def run_etf_rotation_walk_forward(
    bars_by_symbol: dict[str, list[dict[str, Any]]],
    *,
    initial_capital: float = 1_000_000.0,
    params: dict[str, Any] | None = None,
    n_splits: int = 3,
    scheme: str = "anchored",
) -> dict[str, Any]:
    """Assess ETF-rotation temporal robustness using date-based IS/OOS windows."""
    config = make_config(params)
    dates, aligned = align_portfolio_bars(bars_by_symbol)
    universe = sorted(aligned)
    effective_scheme = scheme if scheme in {"anchored", "rolling"} else "anchored"
    full_period = run_etf_rotation_backtest(aligned, initial_capital=initial_capital, params=params)
    windows_index, effective_splits = _rotation_windows(len(dates), config.warmup_bars, n_splits, effective_scheme)
    if full_period.get("status") != "ok" or not windows_index:
        return {
            "status": "insufficient_data",
            "strategy_name": STRATEGY_ID,
            "universe": universe,
            "scheme": effective_scheme,
            "requested_windows": n_splits,
            "n_windows": 0,
            "windows": [],
            "aggregate": _aggregate_walk_forward([]),
            "full_period": full_period.get("performance", {}),
            "assumptions": full_period.get("assumptions", _assumptions(config, universe)),
            "note": (
                "Insufficient aligned data for walk-forward windows with the current momentum and RSRS warm-up. "
                "Use a longer history or explicitly reduce research windows."
            ),
            "disclaimer": "Out-of-sample results describe historical robustness only and are not investment advice.",
        }

    windows: list[dict[str, Any]] = []
    for number, (is_start, is_end, oos_start, oos_end) in enumerate(windows_index, start=1):
        context_start = 0 if effective_scheme == "anchored" else max(0, is_start - config.warmup_bars)
        sliced = {symbol: rows[context_start:oos_end] for symbol, rows in aligned.items()}
        run = run_etf_rotation_backtest(sliced, initial_capital=initial_capital, params=params)
        if run.get("status") != "ok":
            continue
        offset = context_start
        equity = run["equity_curve"]
        is_curve = equity[is_start - offset : is_end - offset + 1]
        oos_curve = equity[oos_start - offset : oos_end - offset + 1]
        is_dates = dates[is_start:is_end]
        oos_dates = dates[oos_start:oos_end]
        is_trades = [trade for trade in run["trades"] if trade.get("date") in set(is_dates)]
        oos_trades = [trade for trade in run["trades"] if trade.get("date") in set(oos_dates)]
        is_performance = _curve_performance(is_curve, is_trades, len(is_dates))
        oos_performance = _curve_performance(oos_curve, oos_trades, len(oos_dates))
        is_annualized = float(is_performance.get("annualized_return") or 0.0)
        oos_annualized = float(oos_performance.get("annualized_return") or 0.0)
        wfe = oos_annualized / is_annualized if abs(is_annualized) > _EPSILON else 0.0
        windows.append(
            {
                "index": number,
                "scheme": effective_scheme,
                "is_start_date": dates[is_start],
                "is_end_date": dates[is_end - 1],
                "oos_start_date": dates[oos_start],
                "oos_end_date": dates[oos_end - 1],
                "is_bars": len(is_dates),
                "oos_bars": len(oos_dates),
                "is_return": is_performance.get("total_return", 0.0),
                "oos_return": oos_performance.get("total_return", 0.0),
                "is_annualized": is_annualized,
                "oos_annualized": oos_annualized,
                "oos_sharpe": oos_performance.get("sharpe_ratio", 0.0),
                "oos_max_drawdown": oos_performance.get("max_drawdown", 0.0),
                "oos_trades": oos_performance.get("total_trades", 0),
                "wfe": round(max(-9.99, min(9.99, wfe)), 4),
                "oos_profitable": bool(float(oos_performance.get("total_return") or 0.0) > 0),
                "is_performance": is_performance,
                "oos_performance": oos_performance,
            }
        )

    status = "ok" if len(windows) >= 2 else "degraded"
    return {
        "status": status,
        "strategy_name": STRATEGY_ID,
        "universe": universe,
        "scheme": effective_scheme,
        "requested_windows": n_splits,
        "n_windows": len(windows),
        "effective_splits": effective_splits,
        "windows": windows,
        "aggregate": _aggregate_walk_forward(windows),
        "full_period": full_period.get("performance", {}),
        "assumptions": full_period.get("assumptions", _assumptions(config, universe)),
        "note": "Each window uses only its historical prefix for indicators and executes targets at the next open.",
        "disclaimer": "Out-of-sample results describe historical robustness only and are not investment advice.",
    }
