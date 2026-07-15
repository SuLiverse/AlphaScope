"""vectorBT Adapter — 向量化回测引擎 + 参数扫描 (Phase 2 第一个真实 adapter).

vectorBT (Apache-2.0) 是基于 NumPy 的向量化回测库, 强项是**一次跑一整张参数网格**
而不是逐组循环。本 adapter 把它接入 AlphaScope 的 Integration Registry, 补齐原生
引擎(精确但逐 bar 迭代)所不擅长的「快速参数扫描」能力。

设计要点 (延续项目「确定性 · 失败安全 · 可溯源」基线):
- **可选依赖 + 优雅降级**: ``vectorbt`` 用 import-guard 包裹, 没装不影响其余功能
  (healthcheck 报 UNAVAILABLE)。安装后即生效。
- **不触网**: 不内置抓数据; 回测所需的 OHLCV 由调用方通过 ``bars=`` 注入,
  或由上层 DataAdapter 取数后喂入。与 datalake / factor_registry 的注入哲学一致。
- **诚实假设卡 (Backtest Assumption Card, 想法 #4)**: vectorBT 原生不模拟 A 股
  T+1 / 印花税 / 涨跌停过滤; 本 adapter 在 ``BacktestAssumptions`` 里**显式标注
  这些未建模项**, 让「快速但粗糙」的扫描结果不被误读为「可直接实盘」。
- **边界**: ``allow_live_order=False``, 不暴露任何实盘下单能力。

合规: 回测结果是对历史数据的统计描述, 不预测未来、不构成投资建议。
"""

from __future__ import annotations

import math
from typing import Any

# ----- 可选依赖: vectorbt 缺失时优雅降级 -----
try:
    import vectorbt as vbt  # type: ignore[import-untyped]

    _VBT_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    vbt = None  # type: ignore[assignment]
    _VBT_AVAILABLE = False

import pandas as pd

from backend.integrations.base import BacktestEngineAdapter
from backend.integrations.schemas import (
    BacktestAssumptions,
    BacktestMetrics,
    HealthStatus,
    IntegrationHealth,
    IntegrationMetadata,
    IntegrationMode,
    LicenseSafety,
    NormalizedBacktestResult,
)
from backend.integrations.registry import register
from backend.quant.metrics import calc_sharpe

# 本 adapter 当前支持的「可向量化」策略族; 每个都有可扫描的数值参数。
# Phase 2 首批只内置 ma_cross (vectorBT 最经典的演示), 后续按需扩展。
_SUPPORTED_STRATEGIES: tuple[str, ...] = ("ma_cross",)
_DEFAULT_STRATEGY = "ma_cross"
DEFAULT_PERIODS_PER_YEAR = 252
DEFAULT_PARAM_GRID: dict[str, list[int]] = {
    "fast": [3, 5, 10],
    "slow": [10, 20, 30, 60],
}


# ============================================================
# 纯函数 (无需 vectorbt 即可单测)
# ============================================================


def bars_to_close_series(bars: list[dict[str, Any]]) -> "pd.Series":
    """把 OHLCV dict 列表转成 pandas Series (index=date, values=close)。

    纯函数, 失败安全: 空 / 缺字段 → 空 Series (上游据此跳过回测)。
    """
    if not bars:
        return pd.Series([], dtype="float64")
    rows = []
    for b in bars:
        close = b.get("close")
        date = b.get("date") or b.get("datetime") or b.get("time")
        if close is None or date is None:
            continue
        try:
            rows.append((str(date), float(close)))
        except (TypeError, ValueError):
            continue
    if not rows:
        return pd.Series([], dtype="float64")
    s = pd.Series({r[0]: r[1] for r in rows})
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def build_ma_cross_signals(close: "pd.Series", fast: int, slow: int) -> tuple["pd.Series", "pd.Series"]:
    """Generate next-bar execution signals from close-based MA decisions.

    A cross observed at ``close[t]`` is shifted to ``t + 1`` before it reaches
    vectorbt.  Because the portfolio uses close as its order price, execution
    is therefore at the next bar's close rather than the close that generated
    the signal.  This explicit delay removes same-bar look-ahead.
    """
    if len(close) <= slow or fast >= slow or fast <= 0:
        return pd.Series(False, index=close.index), pd.Series(False, index=close.index)
    fast_ma = close.rolling(window=int(fast)).mean()
    slow_ma = close.rolling(window=int(slow)).mean()
    above = fast_ma > slow_ma
    decision_entries = above & ~above.shift(1, fill_value=False)
    decision_exits = ~above & above.shift(1, fill_value=False)
    entries = decision_entries.shift(1, fill_value=False)
    exits = decision_exits.shift(1, fill_value=False)
    return entries.fillna(False).astype(bool), exits.fillna(False).astype(bool)


