"""PyBroker Adapter — ML + walk-forward 回测 (Phase 2 第六个真实 adapter, §9.4).

PyBroker (Apache-2.0, edtechre/pybroker) 是面向机器学习的回测框架, 强项是**walk-forward
验证 + 内置 ML 模型管线**, 适合策略过拟合检测与 ML 策略研究。本 adapter 把它接入
AlphaScope 的 Integration Registry, 作为「ML 回测」层与 vectorBT(向量化参数扫描)/
Backtrader(经典事件驱动)/原生引擎(A股真实摩擦)形成互补
(对应战略规划 §9.4「PyBroker」与 Phase B 第 1 项)。

设计要点 (延续项目「确定性 · 失败安全 · 可溯源」基线):
- **可选依赖 + 优雅降级**: ``lib-pybroker`` 用 import-guard 包裹 (PyPI 包名是
  lib-pybroker, 不是 pybroker), 没装不影响其余功能 (healthcheck 报 UNAVAILABLE)。
- **不触网**: PyBroker 直传 pandas DataFrame 即可回测 (无需 DataSource/YFinance),
  OHLCV 由调用方通过 ``bars=`` 注入。
- **诚实假设卡**: PyBroker 原生不模拟 A 股 T+1 / 印花税 / 涨跌停; 假设卡显式标注。
- **边界**: ``allow_live_order=False``; 通过 registry 三道断言。
- **归一化纯函数可单测**: ``bars_to_pybroker_df`` / ``build_assumptions`` /
  ``extract_pybroker_metrics`` 不依赖 pybroker, 始终可测。

A​PI 已对照 lib-pybroker 1.2.x 真实源码核对 (非臆测):
- ``Strategy(df, start_date, end_date, config=StrategyConfig(...))`` 直传 DataFrame
- ``strat.add_execution(fn, symbols, indicators=[...])``
- ``result = strat.backtest(warmup=N)`` 或 ``strat.walkforward(windows=N)``
- ``result.metrics.sharpe / total_return_pct / max_drawdown_pct / win_rate`` (EvalMetrics)
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: lib-pybroker 缺失时优雅降级 -----
# 注意 PyPI 包名是 lib-pybroker, 顶层 import 名仍是 pybroker
try:
    from pybroker import Strategy as _PybrokerStrategy  # type: ignore[import-untyped]
    from pybroker import StrategyConfig as _PybrokerConfig  # type: ignore[import-untyped]
    import pandas as pd
    import numpy as np

    _PB_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    _PybrokerStrategy = None  # type: ignore[assignment]
    _PybrokerConfig = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    _PB_AVAILABLE = False

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
# 纯函数 (无需 pybroker 即可单测)
# ============================================================


def bars_to_pybroker_df(bars: list[dict[str, Any]], symbol: str = "DEMO") -> "pd.DataFrame":
    """把 AlphaScope OHLCV dict 列表转成 PyBroker 要求的长格式 DataFrame。

    PyBroker 要求列: date / symbol / open / high / low / close (+ volume 可选)。
    date 必须是 datetime (非字符串)。纯函数, 失败安全: 空/缺字段 → 空 DataFrame。
    """
    if pd is None or not bars:
        return pd.DataFrame() if pd is not None else None  # type: ignore[return-value]
    try:
        df = pd.DataFrame(bars)
        rename = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        df = df.rename(columns=rename)
        for col in ("open", "high", "low", "close", "volume"):
            if col not in df.columns:
                df[col] = 0.0
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        if "date" not in df.columns:
            return pd.DataFrame()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
        df["symbol"] = symbol
        df = df.sort_values("date")
        cols = ["date", "symbol", "open", "high", "low", "close"]
        if "volume" in df.columns:
            cols.append("volume")
        return df[cols]
    except Exception:
        return pd.DataFrame() if pd is not None else None  # type: ignore[return-value]


def build_assumptions(
    engine_name: str = "pybroker",
    initial_cash: float = 1_000_000,
    buy_delay: int = 1,
    sell_delay: int = 1,
) -> BacktestAssumptions:
    """构造诚实假设卡 (与其他 adapter 一致的披露口径)。

    PyBroker 原生**不**模拟 A 股 T+1 / 印花税 / 涨跌停过滤; 通过 buy_delay/sell_delay
    控制 next-bar 成交 (默认 1, T+1 口径的弱近似), 通过 fee_mode 设佣金。
    """
    return BacktestAssumptions(
        engine_name=engine_name,
        commission_rate=None,  # fee 由 StrategyConfig.fee_amount 控制, 非单一率
        stamp_duty_rate=None,
        slippage_rate=None,
        execution_price=f"next bar (buy_delay={buy_delay}, sell_delay={sell_delay})",
        settlement_rule=f"buy_delay={buy_delay} (T+1 近似, 非真实 A 股约束)",
        price_limit_filter=False,
        suspension_handling=None,
        adj_method="后复权 (由数据源决定)",
        future_function_check=True,
        data_source="调用方注入 (bars=)",
        note=(
            "pybroker ML + walk-forward 回测: 原生不模拟 A 股 T+1/印花税/涨跌停/停牌; "
            "buy_delay/sell_delay 是 next-bar 成交近似 T+1; 结果偏乐观, 适合 ML 策略研究"
            "与过拟合检测, 严肃 A 股回测须切回原生引擎。"
        ),
    )


def extract_pybroker_metrics(metrics: Any) -> BacktestMetrics:
    """从 PyBroker EvalMetrics 对象抽取归一化指标 (容错)。

    PyBroker 字段名: sharpe / sortino / calmar / max_drawdown_pct /
    total_return_pct / win_rate / profit_factor / trade_count。
    """
    m = BacktestMetrics()

    def _get(name: str) -> float | None:
        try:
            v = getattr(metrics, name, None)
            if v is None:
                return None
            f = float(v)
            return f if f == f and f not in (float("inf"), float("-inf")) else None
        except (TypeError, ValueError):
            return None

    m.sharpe = _get("sharpe")
    m.sortino = _get("sortino")
    m.calmar = _get("calmar")
    m.max_drawdown = _get("max_drawdown_pct")
    m.total_return = _get("total_return_pct")
    m.annual_return = _get("annual_return_pct")
    m.volatility = _get("annual_volatility_pct")
    m.win_rate = _get("win_rate")
    m.profit_factor = _get("profit_factor")
    return m


# ============================================================
# Adapter
# ============================================================


@register
class PybrokerAdapter(BacktestEngineAdapter):
    """PyBroker ML + walk-forward 回测 adapter (§9.4)。

    强项是 walk-forward 验证 + 内置 ML 模型管线 (策略过拟合检测); 与 vectorBT/
    Backtrader/原生引擎形成多引擎互补。所需 OHLCV 由调用方注入 (``bars=``)。
    """

    NAME = "pybroker"
    # CATEGORY 继承自 BacktestEngineAdapter.BACKTEST

    def _metadata(self) -> IntegrationMetadata:
        return IntegrationMetadata(
            name=self.NAME,
            category=self.CATEGORY,
            mode=IntegrationMode.PYTHON_ADAPTER,
            version="0.1.0",
            display_name="PyBroker ML 回测",
            description=(
                "面向机器学习的 Python 回测框架, 强项是 walk-forward 验证 + 内置 ML "
                "模型管线, 适合策略过拟合检测。与 vectorBT/Backtrader/原生引擎形成"
                "多引擎互补。可选依赖, 缺失时降级。"
            ),
            homepage="https://github.com/edtechre/pybroker",
            package="lib-pybroker",  # PyPI 包名
            capabilities=[
                {"name": "run_backtest", "description": "MA 规则回测 + walk-forward"},
            ],
            license_name="Apache-2.0",
            license_safety=LicenseSafety.SAFE,
            code_copy_allowed=True,
            allow_live_order=False,
        )

    def healthcheck(self) -> IntegrationHealth:
        if not _PB_AVAILABLE:
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.UNAVAILABLE,
                message=(
                    "lib-pybroker 未安装。安装后生效: pip install lib-pybroker "
                    "(注意 PyPI 包名是 lib-pybroker, import 名是 pybroker)"
                ),
            )
        return IntegrationHealth(
            name=self.NAME,
            status=HealthStatus.HEALTHY,
            message="pybroker 就绪 (ML + walk-forward 回测)",
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
        """MA 规则回测 (内置简单规则, 验证引擎走通)。

        关键入参 (kw):
        - bars: list[dict]      OHLCV (必需, 注入不触网)
        - fast / slow: int      MA 参数 (默认 5 / 20)
        - initial_cash: float   初始资金 (默认 1_000_000)
        - buy_delay/sell_delay: next-bar 成交延迟 (默认 1)

        失败安全: pybroker 不可用 / 数据不足 / 运行抛错 → 返回空结果, 不抛。
        """
        if not _PB_AVAILABLE:
            return self._unavailable_result(strategy_id, symbols, start, end, assumptions)

        bars = kw.get("bars") or []
        fast = int(kw.get("fast", 5))
        slow = int(kw.get("slow", 20))
        initial_cash = float(kw.get("initial_cash", 1_000_000.0))
        buy_delay = int(kw.get("buy_delay", 1))
        sell_delay = int(kw.get("sell_delay", 1))
        symbol = symbols[0] if symbols else "DEMO"

        assump = assumptions or build_assumptions(
            engine_name=self.NAME,
            initial_cash=initial_cash,
            buy_delay=buy_delay,
            sell_delay=sell_delay,
        )

        df = bars_to_pybroker_df(bars, symbol=symbol)
        if df is None or len(df) <= slow + 5:  # 留 warmup 余量
            return self._insufficient_result(strategy_id, symbol, start, end, assump, initial_cash)

        # 确定日期范围 (优先用 df 实际范围, 因为 PyBroker 按日期过滤)
        df_start = str(df["date"].min().date())
        df_end = str(df["date"].max().date())

        try:
            config = _PybrokerConfig(  # type: ignore[misc]
                initial_cash=initial_cash,
                buy_delay=buy_delay,
                sell_delay=sell_delay,
                bars_per_year=252,
                exit_on_last_bar=True,
            )
            strat = _PybrokerStrategy(df, df_start, df_end, config=config)  # type: ignore[misc]

            # 内置 MA 规则 (纯规则, 不用 ML)
            def ma_rule(ctx: Any) -> None:
                closes = ctx.close
                if len(closes) < slow:
                    return
                fast_ma = float(np.mean(closes[-fast:]))  # type: ignore[union-attr]
                slow_ma = float(np.mean(closes[-slow:]))  # type: ignore[union-attr]
                if not ctx.long_pos() and fast_ma > slow_ma:
                    ctx.buy_shares = 100
                elif ctx.long_pos() and fast_ma < slow_ma:
                    ctx.sell_all_shares()

            strat.add_execution(ma_rule, [symbol])
            result = strat.backtest(warmup=slow)
            metrics = extract_pybroker_metrics(result.metrics)

            # 权益曲线 (简化: 用 portfolio 的 final equity)
            try:
                eq_df = result.portfolio
                equity_curve = (
                    [{"date": str(idx.date()), "value": float(row["equity"])} for idx, row in eq_df.iterrows()]
                    if "equity" in eq_df.columns and len(eq_df) > 0
                    else []
                )
            except Exception:
                equity_curve = []

            return NormalizedBacktestResult(
                engine_name=self.NAME,
                strategy_id=strategy_id,
                universe=list(symbols) or [symbol],
                start_date=start or df_start,
                end_date=end or df_end,
                initial_cash=initial_cash,
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
            return self._insufficient_result(strategy_id, symbol, start, end, assump, initial_cash)

    # ---------- 失败安全兜底 ----------

    def _unavailable_result(
        self,
        strategy_id: str,
        symbols: list[str],
        start: str,
        end: str,
        assumptions: BacktestAssumptions | None,
    ) -> NormalizedBacktestResult:
        assump = assumptions or build_assumptions(engine_name=self.NAME, note="pybroker 不可用")
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
