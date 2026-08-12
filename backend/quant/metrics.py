"""Performance metrics calculator - pure functions, no external dependencies."""

from __future__ import annotations

import math
from typing import Any


def calc_returns(equity_curve: list[float]) -> list[float]:
    """Calculate period-over-period returns from equity curve."""
    if len(equity_curve) < 2:
        return []
    return [(equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1] for i in range(1, len(equity_curve))]


def calc_sharpe(returns: list[float], risk_free_rate: float = 0.03, periods_per_year: int = 252) -> float:
    """Annualized Sharpe ratio."""
    if not returns:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    if len(returns) < 2:
        return 0.0
    variance = sum((r - mean_ret) ** 2 for r in returns) / (len(returns) - 1)
    std_ret = math.sqrt(variance) if variance > 0 else 0.0
    if std_ret == 0:
        return 0.0
    daily_rf = risk_free_rate / periods_per_year
    return (mean_ret - daily_rf) / std_ret * math.sqrt(periods_per_year)


def calc_max_drawdown(equity_curve: list[float]) -> float:
    """Maximum drawdown as a negative fraction (e.g., -0.12 = -12%)."""
    if len(equity_curve) < 2:
        return 0.0
    peak = equity_curve[0]
    max_dd = 0.0
    for val in equity_curve:
        if val > peak:
            peak = val
        dd = (val - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd
    return max_dd


def calc_annualized_return(total_return: float, days: int) -> float:
    """Annualized return from total return and holding days.

    ``days`` is the holding period in **natural (calendar) days**; the caller
    must not feed a trading-day count (≈252/year) into a 365-day exponent.
    """
    if days <= 0:
        return 0.0
    return (1 + total_return) ** (365.0 / days) - 1


def calc_win_rate(trades: list[dict[str, Any]]) -> float:
    """Win rate: fraction of profitable closed trades.

    Engine trade lists contain both entries (``buy``, always ``pnl=0``) and
    exits. Counting entries in the denominator halves the apparent win rate.
    Generic callers without a ``side`` field retain the legacy PnL-list
    behavior.
    """
    if not trades:
        return 0.0
    has_side = any("side" in trade for trade in trades)
    closed = [trade for trade in trades if str(trade.get("side", "")).lower() == "sell"] if has_side else trades
    if not closed:
        return 0.0
    wins = sum(1 for trade in closed if trade.get("pnl", 0) > 0)
    return wins / len(closed)


def calc_profit_factor(trades: list[dict[str, Any]]) -> float:
    """Profit factor: gross profit / gross loss."""
    gross_profit = sum(t["pnl"] for t in trades if t.get("pnl", 0) > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t.get("pnl", 0) < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def calc_total_return(initial_capital: float, final_equity: float) -> float:
    """Total return as a fraction."""
    if initial_capital <= 0:
        return 0.0
    return (final_equity - initial_capital) / initial_capital


def calc_sortino(returns: list[float], risk_free_rate: float = 0.03, periods_per_year: int = 252) -> float:
    """Sortino ratio: like Sharpe but only penalizes downside volatility."""
    if not returns or len(returns) < 2:
        return 0.0
    mean_ret = sum(returns) / len(returns)
    daily_rf = risk_free_rate / periods_per_year
    downside = [min(0, r - daily_rf) ** 2 for r in returns]
    downside_dev = math.sqrt(sum(downside) / len(downside)) if downside else 0.0
    if downside_dev == 0:
        return 0.0
    return (mean_ret - daily_rf) / downside_dev * math.sqrt(periods_per_year)


def calc_calmar(total_return: float, max_drawdown: float, days: int) -> float:
    """Calmar ratio: annualized return / max drawdown."""
    if max_drawdown == 0 or days <= 0:
        return 0.0
    ann_ret = calc_annualized_return(total_return, days)
    return ann_ret / abs(max_drawdown)


# ---------------------------------------------------------------------------
# Benchmark-relative metrics (v1.9.4, compass §7.4-2 统计指标标准化)
# 对标 Qlib 口径: 超额收益 / 信息比率 / beta / alpha。
# 所有函数接受基准净值曲线(如沪深300), 无基准或长度不匹配时优雅降级返回 0,
# 不抛异常 —— 回测不依赖基准数据可得性。
# ---------------------------------------------------------------------------


def calc_beta(strategy_returns: list[float], benchmark_returns: list[float]) -> float:
    """Beta: 策略收益对基准收益的回归斜率。

    beta = Cov(R_p, R_b) / Var(R_b)
    """
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return 0.0
    sp = strategy_returns[-n:]
    bp = benchmark_returns[-n:]
    mean_s = sum(sp) / n
    mean_b = sum(bp) / n
    cov = sum((sp[i] - mean_s) * (bp[i] - mean_b) for i in range(n)) / (n - 1)
    var_b = sum((b - mean_b) ** 2 for b in bp) / (n - 1)
    if var_b == 0:
        return 0.0
    return cov / var_b


def calc_alpha(
    strategy_returns: list[float],
    benchmark_returns: list[float],
    risk_free_rate: float = 0.03,
    periods_per_year: int = 252,
) -> float:
    """Alpha (Jensen's alpha), annualized.

    alpha = R_p_annual - [R_f + beta * (R_b_annual - R_f)]
    """
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return 0.0
    sp = strategy_returns[-n:]
    bp = benchmark_returns[-n:]
    beta = calc_beta(sp, bp)
    ann_p = (sum(sp) / n) * periods_per_year
    ann_b = (sum(bp) / n) * periods_per_year
    return ann_p - (risk_free_rate + beta * (ann_b - risk_free_rate))


def calc_excess_return(strategy_curve: list[float], benchmark_curve: list[float]) -> float:
    """超额收益(累计, 分数): 策略总收益 - 基准总收益。

    无基准或基准退化(非正)时返回 0.0。
    """
    if len(strategy_curve) < 2 or len(benchmark_curve) < 2:
        return 0.0
    if strategy_curve[0] <= 0 or benchmark_curve[0] <= 0:
        return 0.0
    strat_ret = (strategy_curve[-1] - strategy_curve[0]) / strategy_curve[0]
    bench_ret = (benchmark_curve[-1] - benchmark_curve[0]) / benchmark_curve[0]
    return strat_ret - bench_ret


def _round_json_float(value: float, digits: int) -> float | None:
    if not math.isfinite(value):
        return None
    return round(value, digits)


def calc_information_ratio(
    strategy_returns: list[float],
    benchmark_returns: list[float],
    periods_per_year: int = 252,
) -> float:
    """信息比率 (年化): 超额收益均值 / 跟踪误差。

    IR = mean(R_p - R_b) / std(R_p - R_b) * sqrt(periods_per_year)
    """
    n = min(len(strategy_returns), len(benchmark_returns))
    if n < 2:
        return 0.0
    excess = [strategy_returns[-n:][i] - benchmark_returns[-n:][i] for i in range(n)]
    mean_ex = sum(excess) / n
    var_ex = sum((e - mean_ex) ** 2 for e in excess) / (n - 1)
    te = math.sqrt(var_ex) if var_ex > 0 else 0.0
    if te == 0:
        return 0.0
    return (mean_ex / te) * math.sqrt(periods_per_year)


def build_performance_summary(
    equity_curve: list[float],
    trades: list[dict[str, Any]],
    initial_capital: float,
    days: int,
    benchmark_curve: list[float] | None = None,
    benchmark_name: str = "",
    calendar_days: int | None = None,
) -> dict[str, Any]:
    """Build a complete performance summary from equity curve and trades.

    ``days`` is the trading-day (bar) count and feeds the ``trading_days``
    field. ``calendar_days`` is the annualization basis (natural days between
    first and last bar); when provided it drives ``annualized_return`` /
    ``calmar_ratio`` instead of ``days``, so the two bases never mix.
    若提供 benchmark_curve(如沪深300净值), 额外计算超额收益/信息比率/alpha/beta;
    无基准时这些字段为 0/None, 不影响主指标(优雅降级)。
    """
    returns = calc_returns(equity_curve)
    final_equity = equity_curve[-1] if equity_curve else initial_capital
    total_ret = calc_total_return(initial_capital, final_equity)
    max_dd = calc_max_drawdown(equity_curve)
    ann_days = calendar_days if calendar_days is not None else days

    summary = {
        "total_return": _round_json_float(total_ret * 100, 2),
        "annualized_return": _round_json_float(calc_annualized_return(total_ret, ann_days) * 100, 2),
        "max_drawdown": _round_json_float(max_dd * 100, 2),
        "sharpe_ratio": _round_json_float(calc_sharpe(returns), 2),
        "sortino_ratio": _round_json_float(calc_sortino(returns), 2),
        "calmar_ratio": _round_json_float(calc_calmar(total_ret, max_dd, ann_days), 2),
        "win_rate": _round_json_float(calc_win_rate(trades) * 100, 2),
        "profit_factor": _round_json_float(calc_profit_factor(trades), 2),
        "total_trades": len(trades),
        "initial_capital": initial_capital,
        "final_equity": _round_json_float(final_equity, 2),
        # trading_days keeps its meaning: trading-day (bar) count, never
        # conflated with the calendar-days annualization basis.
        "trading_days": days,
    }
    if calendar_days is not None:
        summary["calendar_days"] = calendar_days
    # 选择偏差校正指标(默认 n_trials=1; 扫描/进化侧可再 attach)
    try:
        from backend.quant.metrics_advanced import attach_selection_bias_metrics

        summary = attach_selection_bias_metrics(summary, returns, n_trials=1, sharpe_key="sharpe_ratio")
    except Exception:
        pass

    # 基准相关指标: 无基准或数据不足时优雅降级为 0, 且标记 has_benchmark=False。
    bench_returns = calc_returns(benchmark_curve) if benchmark_curve else []
    has_benchmark = bool(bench_curve_valid(benchmark_curve))
    summary["has_benchmark"] = has_benchmark
    summary["benchmark_name"] = benchmark_name if has_benchmark else ""
    if has_benchmark:
        summary["excess_return"] = _round_json_float(calc_excess_return(equity_curve, benchmark_curve) * 100, 2)
        summary["information_ratio"] = _round_json_float(calc_information_ratio(returns, bench_returns), 2)
        summary["beta"] = _round_json_float(calc_beta(returns, bench_returns), 3)
        summary["alpha"] = _round_json_float(calc_alpha(returns, bench_returns), 3)
    else:
        summary["excess_return"] = 0.0
        summary["information_ratio"] = 0.0
        summary["beta"] = 0.0
        summary["alpha"] = 0.0

    return summary


def bench_curve_valid(benchmark_curve: list[float] | None) -> bool:
    """基准曲线是否可用(非空且首值正)。"""
    if not benchmark_curve or len(benchmark_curve) < 2:
        return False
    return benchmark_curve[0] > 0