def parse_param_grid(params: dict[str, Any] | None) -> dict[str, list[Any]]:
    """把 ``{fast: [5,10], slow: [20,30]}`` 形式的网格抽出来。

    - 值是 list/tuple → 当作可扫描维度
    - 值是标量 → 包装成单元素 list
    缺失 / 非法 → 返回空 dict (上游用默认网格)。
    """
    out: dict[str, list[Any]] = {}
    if not isinstance(params, dict):
        return out
    for k, v in params.items():
        if isinstance(v, (list, tuple)):
            out[k] = list(v)
        else:
            out[k] = [v]
    return out


def count_param_trials(param_grid: dict[str, list[Any]] | None = None) -> int:
    """Count valid MA parameter combinations used by ``param_sweep``."""
    grid = parse_param_grid(param_grid) or DEFAULT_PARAM_GRID
    fasts = [int(x) for x in grid.get("fast", [5])]
    slows = [int(x) for x in grid.get("slow", [20])]
    return max(1, sum(1 for fast in fasts for slow in slows if fast < slow))


def equity_curve_returns(equity_curve: list[Any]) -> list[float]:
    """Convert a normalized equity curve into period returns for PSR/DSR."""
    values: list[float] = []
    for point in equity_curve or []:
        value = point.get("value") if isinstance(point, dict) else point
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return [
        (values[index] - values[index - 1]) / values[index - 1] for index in range(1, len(values)) if values[index - 1]
    ]


def annualized_sharpe_from_returns(returns: list[float], periods_per_year: int = DEFAULT_PERIODS_PER_YEAR) -> float:
    """Calculate Sharpe with the same annualization convention used by DSR."""
    periods = int(periods_per_year)
    if periods <= 0:
        raise ValueError("periods_per_year must be positive")
    return calc_sharpe(returns, risk_free_rate=0.0, periods_per_year=periods)


def build_assumptions(
    engine_name: str,
    fees: float,
    freq: str = "1D",
    note: str = "",
    periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
) -> BacktestAssumptions:
    """构造诚实的回测假设卡。

    vectorBT 原生**不**模拟 A 股 T+1 结算、印花税(卖方)、涨跌停过滤、停牌处理。
    本函数把这些未建模项显式标在 note 里, 防止「快速扫描的好结果」被误读为
    「可直接实盘」。这是 Backtest Assumption Card (想法 #4) 的工程落地。
    """
    return BacktestAssumptions(
        engine_name=engine_name,
        commission_rate=fees,
        stamp_duty_rate=None,  # vectorBT 不区分买卖手费用, 不模拟印花税
        slippage_rate=None,  # 由调用方在信号层处理, 引擎本身不强制
        execution_price="信号次一 bar 收盘价 (close[t] 判定, close[t+1] 成交)",
        settlement_rule="信号延迟 1 bar; 未强制 A 股持仓 T+1",
        price_limit_filter=False,  # 不模拟涨跌停
        suspension_handling=None,
        adj_method="后复权 (由数据源决定)",
        future_function_check=True,
        data_source="调用方注入 (bars=)",
        note=(
            f"vectorBT 向量化回测: {freq} 信号延迟至下一 bar 收盘成交, "
            f"Sharpe 按每年 {int(periods_per_year)} 个观测期年化; "
            "未模拟 A 股持仓 T+1 / 印花税 / 涨跌停 / 停牌; "
            "结果偏乐观, 仅适合快速参数扫描初筛, 严肃验证须切回 AlphaScope 原生引擎。" + (f" {note}" if note else "")
        ),
    )


