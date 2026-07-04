"""bt Adapter — 组合级策略回测 (Phase 2 第七个 adapter, §9.4 / Phase B #2).

bt (Apache-2.0, pmorissette/bt) 是组合级策略回测框架, 强项是**可组合的 algo 链**
(SelectAll/WeighEqually/WeighInvVol/Rebalance 等), 适合资产配置、再平衡、多策略组合
研究。本 adapter 把它接入 AlphaScope 的 Integration Registry, 作为「组合级回测」层,
与 vectorBT(向量化)/Backtrader(事件驱动)/PyBroker(ML)/原生引擎(A股真实摩擦)互补
(对应战略规划 Phase B 第 2 项「bt Adapter」与 §4 组合回测)。

设计要点 (延续项目「确定性 · 失败安全 · 可溯源」基线):
- **可选依赖 + 优雅降级**: ``bt`` 用 import-guard 包裹, 没装不影响其余功能。
- **不触网**: 价格数据由调用方通过 ``prices=`` 注入 (DataFrame 列=资产)。
- **诚实假设卡**: bt 原生不模拟 A 股 T+1 / 印花税 / 涨跌停; 假设卡显式标注。
- **边界**: ``allow_live_order=False``; 通过 registry 三道断言。

A​PI 已对照 bt 1.2.0 真实源码核对 (非臆测):
- ``bt.Strategy(name, [algos])`` + ``bt.Backtest(strategy, prices)`` + ``bt.run(backtest)``
- ``res[strategy_name].stats`` 返回 Series, 含 total_return/daily_sharpe/max_drawdown/
  calmar/daily_sortino/win_rate 等
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: bt 缺失时优雅降级 -----
try:
    import bt as _bt  # type: ignore[import-untyped]
    import pandas as pd

    _BT_AVAILABLE = True
except Exception:
    _bt = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]
    _BT_AVAILABLE = False

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


# ============================================================
# 纯函数 (无需 bt 即可单测)
# ============================================================


def bars_to_price_df(bars: list[dict[str, Any]], symbols: list[str] | None = None) -> "pd.DataFrame":
    """把 OHLCV dict 列表 (可能多标的) 转成 bt 要求的 wide 格式价格 DataFrame。

    bt 要求: index=date, columns=asset, values=close price。
    输入 bars 若含 symbol 字段, 按 symbol 分列; 否则用 symbols[0] 作单列。
    纯函数, 失败安全: 空/缺字段 → 空 DataFrame。
    """
    if pd is None or not bars:
        return pd.DataFrame() if pd is not None else None  # type: ignore[return-value]
    try:
        df = pd.DataFrame(bars)
        if "date" not in df.columns and "日期" not in df.columns:
            return pd.DataFrame()
        date_col = "date" if "date" in df.columns else "日期"
        close_col = "close" if "close" in df.columns else "收盘"
        sym_col = "symbol" if "symbol" in df.columns else None

        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df = df.dropna(subset=[date_col])
        df[close_col] = pd.to_numeric(df[close_col], errors="coerce")

        if sym_col and df[sym_col].nunique() > 1:
            # 多标的: pivot 成 wide
            pivot = df.pivot_table(index=date_col, columns=sym_col, values=close_col)
            return pivot.sort_index()
        else:
            # 单标的
            name = symbols[0] if symbols else (df[sym_col].iloc[0] if sym_col else "ASSET")
            return df.set_index(date_col)[[close_col]].rename(columns={close_col: name}).sort_index()
    except Exception:
        return pd.DataFrame() if pd is not None else None  # type: ignore[return-value]


def build_assumptions(engine_name: str = "bt") -> BacktestAssumptions:
    """构造诚实假设卡 (与其他 adapter 披露口径一致)。"""
    return BacktestAssumptions(
        engine_name=engine_name,
        commission_rate=None,  # bt 手续费在 algo 链里配, 非单一率
        stamp_duty_rate=None,
        slippage_rate=None,
        execution_price="收盘价 (bt 默认, 收盘撮合)",
        settlement_rule="无 T+1 约束 (bt 原生不限, 需 algo 自行实现)",
        price_limit_filter=False,
        suspension_handling=None,
        adj_method="后复权 (由数据源决定)",
        future_function_check=True,
        data_source="调用方注入 (prices=)",
        note=(
            "bt 组合级回测: 原生不模拟 A 股 T+1/印花税/涨跌停/停牌; "
            "强项是可组合 algo 链 (SelectAll/WeighEqually/Rebalance) 做资产配置/再平衡研究; "
            "结果偏乐观, 严肃 A 股回测须切回原生引擎。"
        ),
    )


def extract_bt_stats(stats: Any) -> BacktestMetrics:
    """从 bt 的 stats Series 抽取归一化指标 (容错)。

    bt 字段名: total_return / daily_sharpe / daily_sortino / max_drawdown / calmar /
    daily_mean / daily_vol。
    """
    m = BacktestMetrics()

    def _get(name: str) -> float | None:
        try:
            if not hasattr(stats, "get"):
                return None
            v = stats.get(name)
            if v is None:
                return None
            f = float(v)
            return f if f == f and f not in (float("inf"), float("-inf")) else None
        except (TypeError, ValueError):
            return None

    m.total_return = _get("total_return")
    if m.total_return is not None:
        m.total_return = m.total_return * 100  # bt 返回小数, 转 %
    m.sharpe = _get("daily_sharpe")
    m.sortino = _get("daily_sortino")
    m.calmar = _get("calmar")
    m.max_drawdown = _get("max_drawdown")
    if m.max_drawdown is not None:
        m.max_drawdown = m.max_drawdown * 100  # 小数 → %
    m.annual_return = _get("cagr")
    if m.annual_return is not None:
        m.annual_return = m.annual_return * 100
    m.volatility = _get("daily_vol")
    if m.volatility is not None:
        m.volatility = m.volatility * 100
    return m


# ============================================================
# Adapter
# ============================================================


@register
class BtAdapter(BacktestEngineAdapter):
    """bt 组合级策略回测 adapter (§9.4 / Phase B #2)。

    强项是可组合 algo 链做资产配置/再平衡研究。所需价格数据由调用方注入
    (``prices=`` DataFrame, 或 ``bars=`` OHLCV 列表自动转换)。
    """

    NAME = "bt"
    # CATEGORY 继承自 BacktestEngineAdapter.BACKTEST

    def _metadata(self) -> IntegrationMetadata:
        return IntegrationMetadata(
            name=self.NAME,
            category=self.CATEGORY,
            mode=IntegrationMode.PYTHON_ADAPTER,
            version="0.1.0",
            display_name="bt 组合级回测",
            description=(
                "组合级策略回测框架, 强项是可组合 algo 链 (SelectAll/WeighEqually/"
                "WeighInvVol/Rebalance) 做资产配置/再平衡研究。与 vectorBT(向量化参数"
                "扫描)/Backtrader(事件驱动)/PyBroker(ML)/原生引擎(A股真实摩擦)互补。"
                "可选依赖, 缺失时降级。"
            ),
            homepage="https://github.com/pmorissette/bt",
            package="bt",
            capabilities=[
                {
                    "name": "run_backtest",
                    "description": "组合级 algo 链回测 (默认 WeighEqually 月度再平衡)",
                },
            ],
            license_name="Apache-2.0",
            license_safety=LicenseSafety.SAFE,
            code_copy_allowed=True,
            allow_live_order=False,
        )

    def healthcheck(self) -> IntegrationHealth:
        if not _BT_AVAILABLE:
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.UNAVAILABLE,
                message="bt 未安装。安装后生效: pip install bt",
            )
        return IntegrationHealth(
            name=self.NAME,
            status=HealthStatus.HEALTHY,
            message=f"bt {getattr(_bt, '__version__', '?')} 就绪 (组合级 algo 链回测)",
        )

    def run_backtest(
        self,
        strategy_id: str,
        symbols: list[str],
        start: str,
        end: str,
        assumptions: BacktestAssumptions | None = None,
        **kw: Any,
    ) -> NormalizedBacktestResult:
        """组合级 algo 链回测 (默认: 月度 WeighEqually 再平衡)。

        关键入参 (kw):
        - prices: DataFrame  价格数据 (优先, index=date columns=asset)
        - bars: list[dict]    OHLCV (备选, 自动转 wide 价格)
        - init_cash: float    初始资金 (默认 1_000_000)
        - rebalance: str      再平衡频率 "monthly"(默认)/"weekly"/"daily"

        失败安全: bt 不可用 / 数据不足 / 运行抛错 → 返回空结果, 不抛。
        """
        if not _BT_AVAILABLE:
            return self._unavailable_result(strategy_id, symbols, start, end, assumptions)

        prices = kw.get("prices")
        bars = kw.get("bars")
        init_cash = float(kw.get("init_cash", 1_000_000.0))
        rebalance = str(kw.get("rebalance", "monthly"))
        assump = assumptions or build_assumptions(engine_name=self.NAME)

        # 优先用 prices, 否则从 bars 转
        if prices is None:
            prices = bars_to_price_df(bars or [], symbols=symbols)
        if prices is None or len(prices) < 20:
            return self._insufficient_result(
                strategy_id,
                ",".join(symbols) or "portfolio",
                start,
                end,
                assump,
                init_cash,
            )

        try:
            # algo 链: 选全部 → 等权 → 再平衡 (频率参数化)
            run_algo = {
                "monthly": _bt.algos.RunMonthly(),  # type: ignore[union-attr]
                "weekly": _bt.algos.RunWeekly(),  # type: ignore[union-attr]
                "daily": _bt.algos.RunDaily(),  # type: ignore[union-attr]
            }.get(rebalance, _bt.algos.RunMonthly())  # type: ignore[union-attr]

            strat = _bt.Strategy(  # type: ignore[union-attr]
                strategy_id or "bt_strategy",
                [
                    run_algo,
                    _bt.algos.SelectAll(),  # type: ignore[union-attr]
                    _bt.algos.WeighEqually(),  # type: ignore[union-attr]
                    _bt.algos.Rebalance(),  # type: ignore[union-attr]
                ],
            )
            test = _bt.Backtest(strat, prices, initial_capital=init_cash)  # type: ignore[union-attr]
            res = _bt.run(test)  # type: ignore[union-attr]

            # 抽取 stats (单策略: res[strategy_name].stats)
            strat_name = strat.name
            stats = res[strat_name].stats
            metrics = extract_bt_stats(stats)

            # 权益曲线: bt 的 backtest.prices 可能是 Series 或 DataFrame, 兼容
            try:
                prices_series = res[strat_name].prices
                if isinstance(prices_series, pd.DataFrame):
                    prices_series = prices_series.iloc[:, 0]
                equity_curve = [{"date": str(idx.date()), "value": float(val)} for idx, val in prices_series.items()]
            except Exception:
                equity_curve = []

            return NormalizedBacktestResult(
                engine_name=self.NAME,
                strategy_id=strategy_id,
                universe=list(symbols) if symbols else list(prices.columns),
                start_date=start,
                end_date=end,
                initial_cash=init_cash,
                benchmark=kw.get("benchmark", "沪深300"),
                assumptions=assump,
                metrics=metrics,
                equity_curve=equity_curve,
                trades=[],
                risk_events=[],
                evidence_links=[],
                reproducibility_hash=None,
                research_only=True,
            )
        except Exception:
            return self._insufficient_result(
                strategy_id,
                ",".join(symbols) or "portfolio",
                start,
                end,
                assump,
                init_cash,
            )

    # ---------- 失败安全兜底 ----------

    def _unavailable_result(
        self,
        strategy_id: str,
        symbols: list[str],
        start: str,
        end: str,
        assumptions: BacktestAssumptions | None,
    ) -> NormalizedBacktestResult:
        assump = assumptions or build_assumptions(engine_name=self.NAME)
        assump.note = (assump.note or "") + " (bt 不可用)"
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
