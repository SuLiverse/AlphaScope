"""Walk-forward analysis — rolling / anchored out-of-sample backtest robustness.

Splits the full bar series into sequential windows, each with an in-sample (IS)
and out-of-sample (OOS) segment, and runs the *same* strategy on each. Because
AlphaScope strategies use fixed (non-optimised) parameters, this measures
**temporal robustness**: does the strategy's edge persist out-of-sample and
across regimes, or is the headline full-period return concentrated in one lucky
window (a classic overfitting / curve-fit tell)?

Honest by construction:

* One engine run per window over the *contiguous* IS+OOS slice, so indicators
  get proper warm-up — there is no artificial signal gap at the OOS boundary.
* OOS metrics are re-based to the equity at the IS/OOS split, so OOS return is
  measured purely on out-of-sample bars.
* Failure-safe: too little data degrades to a clearly-flagged neutral report,
  never raises.

Compliance: backtest robustness is a *description of historical behaviour*, not
a prediction or a recommendation (不预测 / 不荐股 / 不承诺收益). Labels are framed
accordingly ("历史样本外…"), and the standard backtest≠未来 caveat is attached.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date as _calendar_date
from typing import Any, Callable, Union

from .metrics import build_performance_summary
from .strategies import BaseStrategy, StrategyRegistry


def _calendar_span(bars: list[dict]) -> int:
    """首末 bar 之间的自然日天数(年化基准, 与 engine 口径一致); 非 ISO 日期回退为 bar 数。"""
    if len(bars) < 2:
        return len(bars)
    try:
        first = _calendar_date.fromisoformat(str(bars[0].get("date", ""))[:10])
        last = _calendar_date.fromisoformat(str(bars[-1].get("date", ""))[:10])
        return max((last - first).days, 1)
    except ValueError:
        return len(bars)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Each fold must hold at least this many bars, otherwise indicators (up to MA60
# in some strategies) and the metrics would be meaningless. Drives both the
# auto-reduction of the requested window count and the insufficient-data guard.
_MIN_FOLD_BARS = 20
_MIN_SPLITS = 2
_MAX_SPLITS = 12

OK = "ok"
DEGRADED = "degraded"
INSUFFICIENT = "insufficient"

# Strategy can be passed by registry name (+params) or as a ready instance.
StrategyArg = Union[str, BaseStrategy]


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class WindowResult:
    """One IS/OOS window's outcome."""

    index: int
    scheme: str
    is_start_date: str
    is_end_date: str
    oos_start_date: str
    oos_end_date: str
    is_bars: int
    oos_bars: int
    is_return: float  # % total return over IS
    oos_return: float  # % total return over OOS (re-based at the split)
    is_annualized: float  # %
    oos_annualized: float  # %
    oos_sharpe: float
    oos_max_drawdown: float  # %
    oos_win_rate: float  # %
    oos_trades: int
    wfe: float  # walk-forward efficiency = OOS annualised / IS annualised
    oos_profitable: bool
    is_performance: dict[str, Any] = field(default_factory=dict)
    oos_performance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "scheme": self.scheme,
            "is_start_date": self.is_start_date,
            "is_end_date": self.is_end_date,
            "oos_start_date": self.oos_start_date,
            "oos_end_date": self.oos_end_date,
            "is_bars": self.is_bars,
            "oos_bars": self.oos_bars,
            "is_return": self.is_return,
            "oos_return": self.oos_return,
            "is_annualized": self.is_annualized,
            "oos_annualized": self.oos_annualized,
            "oos_sharpe": self.oos_sharpe,
            "oos_max_drawdown": self.oos_max_drawdown,
            "oos_win_rate": self.oos_win_rate,
            "oos_trades": self.oos_trades,
            "wfe": self.wfe,
            "oos_profitable": self.oos_profitable,
            "is_performance": self.is_performance,
            "oos_performance": self.oos_performance,
        }