def map_vbt_stats_to_metrics(stats: Any) -> BacktestMetrics:
    """把 vectorbt 的 stats 对象映射到统一 BacktestMetrics (容错)。

    vectorbt 不同版本字段名/单位略有差异; 全部用 getattr + 失败安全,
    缺字段返回 None 而非抛错。
    """

    def _get(*names: str) -> float | None:
        for n in names:
            v = getattr(stats, n, None)
            if v is None and isinstance(stats, dict):
                v = stats.get(n)
            try:
                if v is None:
                    continue
                f = float(v)
                if f == f and f not in (float("inf"), float("-inf")):
                    return f
            except (TypeError, ValueError):
                continue
        return None

    return BacktestMetrics(
        total_return=_get("Total Return [%]", "total_return"),
        annual_return=_get("Annualized Return [%]", "annual_return"),
        sharpe=_get("Sharpe Ratio", "sharpe"),
        sortino=_get("Sortino Ratio", "sortino"),
        calmar=_get("Calmar Ratio", "calmar"),
        max_drawdown=_get("Max Drawdown [%]", "max_drawdown"),
        volatility=_get("Annualized Volatility [%]", "volatility"),
        win_rate=_get("Win Rate [%]", "win_rate"),
        turnover=None,  # vectorbt 口径不同, 留空避免误导
        profit_factor=_get("Profit Factor", "profit_factor"),
    )


# ============================================================
# Adapter
# ============================================================


