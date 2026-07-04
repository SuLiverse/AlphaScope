"""Core backtesting engine - runs strategies against historical price data.

The engine models realistic A-share trading frictions so that backtest results
are not systematically overstated:

* **T+1 settlement** - a position bought on day D cannot be sold on day D.
* **Commission + stamp duty + slippage** - see :class:`constraints.TradingCostModel`.
* **Price-limit filter** - orders against a limit-locked bar are rejected.
* **No look-ahead** - a signal generated on bar ``i`` is executed on bar ``i+1``
  at the open price, so the strategy can never trade on the same bar whose close
  it used to compute the signal.

The friction models are optional and default to realistic A-share values, but
they can be disabled for parity with legacy runs. The public ``BacktestResult``
shape is unchanged so existing API consumers and tests keep working.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .constraints import PriceLimitFilter, T1Constraint, TradingCostModel
from .metrics import build_performance_summary
from .portfolio import Portfolio, Trade
from .risk_controller import RiskConfig, RiskController
from .strategies import BaseStrategy, Signal, StrategyRegistry


@dataclass
class BacktestResult:
    """Result of a backtest run."""

    strategy_name: str
    symbol: str
    params: dict[str, Any]
    equity_curve: list[float]
    dates: list[str]
    trades: list[dict[str, Any]]
    performance: dict[str, Any]
    risk_violations: list[dict[str, Any]]
    # Engine-assumption disclosure, surfaced in the result so consumers (and the
    # report generator) can show "本次回测假设: T+1 / 印花税 / 滑点 / 次日开盘成交".
    assumptions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "params": self.params,
            "equity_curve": self.equity_curve,
            "dates": self.dates,
            "trades": self.trades,
            "performance": self.performance,
            "risk_violations": self.risk_violations,
            "assumptions": self.assumptions,
        }


class BacktestEngine:
    """Core backtesting engine.

    Runs a strategy against historical price bars with portfolio simulation,
    realistic trading frictions and risk control.

    Args:
        initial_capital: Starting cash.
        commission_rate: Broker commission rate (double-sided). For historical
            compatibility the default is 0.001; when a :class:`TradingCostModel`
            is supplied this value is ignored in favour of the model's rate.
        risk_config: Optional risk-controller configuration.
        cost_model: Trading cost model (commission + stamp duty + slippage).
            Defaults to a realistic A-share model. Pass ``None`` and keep
            ``commission_rate`` to fall back to the legacy commission-only path.
        enable_t_plus_1: Enforce T+1 settlement (default True).
        enable_price_limit: Reject orders against limit-locked bars (default True).
        execution_price: Which reference price fills a deferred order:

            * ``"open"`` (default) - execute at next bar's open. This is the
              look-ahead-safe choice: a signal computed from bar ``i``'s close
              is filled at bar ``i+1``'s open.
            * ``"close"`` - legacy behaviour, fill at the signal bar's close.
              Kept for backwards comparison but not look-ahead-safe.
    """

    def __init__(
        self,
        initial_capital: float = 100000.0,
        commission_rate: float = 0.001,
        risk_config: RiskConfig | None = None,
        cost_model: TradingCostModel | None = None,
        enable_t_plus_1: bool = True,
        enable_price_limit: bool = True,
        execution_price: str = "open",
    ):
        self.initial_capital = initial_capital
        self.commission_rate = commission_rate
        self.risk_config = risk_config or RiskConfig()
        # When no explicit cost model is provided we still want honest frictions
        # (stamp duty + slippage) beyond the legacy commission-only behaviour.
        self.cost_model = cost_model if cost_model is not None else TradingCostModel()
        self.t1 = T1Constraint(enabled=enable_t_plus_1)
        self.price_limit = PriceLimitFilter(enabled=enable_price_limit)
        self.execution_price = execution_price

    def _assumptions(self) -> dict[str, Any]:
        return {
            "commission_rate": self.cost_model.commission_rate,
            "commission_min": self.cost_model.commission_min,
            "stamp_duty_rate": self.cost_model.stamp_duty_rate,
            "slippage_rate": self.cost_model.slippage_rate,
            "t_plus_1": self.t1.enabled,
            "price_limit_filter": self.price_limit.enabled,
            "price_limit_band": self.price_limit.band,
            "execution_price": self.execution_price,
            "note": "T日信号于T+1开盘价成交（防未来函数）；含佣金、印花税（卖方）、滑点。",
        }

    def run(
        self,
        strategy: BaseStrategy,
        bars: list[dict[str, Any]],
        symbol: str = "",
        benchmark_bars: list[dict[str, Any]] | None = None,
        benchmark_name: str = "",
    ) -> BacktestResult:
        """Run a backtest.

        Args:
            strategy: Strategy instance to generate signals
            bars: Historical OHLCV bars (must have 'date', 'open', 'high', 'low', 'close')
            symbol: Stock symbol for labeling
            benchmark_bars: 可选基准 OHLCV(如沪深300), 用于计算超额/信息比率/alpha/beta。
                长度/日期无需严格对齐——metrics 取尾部等长窗口优雅降级。无则跳过基准指标。
            benchmark_name: 基准名称(展示用, 如 "沪深300")。

        Returns:
            BacktestResult with equity curve, trades, and performance metrics
        """
        if not bars:
            return BacktestResult(
                strategy_name=strategy.name,
                symbol=symbol,
                params=strategy.params,
                equity_curve=[self.initial_capital],
                dates=[],
                trades=[],
                performance={},
                risk_violations=[],
                assumptions=self._assumptions(),
            )

        # Add symbol to bars for signal generation
        for bar in bars:
            bar.setdefault("symbol", symbol)

        portfolio = Portfolio(
            initial_capital=self.initial_capital,
            commission_rate=self.commission_rate,
        )
        risk_controller = RiskController(self.risk_config)

        # Generate all signals up front (strategy contract is unchanged). The
        # engine guarantees look-ahead safety by *deferring* execution: a signal
        # at index i is filled at index i+1, never at i.
        signals = strategy.generate_signals(bars, {"equity": portfolio.get_equity()})

        # pending_orders holds (signal, generated_at_index) waiting to be filled
        # on the *next* bar. This is the mechanism that kills look-ahead bias.
        pending_orders: list[tuple[Signal, int]] = []

        prev_close: float | None = None
        for i, bar in enumerate(bars):
            date = bar.get("date", f"day_{i}")
            price = bar["close"]

            # Update position mark-to-market prices.
            portfolio.update_prices({symbol: price})

            # Check drawdown circuit-breaker before any trading this bar.
            dd_check = risk_controller.check_drawdown(portfolio.equity_history)
            if not dd_check.allowed:
                risk_controller.record_violation(dd_check.rule, dd_check.reason, date)
                pending_orders = []  # risk freeze: drop pending orders too
                portfolio.record_equity(date)
                prev_close = price
                continue

            # Fill orders that were generated on a *previous* bar (look-ahead-safe).
            still_pending: list[tuple[Signal, int]] = []
            for signal, gen_idx in pending_orders:
                filled = self._fill_order(
                    signal=signal,
                    generated_at=gen_idx,
                    bar_index=i,
                    bar=bar,
                    prev_close=prev_close,
                    portfolio=portfolio,
                    risk_controller=risk_controller,
                    date=date,
                )
                if not filled and gen_idx == i - 1:
                    # An order from the immediately preceding bar that did not
                    # fill (e.g. limit-locked) is dropped to avoid stale fills.
                    still_pending.append((signal, gen_idx))
                elif not filled:
                    # Older unfilled orders are dropped rather than retried.
                    pass
            pending_orders = still_pending

            # Generate a new order for this bar (to be filled next bar).
            if i < len(signals):
                new_signal = signals[i]
                if new_signal.action in ("buy", "sell"):
                    pending_orders.append((new_signal, i))

            portfolio.record_equity(date)
            prev_close = price

        # Build performance summary
        days = len(bars)
        # 基准净值曲线: 用基准收盘价按首日归一到 initial_capital, 便于与策略净值同图对比。
        benchmark_curve: list[float] = []
        if benchmark_bars:
            bench_closes = []
            for b in benchmark_bars:
                try:
                    c = float(b.get("close", 0) or 0)
                except (TypeError, ValueError):
                    c = 0.0
                if c > 0:
                    bench_closes.append(c)
            if len(bench_closes) >= 2 and bench_closes[0] > 0:
                base = bench_closes[0]
                benchmark_curve = [self.initial_capital * (c / base) for c in bench_closes]
        performance = build_performance_summary(
            equity_curve=portfolio.equity_history,
            trades=[self._trade_to_dict(t) for t in portfolio.trades],
            initial_capital=self.initial_capital,
            days=days,
            benchmark_curve=benchmark_curve or None,
            benchmark_name=benchmark_name,
        )

        return BacktestResult(
            strategy_name=strategy.name,
            symbol=symbol,
            params=strategy.params,
            equity_curve=portfolio.equity_history,
            dates=[bar.get("date", "") for bar in bars],
            trades=[self._trade_to_dict(t) for t in portfolio.trades],
            performance=performance,
            risk_violations=risk_controller.violations,
            assumptions=self._assumptions(),
        )

    def _fill_order(
        self,
        signal: Signal,
        generated_at: int,
        bar_index: int,
        bar: dict[str, Any],
        prev_close: float | None,
        portfolio: Portfolio,
        risk_controller: RiskController,
        date: str,
    ) -> bool:
        """Attempt to fill a deferred order on ``bar``. Returns True if filled."""
        ref_price = bar.get("open") if self.execution_price == "open" else bar.get("close")
        ref_price = bar.get("open", bar.get("close")) if ref_price is None else ref_price
        if not ref_price or ref_price <= 0:
            return False

        side = signal.action
        symbol = signal.symbol

        # Price-limit filter: cannot buy at limit-up, cannot sell at limit-down.
        if not self.price_limit.tradable(bar, prev_close, side):
            risk_controller.record_violation(
                "price_limit_locked",
                f"{date} {symbol} 涨跌停封板，委托未成交",
                date,
            )
            return False

        if side == "buy" and signal.shares > 0:
            check = risk_controller.validate_buy(
                symbol=symbol,
                shares=signal.shares,
                price=ref_price,
                equity=portfolio.get_equity(),
                current_positions=portfolio.positions,
            )
            if not check.allowed:
                risk_controller.record_violation(check.rule, check.reason, date)
                return False
            fill_price, turnover, commission = self.cost_model.buy_cost(signal.shares, ref_price)
            ok = portfolio.execute_buy(symbol, signal.shares, fill_price, date, commission=commission)
            if ok:
                self.t1.record_buy(symbol, bar_index)
            else:
                risk_controller.record_violation("insufficient_cash", f"{date} 现金不足", date)
            return ok

        if side == "sell":
            if symbol not in portfolio.positions:
                return False
            # T+1: cannot sell a lot bought today (or any bar index not yet passed).
            if not self.t1.can_sell(symbol, bar_index):
                risk_controller.record_violation(
                    "t_plus_1",
                    f"{date} {symbol} T+1 约束：当日买入不可卖出",
                    date,
                )
                return False
            check = risk_controller.validate_sell(
                symbol=symbol,
                shares=portfolio.positions[symbol].shares,
                current_positions=portfolio.positions,
            )
            if not check.allowed:
                risk_controller.record_violation(check.rule, check.reason, date)
                return False
            shares = portfolio.positions[symbol].shares
            fill_price, turnover, commission, stamp = self.cost_model.sell_proceeds(shares, ref_price)
            ok = portfolio.execute_sell(
                symbol,
                shares,
                fill_price,
                date,
                commission=commission,
                stamp_duty=stamp,
            )
            return ok

        return False

    @staticmethod
    def _trade_to_dict(trade: Trade) -> dict[str, Any]:
        return {
            "symbol": trade.symbol,
            "side": trade.side,
            "shares": trade.shares,
            "price": trade.price,
            "commission": round(trade.commission, 2),
            "pnl": round(trade.pnl, 2),
            "timestamp": trade.timestamp,
        }


def run_quick_backtest(
    strategy_name: str,
    bars: list[dict[str, Any]],
    symbol: str = "",
    initial_capital: float = 100000.0,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience function to run a quick backtest.

    Returns the result as a dict for direct API response.
    """
    strategy = StrategyRegistry.create(strategy_name, params)
    if not strategy:
        return {"error": f"Unknown strategy: {strategy_name}"}

    engine = BacktestEngine(initial_capital=initial_capital)
    result = engine.run(strategy, bars, symbol)
    return result.to_dict()