@dataclass
class WalkForwardReport:
    """Aggregate walk-forward outcome across all windows."""

    symbol: str
    strategy_name: str
    scheme: str
    n_windows: int
    requested_windows: int
    status: str  # ok | degraded | insufficient
    note: str
    windows: list[WindowResult]
    aggregate: dict[str, Any]
    full_period: dict[str, Any]
    assumptions: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy_name": self.strategy_name,
            "scheme": self.scheme,
            "n_windows": self.n_windows,
            "requested_windows": self.requested_windows,
            "status": self.status,
            "note": self.note,
            "windows": [w.to_dict() for w in self.windows],
            "aggregate": self.aggregate,
            "full_period": self.full_period,
            "assumptions": self.assumptions,
            "disclaimer": (
                "样本外回测仅用于评估策略在不同历史区间的稳健性，不代表未来表现，不构成任何投资建议或收益承诺。"
            ),
        }


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _strategy_factory(strategy: StrategyArg, params: dict[str, Any] | None) -> Callable[[], BaseStrategy | None]:
    """Return a zero-arg factory producing a *fresh* strategy per window.

    A fresh instance avoids any state leaking across windows. Accepts either a
    registry name (resolved + params applied) or an existing instance (re-created
    from its own type/params so each window is independent).
    """
    if isinstance(strategy, str):
        name = strategy
        return lambda: StrategyRegistry.create(name, params)
    inst_params = {**getattr(strategy, "params", {}), **(params or {})}
    cls = type(strategy)
    return lambda: cls(inst_params)