@register
class VectorbtAdapter(BacktestEngineAdapter):
    """vectorBT 向量化回测引擎 adapter (Phase 2)。

    强项是参数网格扫描; 单次回测也能跑。所需 OHLCV 由调用方注入 (``bars=``),
    本 adapter 不触网、不下单。
    """

    NAME = "vectorbt"
    # CATEGORY 继承自 BacktestEngineAdapter.BACKTEST

    def _metadata(self) -> IntegrationMetadata:
        return IntegrationMetadata(
            name=self.NAME,
            category=self.CATEGORY,
            mode=IntegrationMode.PYTHON_ADAPTER,
            version="0.1.0",
            display_name="vectorBT 向量化回测",
            description=(
                "向量化回测引擎, 强项是参数网格扫描 (一次跑完整张参数表)。"
                "原生不模拟 A 股 T+1/印花税/涨跌停, 适合快速初筛;"
                "严肃验证须切回 AlphaScope 原生引擎。可选依赖, 缺失时降级。"
            ),
            homepage="https://github.com/polakowo/vectorbt",
            package="vectorbt",
            capabilities=[
                {"name": "run_backtest", "description": "单次向量化回测 (ma_cross)"},
                {
                    "name": "param_sweep",
                    "description": "参数网格扫描, 返回按收益排序的结果列表",
                },
            ],
            license_name="Apache-2.0",
            license_safety=LicenseSafety.SAFE,
            code_copy_allowed=True,
            allow_live_order=False,
        )

    def healthcheck(self) -> IntegrationHealth:
        if not _VBT_AVAILABLE:
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.UNAVAILABLE,
                message="vectorbt 未安装。安装后生效: pip install vectorbt",
            )
        try:
            ver = getattr(vbt, "__version__", "unknown")
        except Exception:
            ver = "unknown"
        return IntegrationHealth(
            name=self.NAME,
            status=HealthStatus.HEALTHY,
            message=f"vectorbt {ver} 就绪 (向量化回测 + 参数扫描)",
        )

    # ---------- 单次回测 ----------

    def run_backtest(
        self,
        strategy_id: str,
        symbols: list[str],
        start: str,
        end: str,
        assumptions: BacktestAssumptions | None = None,
        **kw: Any,
    ) -> NormalizedBacktestResult:
        """单次向量化回测。

        关键入参 (kw):
        - bars: list[dict]  OHLCV 数据 (必需, 调用方注入, 不触网)
        - fast / slow: int  ma_cross 参数 (默认 5 / 20)
        - fees: float       手续费率 (默认 0.0003, 万三; 与原生引擎口径一致)
        - init_cash: float  初始资金 (默认 1_000_000)
        - periods_per_year: int  Sharpe 年化因子 (股票日频默认 252)

        约束: vectorbt 不可用时返回带 UNAVAILABLE 标记的空结果 (失败安全),
        不抛破坏性异常。
        """
        if not _VBT_AVAILABLE:
            return self._unavailable_result(strategy_id, symbols, start, end, assumptions)

        bars = kw.get("bars") or []
        close = bars_to_close_series(bars)
        fees = float(kw.get("fees", 0.0003))
        init_cash = float(kw.get("init_cash", 1_000_000.0))
        periods_per_year = int(kw.get("periods_per_year", DEFAULT_PERIODS_PER_YEAR))
        if periods_per_year <= 0:
            raise ValueError("periods_per_year must be positive")
        # benchmark 默认沪深300 (A 股); 全球品种调用方应传 benchmark="S&P500" 等
        benchmark = kw.get("benchmark", "沪深300")
        fast = int(kw.get("fast", 5))
        slow = int(kw.get("slow", 20))
        symbol = symbols[0] if symbols else (close.name or "unknown")

        assump = assumptions or build_assumptions(
            self.NAME,
            fees=fees,
            periods_per_year=periods_per_year,
        )

        if len(close) <= slow:
            return self._insufficient_result(strategy_id, symbol, start, end, assump, init_cash)

        entries, exits = build_ma_cross_signals(close, fast, slow)
        pf = vbt.Portfolio.from_signals(
            close,
            entries,
            exits,
            fees=fees,
            init_cash=init_cash,
            freq="1D",
        )
        # vectorbt defaults a daily calendar to 365 periods/year.  Equity
        # returns, normalized Sharpe, PSR and DSR all use the explicit stock
        # trading-year convention instead.
        stats = pf.stats(settings={"year_freq": f"{periods_per_year}D"})

        # 权益曲线 + 交易记录归一化 (失败安全: 取不到就给空)
        try:
            equity = pf.value().tolist()
        except Exception:
            equity = []
        metrics = map_vbt_stats_to_metrics(stats)
        returns = equity_curve_returns(equity)
        if len(returns) >= 2:
            metrics.sharpe = annualized_sharpe_from_returns(returns, periods_per_year)
        try:
            trades = pf.trades.records_readable.to_dict("records")
        except Exception:
            trades = []

        return NormalizedBacktestResult(
            engine_name=self.NAME,
            strategy_id=strategy_id,
            universe=list(symbols) or [symbol],
            start_date=start,
            end_date=end,
            initial_cash=init_cash,
            benchmark=benchmark,
            assumptions=assump,
            metrics=metrics,
            equity_curve=[{"date": str(d), "value": v} for d, v in zip(close.index, equity)]
            if len(equity) == len(close.index)
            else [{"value": v} for v in equity],
            trades=_safe_serialize(trades),
            risk_events=[],
            evidence_links=[],
            reproducibility_hash=None,
            research_only=True,
        )

    # ---------- 参数扫描 (vectorBT 的核心价值) ----------

    def param_sweep(
        self,
        bars: list[dict[str, Any]],
        param_grid: dict[str, list[Any]] | None = None,
        strategy_id: str = _DEFAULT_STRATEGY,
        fees: float = 0.0003,
        init_cash: float = 1_000_000.0,
        metric: str = "sharpe",
        top_n: int = 20,
        periods_per_year: int = DEFAULT_PERIODS_PER_YEAR,
        effective_trials: float | None = None,
    ) -> list[dict[str, Any]]:
        """参数网格扫描: 逐组跑 ma_cross, 按指定指标排序, 返回 top_n。

        返回 [{"params": {fast, slow}, "metrics": BacktestMetrics-dict, "total_return": float}, ...]
        降序 (metric 越大越好; max_drawdown 取绝对值后负向, 即小回撤优先)。

        vectorbt 不可用 / 数据不足 → 返回空列表 (失败安全)。
        本方法是 vectorBT 相对原生引擎的差异化能力, 故单独暴露。
        """
        if not _VBT_AVAILABLE:
            return []
        from backend.quant.metrics_advanced import attach_selection_bias_metrics

        grid = parse_param_grid(param_grid) or DEFAULT_PARAM_GRID
        fasts = [int(x) for x in grid.get("fast", [5])]
        slows = [int(x) for x in grid.get("slow", [20])]
        n_trials = count_param_trials(grid)
        periods = int(periods_per_year)
        if periods <= 0:
            raise ValueError("periods_per_year must be positive")
        resolved_effective_trials = float(n_trials if effective_trials is None else effective_trials)
        if not math.isfinite(resolved_effective_trials) or resolved_effective_trials < 1:
            raise ValueError("effective_trials must be finite and at least one")
        resolved_effective_trials = min(float(n_trials), resolved_effective_trials)

        raw_results: list[dict[str, Any]] = []
        for fast in fasts:
            for slow in slows:
                if fast >= slow:
                    continue
                res = self.run_backtest(
                    strategy_id=strategy_id,
                    symbols=[],
                    start="",
                    end="",
                    bars=bars,
                    fast=fast,
                    slow=slow,
                    fees=fees,
                    init_cash=init_cash,
                    periods_per_year=periods,
                )
                m = res.metrics
                returns = equity_curve_returns(res.equity_curve)
                raw_results.append(
                    {
                        "params": {"fast": fast, "slow": slow},
                        "metrics": m.model_dump(),
                        "total_return": m.total_return,
                        "sharpe": m.sharpe,
                        "max_drawdown": m.max_drawdown,
                        "returns": returns,
                    }
                )

        # DSR needs the complete candidate distribution, not only the selected
        # top-N rows.  Enrich in a second pass after every valid grid point has
        # produced its Sharpe.
        candidate_sharpes = []
        for row in raw_results:
            try:
                candidate = float(row["sharpe"])
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(candidate):
                candidate_sharpes.append(candidate)

        results: list[dict[str, Any]] = []
        for row in raw_results:
            returns = row.pop("returns")
            metrics = attach_selection_bias_metrics(
                row["metrics"],
                returns,
                n_trials=n_trials,
                sharpe_key="sharpe",
                periods_per_year=periods,
                candidate_sharpes=candidate_sharpes,
                effective_trials=resolved_effective_trials,
            )
            results.append(
                {
                    **row,
                    "metrics": metrics,
                    "probabilistic_sharpe": metrics.get("probabilistic_sharpe"),
                    "deflated_sharpe": metrics.get("deflated_sharpe"),
                    "n_trials": n_trials,
                    "effective_trials": resolved_effective_trials,
                    "observations": len(returns),
                    "selection_bias_status": metrics.get("selection_bias_status", "error"),
                }
            )
        # 排序键: 默认按 sharpe 降序; max_drawdown 升序 (小回撤优先); 其余按 total_return 降序
        reverse = metric != "max_drawdown"
        key_field = metric if metric in ("sharpe", "max_drawdown", "total_return") else "sharpe"
        results.sort(
            key=lambda r: r.get(key_field) if r.get(key_field) is not None else float("-inf"),
            reverse=reverse,
        )
        return results[: max(0, int(top_n))]

    # ---------- 失败安全兜底 ----------

    def _unavailable_result(
        self,
        strategy_id: str,
        symbols: list[str],
        start: str,
        end: str,
        assumptions: BacktestAssumptions | None,
    ) -> NormalizedBacktestResult:
        assump = assumptions or build_assumptions(self.NAME, fees=0.0, note="vectorbt 不可用")
        return NormalizedBacktestResult(
            engine_name=self.NAME,
            strategy_id=strategy_id,
            universe=list(symbols),
            start_date=start,
            end_date=end,
            initial_cash=None,
            assumptions=assump,
            metrics=BacktestMetrics(),
            equity_curve=[],
            trades=[],
            risk_events=[],
            evidence_links=[],
            reproducibility_hash=None,
            research_only=True,
        )

    def _insufficient_result(
        self,
        strategy_id: str,
        symbol: str,
        start: str,
        end: str,
        assumptions: BacktestAssumptions,
        init_cash: float,
    ) -> NormalizedBacktestResult:
        return NormalizedBacktestResult(
            engine_name=self.NAME,
            strategy_id=strategy_id,
            universe=[symbol],
            start_date=start,
            end_date=end,
            initial_cash=init_cash,
            assumptions=assumptions,
            metrics=BacktestMetrics(),
            equity_curve=[],
            trades=[],
            risk_events=[],
            evidence_links=[],
            reproducibility_hash=None,
            research_only=True,
        )


def _safe_serialize(trades: Any) -> list[dict[str, Any]]:
    """把 vectorbt 的 trades 记录转成可 JSON 序列化的 list[dict] (失败安全)。"""
    if not trades:
        return []
    if isinstance(trades, list):
        return [t for t in trades if isinstance(t, dict)]
    try:
        return list(trades)
    except Exception:
        return []
