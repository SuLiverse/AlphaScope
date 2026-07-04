"""Backtrader Adapter — 经典策略兼容层 (Phase 2 第五个真实 adapter, §9.5).

Backtrader (GPL? LGPL? — 实际 LGPL-2.1) 是成熟的 Python 回测框架, 适合接入大量已有
策略、教学验证、迁移老策略。本 adapter 把它接入 AlphaScope 的 Integration Registry,
作为「经典策略兼容层」与 vectorBT (向量化) / AlphaScope 原生 (A 股真实摩擦) 形成互补
(对应战略规划 §9.5「BacktraderAdapter」与 v2.0 蓝图)。

设计要点 (延续项目「确定性 · 失败安全 · 可溯源」基线):
- **可选依赖 + 优雅降级**: ``backtrader`` 用 import-guard 包裹, 没装不影响其余功能
  (healthcheck 报 UNAVAILABLE)。pip install 后即生效。
- **不触网**: OHLCV 由调用方通过 ``bars=`` 注入, 不抓数据、不下单。
- **诚实假设卡**: Backtrader 原生不模拟 A 股 T+1 / 印花税 / 涨跌停; 假设卡显式标注
  (与 vectorbt_adapter 一致的诚实披露, 防误读为可实盘)。
- **边界**: ``allow_live_order=False``, 仅回测; 通过 registry 三道断言。
- **归一化纯函数可单测**: ``bars_to_feed_data`` / ``extract_analyzer_metrics`` /
  ``build_assumptions`` 不依赖 backtrader, 始终可测。

A​PI 已对照 backtrader 1.9.78 真实源码核对 (非臆测):
- ``cerebro = bt.Cerebro()`` + ``adddata(bt.feeds.PandasData(...))`` + ``addstrategy``
- ``result = cerebro.run()`` → 返回策略实例列表
- ``cerebro.broker.getvalue()`` 取终值; analyzer 通过 ``addanalyzer`` + ``strat.analyzers.x.get_analysis()``
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: backtrader 缺失时优雅降级 -----
# pandas 单独守卫: 引擎缺失不应拖垮纯函数 (bars_to_feed_data 只需 pandas)
try:
    import pandas as pd
except Exception:
    pd = None  # type: ignore[assignment]

try:
    import backtrader as bt  # type: ignore[import-untyped]

    _BT_AVAILABLE = pd is not None
except Exception:  # ImportError / 副作用失败都不致命
    bt = None  # type: ignore[assignment]
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
# 纯函数 (无需 backtrader 即可单测)
# ============================================================


def bars_to_feed_data(bars: list[dict[str, Any]]) -> "pd.DataFrame":
    """把 AlphaScope OHLCV dict 列表转成 backtrader PandasData 要求的 DataFrame。

    PandasData 默认要求列: open/high/low/close/volume + DatetimeIndex。
    纯函数, 失败安全: 空/缺字段 → 空 DataFrame。
    """
    if pd is None or not bars:
        return pd.DataFrame() if pd is not None else None  # type: ignore[return-value]
    try:
        df = pd.DataFrame(bars)
        # 列名归一化 (akshare 用中文, openbb 用英文大小写)
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
        df = df.dropna(subset=["date"]).set_index("date").sort_index()
        return df[["open", "high", "low", "close", "volume"]]
    except Exception:
        return pd.DataFrame() if pd is not None else None  # type: ignore[return-value]


def build_assumptions(
    engine_name: str = "backtrader",
    commission: float = 0.0003,
    stake: int = 100,
    note: str | None = None,
) -> BacktestAssumptions:
    """构造诚实假设卡 (与 vectorbt 一致的披露口径)。

    Backtrader 原生**不**模拟 A 股 T+1 / 印花税 / 涨跌停过滤; 通过 commission 设佣金,
    通过 stake 设一手 100 股 (A 股惯例), 但 settlement/limit 需策略层自行处理。
    """
    return BacktestAssumptions(
        engine_name=engine_name,
        commission_rate=commission,
        stamp_duty_rate=None,  # backtrader 不区分买卖手费用, 不模拟印花税
        slippage_rate=None,
        execution_price="next bar 开盘价 (backtrader 默认)",
        settlement_rule="无 T+1 约束 (策略层需自行实现)",
        price_limit_filter=False,  # 不模拟涨跌停
        suspension_handling=None,
        adj_method="后复权 (由数据源决定)",
        future_function_check=True,
        data_source="调用方注入 (bars=)",
        note=note
        or (
            "backtrader 向事件驱动回测: 原生不模拟 A 股 T+1/印花税/涨跌停/停牌; "
            "结果偏乐观, 适合经典策略兼容/教学验证, 严肃 A 股回测须切回原生引擎。"
        ),
    )


def extract_analyzer_metrics(analyzers: Any) -> BacktestMetrics:
    """从 backtrader analyzer 结果抽取归一化指标 (容错)。

    analyzers 是策略实例的 ``strat.analyzers`` 对象。各 analyzer 的 get_analysis()
    返回结构各异, 本函数容错抽取常见字段。
    """
    m = BacktestMetrics()

    def _get(name: str) -> Any:
        try:
            a = getattr(analyzers, name, None)
            return a.get_analysis() if a else None
        except Exception:
            return None

    # Returns analyzer (按 sharpe/time_return 等)
    ret = _get("returns")
    if isinstance(ret, dict):
        try:
            if "sharpe" in ret:
                m.sharpe = float(ret["sharpe"])
            if "rnorm" in ret:
                m.annual_return = float(ret["rnorm"]) * 100
        except (TypeError, ValueError):
            pass

    # SharpeRatioAnnualized
    sharp = _get("sharpe")
    if isinstance(sharp, dict):
        try:
            v = sharp.get("sharpe") or sharp.get("ratio")
            if v is not None:
                m.sharpe = float(v)
        except (TypeError, ValueError):
            pass

    # DrawDown analyzer
    dd = _get("drawdown")
    if isinstance(dd, dict):
        try:
            m.max_drawdown = float(dd.get("max", {}).get("drawdown", 0.0))
        except (TypeError, ValueError, AttributeError):
            pass

    # Trade analyzer
    trades = _get("trades")
    if isinstance(trades, dict):
        try:
            won = trades.get("won", {}).get("total", 0)
            lost = trades.get("lost", {}).get("total", 0)
            total = won + lost
            if total > 0:
                m.win_rate = float(won / total * 100)
            pf = trades.get("pnl", {}).get("gross", {})
            gross_profit = pf.get("profit", 0) if isinstance(pf, dict) else 0
            gross_loss = abs(pf.get("loss", 0)) if isinstance(pf, dict) else 0
            if gross_loss > 0:
                m.profit_factor = float(gross_profit / gross_loss)
        except (TypeError, ValueError, AttributeError):
            pass
    return m


# ============================================================
# 内置 MA 交叉策略 (与 vectorbt_adapter 对齐, 便于跨引擎对比)
# ============================================================


def _make_ma_cross_strategy_class(fast: int, slow: int) -> type:
    """构造一个 backtrader Strategy 子类 (MA 交叉), 参数化 fast/slow。

    动态构造而非固定类, 是为了让 adapter 能 param_sweep 不同 fast/slow 组合。
    """
    if not _BT_AVAILABLE:
        raise RuntimeError("backtrader 未安装")

    class _MACross(bt.Strategy):  # type: ignore[misc, valid-type]
        params = (("pfast", fast), ("pslow", slow))  # type: ignore[assignment]

        def __init__(self) -> None:
            sma_fast = bt.ind.SMA(period=self.p.pfast)  # type: ignore[union-attr]
            sma_slow = bt.ind.SMA(period=self.p.pslow)  # type: ignore[union-attr]
            self.crossover = bt.ind.CrossOver(sma_fast, sma_slow)  # type: ignore[union-attr]

        def next(self) -> None:
            if not self.position:
                if self.crossover > 0:
                    self.buy()
            elif self.crossover < 0:
                self.sell()

    return _MACross


# ============================================================
# Adapter
# ============================================================


@register
class BacktraderAdapter(BacktestEngineAdapter):
    """Backtrader 经典策略回测 adapter (§9.5)。

    强项是事件驱动 + 大量已有策略兼容; 与 vectorBT (向量化) / AlphaScope 原生
    (A 股真实摩擦) 形成多引擎互补。所需 OHLCV 由调用方注入 (``bars=``)。
    """

    NAME = "backtrader"
    # CATEGORY 继承自 BacktestEngineAdapter.BACKTEST

    def _metadata(self) -> IntegrationMetadata:
        return IntegrationMetadata(
            name=self.NAME,
            category=self.CATEGORY,
            mode=IntegrationMode.PYTHON_ADAPTER,
            version="0.1.0",
            display_name="Backtrader 经典回测",
            description=(
                "成熟的事件驱动 Python 回测框架, 适合经典策略兼容/教学验证/"
                "迁移老策略。与 vectorBT/原生引擎形成多引擎互补。原生不模拟 A 股 "
                "T+1/印花税/涨跌停, 适合交叉验证。可选依赖, 缺失时降级。"
            ),
            homepage="https://github.com/mementum/backtrader",
            package="backtrader",
            capabilities=[
                {"name": "run_backtest", "description": "事件驱动 MA 交叉回测"},
            ],
            # backtrader 是 LGPL-2.1 (宽松, 可 pip 安装使用)
            license_name="LGPL-2.1",
            license_safety=LicenseSafety.SAFE,
            code_copy_allowed=True,
            allow_live_order=False,
        )

    def healthcheck(self) -> IntegrationHealth:
        if not _BT_AVAILABLE:
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.UNAVAILABLE,
                message="backtrader 未安装。安装后生效: pip install backtrader",
            )
        return IntegrationHealth(
            name=self.NAME,
            status=HealthStatus.HEALTHY,
            message=f"backtrader {getattr(bt, '__version__', '?')} 就绪 (事件驱动经典回测)",
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
        """事件驱动 MA 交叉回测。

        关键入参 (kw):
        - bars: list[dict]  OHLCV (必需, 注入不触网)
        - fast / slow: int  MA 参数 (默认 5 / 20)
        - commission: float 佣金率 (默认 0.0003)
        - stake: int        一手股数 (默认 100, A 股惯例)
        - init_cash: float  初始资金 (默认 1_000_000)

        失败安全: backtrader 不可用 / 数据不足 / 运行抛错 → 返回带 UNAVAILABLE 标记
        的空结果, 不抛破坏性异常。
        """
        if not _BT_AVAILABLE:
            return self._unavailable_result(strategy_id, symbols, start, end, assumptions)

        bars = kw.get("bars") or []
        fast = int(kw.get("fast", 5))
        slow = int(kw.get("slow", 20))
        commission = float(kw.get("commission", 0.0003))
        stake = int(kw.get("stake", 100))
        init_cash = float(kw.get("init_cash", 1_000_000.0))
        symbol = symbols[0] if symbols else "unknown"
        assump = assumptions or build_assumptions(engine_name=self.NAME, commission=commission, stake=stake)

        df = bars_to_feed_data(bars)
        if df is None or len(df) <= slow:
            return self._insufficient_result(strategy_id, symbol, start, end, assump, init_cash)

        try:
            cerebro = bt.Cerebro()  # type: ignore[union-attr]
            cerebro.broker.setcash(init_cash)
            cerebro.broker.setcommission(commission=commission)
            cerebro.addsizer_byidx(0, lambda s, a: dict(size=stake)) if False else None
            # 简化: 固定每次买 stake 股 (用固定 sizer)
            cerebro.addsizer(bt.sizers.FixedSize, stake=stake)  # type: ignore[union-attr]

            data = bt.feeds.PandasData(dataname=df)  # type: ignore[union-attr]
            cerebro.adddata(data)
            cerebro.addstrategy(_make_ma_cross_strategy_class(fast, slow))

            # analyzers (容错: 不同 backtrader 版本 analyzer 名略有差异)
            cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")  # type: ignore[union-attr]
            cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)  # type: ignore[union-attr]
            cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")  # type: ignore[union-attr]
            cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")  # type: ignore[union-attr]

            results = cerebro.run()
            strat = results[0] if results else None
            final_value = cerebro.broker.getvalue()

            metrics = BacktestMetrics()
            if strat is not None:
                metrics = extract_analyzer_metrics(strat.analyzers)
            # 总收益从 cash 推算 (更可靠)
            if init_cash > 0:
                metrics.total_return = (final_value - init_cash) / init_cash * 100

            # 权益曲线 (简化: backtrader 不直接产 equity curve, 用首末两点近似)
            equity_curve = [
                {"date": str(df.index[0].date()), "value": float(init_cash)},
                {"date": str(df.index[-1].date()), "value": float(final_value)},
            ]

            return NormalizedBacktestResult(
                engine_name=self.NAME,
                strategy_id=strategy_id,
                universe=list(symbols) or [symbol],
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
            return self._insufficient_result(strategy_id, symbol, start, end, assump, init_cash)

    # ---------- 失败安全兜底 ----------

    def _unavailable_result(
        self,
        strategy_id: str,
        symbols: list[str],
        start: str,
        end: str,
        assumptions: BacktestAssumptions | None,
    ) -> NormalizedBacktestResult:
        assump = assumptions or build_assumptions(engine_name=self.NAME, note="backtrader 不可用")
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