def _sort_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Defensive ascending sort by date (the engine assumes chronological bars)."""
    return sorted((dict(b) for b in bars), key=lambda b: str(b.get("date", "")))


def _make_windows(n_bars: int, n_splits: int, scheme: str) -> tuple[list[tuple[int, int, int, int]], int]:
    """Compute (is_start, is_end, oos_start, oos_end) index tuples.

    The series is divided into ``n_splits + 1`` equal folds; window ``w`` tests
    fold ``w+1`` out-of-sample. ``anchored`` grows IS from bar 0; ``rolling`` uses
    a fixed one-fold IS that slides forward. If folds would be smaller than
    ``_MIN_FOLD_BARS`` the split count is auto-reduced to fit.
    """
    fold = n_bars // (n_splits + 1)
    if fold < _MIN_FOLD_BARS:
        n_splits = max(1, n_bars // _MIN_FOLD_BARS - 1)
        fold = n_bars // (n_splits + 1) if n_splits >= 1 else 0
    windows: list[tuple[int, int, int, int]] = []
    if fold < _MIN_FOLD_BARS or n_splits < 1:
        return windows, 0
    for w in range(n_splits):
        oos_start = (w + 1) * fold
        oos_end = (w + 2) * fold if w < n_splits - 1 else n_bars
        is_start = (w * fold) if scheme == "rolling" else 0
        is_end = oos_start
        windows.append((is_start, is_end, oos_start, oos_end))
    return windows, n_splits


def _clamp_wfe(value: float) -> float:
    """Keep walk-forward efficiency in a display-sane band without losing sign."""
    return max(-9.99, min(9.99, value))


def _run_segment_backtest(
    factory: Callable[[], BaseStrategy | None],
    bars: list[dict[str, Any]],
    symbol: str,
    initial_capital: float,
) -> tuple[list[float], list[str], list[dict[str, Any]], dict[str, Any]]:
    """Run one engine pass over a bar slice; return (equity, dates, trades, assumptions)."""
    from .engine import BacktestEngine

    strategy = factory()
    if strategy is None:
        return [initial_capital], [], [], {}
    engine = BacktestEngine(initial_capital=initial_capital)
    # Copy bars so the engine's ``setdefault('symbol', …)`` never mutates shared dicts.
    result = engine.run(strategy, [dict(b) for b in bars], symbol)
    return (
        result.equity_curve,
        result.dates,
        result.trades,
        getattr(result, "assumptions", {}) or {},
    )


def _build_window(
    index: int,
    scheme: str,
    factory: Callable[[], BaseStrategy | None],
    bars: list[dict[str, Any]],
    symbol: str,
    is_start: int,
    is_end: int,
    oos_start: int,
    oos_end: int,
    initial_capital: float,
) -> WindowResult | None:
    """Backtest one contiguous IS+OOS slice and split the result at the boundary."""
    slice_bars = bars[is_start:oos_end]
    n_is = is_end - is_start
    n_oos = oos_end - oos_start
    if n_is < 1 or n_oos < 1:
        return None

    equity, dates, trades, _assump = _run_segment_backtest(factory, slice_bars, symbol, initial_capital)
    # The engine seeds equity_history with the initial capital and then appends
    # one point per bar, so its length is len(bars) + 1: index 0 is pre-trading
    # capital, index k is equity *after* bar k-1. The IS/OOS split therefore sits
    # at equity index ``n_is`` (equity entering the first OOS bar).
    if len(equity) != len(slice_bars) + 1 or len(equity) < 3:
        return None

    is_equity = equity[: n_is + 1]  # seed + n_is points
    oos_open_equity = equity[n_is]  # capital entering OOS
    oos_equity = equity[n_is:]  # opening capital + n_oos points
    if oos_open_equity <= 0 or len(oos_equity) < 2:
        return None

    oos_start_date = str(bars[oos_start].get("date", ""))
    is_trades = [t for t in trades if str(t.get("timestamp", "")) < oos_start_date]
    oos_trades = [t for t in trades if str(t.get("timestamp", "")) >= oos_start_date]

    is_perf = build_performance_summary(
        equity_curve=is_equity,
        trades=is_trades,
        initial_capital=initial_capital,
        days=n_is,
        calendar_days=_calendar_span(slice_bars[:n_is]),
    )
    oos_perf = build_performance_summary(
        equity_curve=oos_equity,
        trades=oos_trades,
        initial_capital=oos_open_equity,
        days=n_oos,
        calendar_days=_calendar_span(slice_bars[oos_start:oos_end]),
    )

    is_ann = float(is_perf.get("annualized_return", 0.0))
    oos_ann = float(oos_perf.get("annualized_return", 0.0))
    if is_ann > 0:
        wfe = _clamp_wfe(oos_ann / is_ann)
    else:
        # IS itself unprofitable → WFE undefined; report 0 and let aggregate skip it.
        wfe = 0.0

    return WindowResult(
        index=index,
        scheme=scheme,
        is_start_date=str(bars[is_start].get("date", "")),
        is_end_date=str(bars[is_end - 1].get("date", "")),
        oos_start_date=oos_start_date,
        oos_end_date=str(bars[oos_end - 1].get("date", "")),
        is_bars=n_is,
        oos_bars=n_oos,
        is_return=float(is_perf.get("total_return", 0.0)),
        oos_return=float(oos_perf.get("total_return", 0.0)),
        is_annualized=round(is_ann, 2),
        oos_annualized=round(oos_ann, 2),
        oos_sharpe=float(oos_perf.get("sharpe_ratio", 0.0)),
        oos_max_drawdown=float(oos_perf.get("max_drawdown", 0.0)),
        oos_win_rate=float(oos_perf.get("win_rate", 0.0)),
        oos_trades=int(oos_perf.get("total_trades", len(oos_trades))),
        wfe=round(wfe, 2),
        oos_profitable=float(oos_perf.get("total_return", 0.0)) > 0,
        is_performance=is_perf,
        oos_performance=oos_perf,
    )


def _aggregate(windows: list[WindowResult]) -> dict[str, Any]:
    """Roll window outcomes into consistency / robustness summary (descriptive)."""
    if not windows:
        return {
            "windows_evaluated": 0,
            "mean_oos_return": 0.0,
            "median_oos_return": 0.0,
            "std_oos_return": 0.0,
            "best_oos_return": 0.0,
            "worst_oos_return": 0.0,
            "profitable_windows": 0,
            "pct_profitable_windows": 0.0,
            "mean_wfe": 0.0,
            "consistency_score": 0.0,
            "robustness": "数据不足",
        }

    oos_returns = [w.oos_return for w in windows]
    n = len(oos_returns)
    n_profitable = sum(1 for r in oos_returns if r > 0)
    pct_profitable = 100.0 * n_profitable / n
    # WFE only meaningful where IS was profitable (otherwise the ratio is noise).
    wfes = [w.wfe for w in windows if w.is_annualized > 0]
    mean_wfe = sum(wfes) / len(wfes) if wfes else 0.0

    # Consistency: mostly "how often does OOS make money", lightly lifted by how
    # well OOS tracks IS (WFE). Purely a description of historical dispersion.
    wfe_component = max(0.0, min(100.0, mean_wfe * 100.0))
    consistency = 0.7 * pct_profitable + 0.3 * wfe_component

    if consistency >= 70 and pct_profitable >= 60:
        robustness = "稳健（历史样本外表现较一致）"
    elif consistency >= 45:
        robustness = "一般（历史样本外表现分化）"
    else:
        robustness = "脆弱（历史样本外表现不稳定，警惕过拟合）"

    return {
        "windows_evaluated": n,
        "mean_oos_return": round(statistics.fmean(oos_returns), 2),
        "median_oos_return": round(statistics.median(oos_returns), 2),
        "std_oos_return": round(statistics.pstdev(oos_returns), 2) if n > 1 else 0.0,
        "best_oos_return": round(max(oos_returns), 2),
        "worst_oos_return": round(min(oos_returns), 2),
        "profitable_windows": n_profitable,
        "pct_profitable_windows": round(pct_profitable, 1),
        "mean_wfe": round(mean_wfe, 2),
        "consistency_score": round(consistency, 1),
        "robustness": robustness,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_walk_forward(
    strategy: StrategyArg,
    bars: list[dict[str, Any]],
    symbol: str = "",
    n_splits: int = 5,
    scheme: str = "anchored",
    initial_capital: float = 100000.0,
    params: dict[str, Any] | None = None,
) -> WalkForwardReport:
    """Run a walk-forward robustness analysis.

    Args:
        strategy: Registry name (with ``params``) or a ready strategy instance.
        bars: Full OHLCV history (will be defensively sorted ascending by date).
        symbol: Label for the run.
        n_splits: Requested OOS windows (clamped to [2, 12]; auto-reduced if the
            history is too short to keep each fold ≥ 20 bars).
        scheme: ``"anchored"`` (IS grows from bar 0) or ``"rolling"`` (fixed IS).
        initial_capital: Starting cash for every window's engine pass.
        params: Strategy param overrides when ``strategy`` is a name.

    Returns:
        A :class:`WalkForwardReport`. Never raises on data shortfall — returns an
        ``insufficient`` / ``degraded`` report instead.
    """
    requested = n_splits
    scheme = scheme if scheme in ("anchored", "rolling") else "anchored"
    n_splits = max(_MIN_SPLITS, min(_MAX_SPLITS, int(n_splits) if n_splits else _MIN_SPLITS))

    strategy_name = strategy if isinstance(strategy, str) else getattr(strategy, "name", "unknown")
    factory = _strategy_factory(strategy, params)

    clean = _sort_bars(bars or [])
    n_bars = len(clean)

    # Full-period reference run (headline behaviour to compare OOS against).
    full_period: dict[str, Any] = {}
    assumptions: dict[str, Any] = {}
    if n_bars >= 2:
        eq, _d, tr, assumptions = _run_segment_backtest(factory, clean, symbol, initial_capital)
        if len(eq) >= 2:
            full_period = build_performance_summary(
                equity_curve=eq,
                trades=tr,
                initial_capital=initial_capital,
                days=n_bars,
                calendar_days=_calendar_span(clean),
            )

    if n_bars < (_MIN_FOLD_BARS * (_MIN_SPLITS + 1)):
        return WalkForwardReport(
            symbol=symbol,
            strategy_name=strategy_name,
            scheme=scheme,
            n_windows=0,
            requested_windows=requested,
            status=INSUFFICIENT,
            note=(
                f"历史数据不足以做样本外切分：需要至少 "
                f"{_MIN_FOLD_BARS * (_MIN_SPLITS + 1)} 根 K 线（每折≥{_MIN_FOLD_BARS}），"
                f"当前 {n_bars} 根。"
            ),
            windows=[],
            aggregate=_aggregate([]),
            full_period=full_period,
            assumptions=assumptions,
        )

    index_windows, effective_splits = _make_windows(n_bars, n_splits, scheme)
    windows: list[WindowResult] = []
    for idx, (is_s, is_e, oos_s, oos_e) in enumerate(index_windows):
        w = _build_window(
            index=idx,
            scheme=scheme,
            factory=factory,
            bars=clean,
            symbol=symbol,
            is_start=is_s,
            is_end=is_e,
            oos_start=oos_s,
            oos_end=oos_e,
            initial_capital=initial_capital,
        )
        if w is not None:
            windows.append(w)

    status = OK
    note = f"{scheme} 方案，{len(windows)} 个样本外窗口。"
    if effective_splits < n_splits or len(windows) < requested:
        status = DEGRADED
        note = (
            f"{scheme} 方案：历史长度仅支持 {len(windows)} 个样本外窗口"
            f"（请求 {requested} 个，已自动收敛以保证每折≥{_MIN_FOLD_BARS} 根 K 线）。"
        )

    return WalkForwardReport(
        symbol=symbol,
        strategy_name=strategy_name,
        scheme=scheme,
        n_windows=len(windows),
        requested_windows=requested,
        status=status,
        note=note,
        windows=windows,
        aggregate=_aggregate(windows),
        full_period=full_period,
        assumptions=assumptions,
    )
