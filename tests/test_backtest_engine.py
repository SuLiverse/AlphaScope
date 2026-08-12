"""Tests for the quantitative backtesting engine (v1.1.1)."""

from __future__ import annotations

import sys
import os

# Ensure backend is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from backend.quant.strategies import BaseStrategy, Signal


# ----------------------------------------------------------------
# Sample data
# ----------------------------------------------------------------


def _make_bars(n: int = 100, base_price: float = 100.0, trend: float = 0.001) -> list[dict]:
    """Generate synthetic OHLCV bars."""
    import random

    random.seed(42)
    bars = []
    price = base_price
    for i in range(n):
        change = random.gauss(trend, 0.02) * price
        open_p = price
        close_p = price + change
        high_p = max(open_p, close_p) * (1 + random.random() * 0.01)
        low_p = min(open_p, close_p) * (1 - random.random() * 0.01)
        bars.append(
            {
                "date": f"2025-01-{i + 1:02d}",
                "open": round(open_p, 2),
                "high": round(high_p, 2),
                "low": round(low_p, 2),
                "close": round(close_p, 2),
                "volume": random.randint(100000, 1000000),
            }
        )
        price = close_p
    return bars


SAMPLE_BARS = _make_bars(120)


# ================================================================
# Test Metrics
# ================================================================


class TestMetrics:
    """Test pure metric calculation functions."""

    def test_calc_returns(self):
        from backend.quant.metrics import calc_returns

        returns = calc_returns([100, 110, 105, 115])
        assert len(returns) == 3
        assert abs(returns[0] - 0.1) < 1e-10
        assert abs(returns[1] - (-5 / 110)) < 1e-10

    def test_calc_returns_empty(self):
        from backend.quant.metrics import calc_returns

        assert calc_returns([]) == []
        assert calc_returns([100]) == []

    def test_calc_sharpe_positive(self):
        from backend.quant.metrics import calc_sharpe

        returns = [0.01, 0.02, -0.005, 0.015, 0.01]
        sharpe = calc_sharpe(returns, risk_free_rate=0.0)
        assert sharpe > 0

    def test_calc_sharpe_empty(self):
        from backend.quant.metrics import calc_sharpe

        assert calc_sharpe([]) == 0.0

    def test_calc_max_drawdown(self):
        from backend.quant.metrics import calc_max_drawdown

        curve = [100, 110, 105, 90, 95, 100]
        dd = calc_max_drawdown(curve)
        assert abs(dd - (-20 / 110)) < 0.01  # ~-18.18%

    def test_calc_max_drawdown_no_drawdown(self):
        from backend.quant.metrics import calc_max_drawdown

        assert calc_max_drawdown([100, 110, 120]) == 0.0

    def test_calc_max_drawdown_empty(self):
        from backend.quant.metrics import calc_max_drawdown

        assert calc_max_drawdown([]) == 0.0

    def test_calc_win_rate(self):
        from backend.quant.metrics import calc_win_rate

        trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -30}]
        assert calc_win_rate(trades) == 0.5

    def test_calc_win_rate_empty(self):
        from backend.quant.metrics import calc_win_rate

        assert calc_win_rate([]) == 0.0

    def test_calc_win_rate_uses_closed_trades_only(self):
        from backend.quant.metrics import calc_win_rate

        trades = [
            {"side": "buy", "pnl": 0},
            {"side": "sell", "pnl": 100},
            {"side": "buy", "pnl": 0},
            {"side": "sell", "pnl": -50},
        ]
        assert calc_win_rate(trades) == 0.5
        assert calc_win_rate(trades[:2]) == 1.0

    def test_calc_profit_factor(self):
        from backend.quant.metrics import calc_profit_factor

        trades = [{"pnl": 100}, {"pnl": -50}, {"pnl": 200}, {"pnl": -30}]
        pf = calc_profit_factor(trades)
        assert abs(pf - 300 / 80) < 0.01

    def test_calc_annualized_return(self):
        from backend.quant.metrics import calc_annualized_return

        # 100% return in 365 days = ~100% annualized
        ann = calc_annualized_return(1.0, 365)
        assert abs(ann - 1.0) < 0.01

    def test_build_performance_summary(self):
        from backend.quant.metrics import build_performance_summary

        summary = build_performance_summary(
            equity_curve=[100000, 105000, 102000, 108000],
            trades=[{"pnl": 5000}, {"pnl": -3000}, {"pnl": 6000}],
            initial_capital=100000,
            days=3,
        )
        assert "total_return" in summary
        assert "sharpe_ratio" in summary
        assert "max_drawdown" in summary
        assert "win_rate" in summary
        assert summary["total_trades"] == 3


# ================================================================
# Test Portfolio
# ================================================================


class TestPortfolio:
    """Test portfolio tracking."""

    def test_initial_state(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=100000)
        assert p.cash == 100000
        assert p.get_equity() == 100000
        assert len(p.positions) == 0

    def test_buy(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=100000, commission_rate=0.001)
        result = p.execute_buy("600519", 100, 100.0, "2025-01-01")
        assert result is True
        assert "600519" in p.positions
        assert p.positions["600519"].shares == 100
        assert p.cash < 100000

    def test_buy_insufficient_cash(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=1000)
        result = p.execute_buy("600519", 100, 100.0)
        assert result is False
        assert "600519" not in p.positions

    def test_sell(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=100000)
        p.execute_buy("600519", 100, 100.0, "2025-01-01")
        cash_before = p.cash
        result = p.execute_sell("600519", 100, 110.0, "2025-01-10")
        assert result is True
        assert "600519" not in p.positions
        assert p.cash > cash_before
        assert len(p.trades) == 2

    def test_sell_no_position(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=100000)
        result = p.execute_sell("600519", 100, 100.0)
        assert result is False

    def test_sell_too_many(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=100000)
        p.execute_buy("600519", 100, 100.0)
        result = p.execute_sell("600519", 200, 100.0)
        assert result is False

    def test_update_prices(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=100000)
        p.execute_buy("600519", 100, 100.0)
        p.update_prices({"600519": 120.0})
        assert p.positions["600519"].current_price == 120.0

    def test_record_equity(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=100000)
        p.execute_buy("600519", 100, 100.0)
        equity = p.record_equity("2025-01-01")
        assert len(p.equity_history) == 2
        assert equity > 0

    def test_get_allocation(self):
        from backend.quant.portfolio import Portfolio

        p = Portfolio(initial_capital=100000)
        p.execute_buy("600519", 100, 100.0)
        alloc = p.get_allocation()
        assert "600519" in alloc
        assert "_cash" in alloc
        assert abs(sum(alloc.values()) - 100) < 0.01


# ================================================================
# Test Risk Controller
# ================================================================


class TestRiskController:
    """Test risk control rules."""

    def test_validate_buy_within_limits(self):
        from backend.quant.risk_controller import RiskConfig, RiskController

        rc = RiskController(RiskConfig(max_position_pct=30, max_total_exposure_pct=80))
        result = rc.validate_buy("600519", 100, 10.0, 100000, {})
        assert result.allowed is True

    def test_validate_buy_position_too_large(self):
        from backend.quant.risk_controller import RiskConfig, RiskController

        rc = RiskController(RiskConfig(max_position_pct=30))
        # 40% of equity exceeds 30% limit
        result = rc.validate_buy("600519", 400, 10.0, 10000, {})
        assert result.allowed is False
        assert "仓位" in result.reason

    def test_validate_sell_no_position(self):
        from backend.quant.risk_controller import RiskController

        rc = RiskController()
        result = rc.validate_sell("600519", 100, {})
        assert result.allowed is False

    def test_stop_loss_triggered(self):
        from backend.quant.risk_controller import RiskConfig, RiskController

        rc = RiskController(RiskConfig(stop_loss_pct=-10))
        result = rc.check_stop_loss("600519", 100.0, 85.0)
        assert result.allowed is False
        assert "止损" in result.reason

    def test_stop_loss_not_triggered(self):
        from backend.quant.risk_controller import RiskConfig, RiskController

        rc = RiskController(RiskConfig(stop_loss_pct=-10))
        result = rc.check_stop_loss("600519", 100.0, 95.0)
        assert result.allowed is True

    def test_drawdown_triggered(self):
        from backend.quant.risk_controller import RiskConfig, RiskController

        rc = RiskController(RiskConfig(max_drawdown_pct=-20))
        result = rc.check_drawdown([100, 110, 80])
        assert result.allowed is False

    def test_drawdown_not_triggered(self):
        from backend.quant.risk_controller import RiskConfig, RiskController

        rc = RiskController(RiskConfig(max_drawdown_pct=-20))
        result = rc.check_drawdown([100, 110, 105])
        assert result.allowed is True


# ================================================================
# Test Strategies
# ================================================================


class TestStrategies:
    """Test strategy signal generation."""

    def test_macd_strategy_generates_signals(self):
        from backend.quant.strategies import MACDMomentumStrategy

        s = MACDMomentumStrategy()
        signals = s.generate_signals(SAMPLE_BARS)
        assert len(signals) == len(SAMPLE_BARS)  # 与 bars 等长, 暖机位为 hold
        actions = {sig.action for sig in signals}
        assert "hold" in actions

    def test_ma_strategy_generates_signals(self):
        from backend.quant.strategies import MAStrategy

        s = MAStrategy()
        signals = s.generate_signals(SAMPLE_BARS)
        assert len(signals) == len(SAMPLE_BARS)  # 与 bars 等长, 暖机位为 hold

    def test_rsi_strategy_generates_signals(self):
        from backend.quant.strategies import RSIStrategy

        s = RSIStrategy()
        signals = s.generate_signals(SAMPLE_BARS)
        assert len(signals) > 0

    def test_strategy_registry(self):
        from backend.quant.strategies import StrategyRegistry

        strategies = StrategyRegistry.list_strategies()
        names = [s["name"] for s in strategies]
        assert "macd_momentum" in names
        assert "ma_crossover" in names
        assert "rsi_reversal" in names

    def test_strategy_registry_create(self):
        from backend.quant.strategies import StrategyRegistry

        s = StrategyRegistry.create("macd_momentum")
        assert s is not None
        assert s.name == "macd_momentum"

    def test_strategy_registry_create_unknown(self):
        from backend.quant.strategies import StrategyRegistry

        s = StrategyRegistry.create("unknown_strategy")
        assert s is None


# ================================================================
# Test Backtest Engine
# ================================================================


class TestBacktestEngine:
    """Test the core backtesting engine."""

    def test_run_basic(self):
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import MACDMomentumStrategy

        engine = BacktestEngine(initial_capital=100000)
        strategy = MACDMomentumStrategy()
        result = engine.run(strategy, SAMPLE_BARS, "TEST")

        assert result.strategy_name == "macd_momentum"
        assert result.symbol == "TEST"
        assert len(result.equity_curve) > 0
        assert "total_return" in result.performance
        assert "sharpe_ratio" in result.performance
        assert "max_drawdown" in result.performance

    def test_run_with_ma_strategy(self):
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import MAStrategy

        engine = BacktestEngine(initial_capital=100000)
        strategy = MAStrategy()
        result = engine.run(strategy, SAMPLE_BARS, "TEST")

        assert result.strategy_name == "ma_crossover"
        assert result.performance["initial_capital"] == 100000

    def test_run_empty_bars(self):
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import MACDMomentumStrategy

        engine = BacktestEngine()
        result = engine.run(MACDMomentumStrategy(), [], "TEST")
        assert result.equity_curve == [100000]
        assert result.performance == {}

    def test_run_preserves_capital(self):
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import MACDMomentumStrategy

        engine = BacktestEngine(initial_capital=50000)
        strategy = MACDMomentumStrategy()
        result = engine.run(strategy, SAMPLE_BARS, "TEST")

        # Final equity should be reasonable (not zero, not negative)
        final = result.performance.get("final_equity", 0)
        assert final > 0

    def test_run_quick_backtest(self):
        from backend.quant.engine import run_quick_backtest

        result = run_quick_backtest("macd_momentum", SAMPLE_BARS, "TEST")
        assert "error" not in result
        assert "performance" in result

    def test_run_quick_backtest_unknown_strategy(self):
        from backend.quant.engine import run_quick_backtest

        result = run_quick_backtest("unknown", SAMPLE_BARS)
        assert "error" in result

    def test_result_to_dict(self):
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import MACDMomentumStrategy

        engine = BacktestEngine(initial_capital=100000)
        result = engine.run(MACDMomentumStrategy(), SAMPLE_BARS, "TEST")
        d = result.to_dict()

        assert isinstance(d, dict)
        assert "strategy_name" in d
        assert "equity_curve" in d
        assert "performance" in d
        assert "trades" in d


# ================================================================
# Golden exact-value regression net (plan 025, hand-computed)
# ================================================================


class _FixedSignalStrategy(BaseStrategy):
    """Test-only deterministic strategy: emits a pre-set signal per bar index."""

    name = "fixed_signal_golden"
    description = "test fixture: fixed per-bar signal schedule"
    default_params: dict = {}

    def __init__(self, schedule: dict[int, Signal]):
        super().__init__()
        self._schedule = schedule

    def generate_signals(self, bars, portfolio_state=None):
        return [self._schedule.get(i, Signal("hold", "TEST")) for i in range(len(bars))]


GOLDEN_BARS = [
    {
        "date": f"2024-01-{i + 1:02d}",
        "open": 10.0 + 0.5 * i,
        "high": 10.0 + 0.5 * i,
        "low": 10.0 + 0.5 * i,
        "close": 10.0 + 0.5 * i,
        "volume": 1000,
    }
    for i in range(12)
]


def _golden_engine():
    """Zero-friction engine (no commission / stamp / slippage) for hand-computable runs."""
    from backend.quant.constraints import TradingCostModel
    from backend.quant.engine import BacktestEngine

    return BacktestEngine(
        initial_capital=100000,
        commission_rate=0.0,
        cost_model=TradingCostModel(
            commission_rate=0.0,
            commission_min=0.0,
            stamp_duty_rate=0.0,
            slippage_rate=0.0,
        ),
    )


class TestBacktestEngineGolden:
    """手算精确值回归网 —— 零摩擦确定性场景锁定引擎记账与指标口径。

    plan 003 会改信号对齐/指标口径，届时本测试的期望值必须随 plan 003
    有意更新；若 plan 003 合并后本测试仍全绿，需人工确认修复未影响本
    场景或期望值已同步。
    """

    def test_golden_run_hand_computed(self):
        # 手算推导（engine.py 当前语义，execution_price="open" 次日开盘成交）:
        # 1) 12 根 K 线 2024-01-01..2024-01-12, open=close=10.0+0.5*i, 无涨跌停
        # 2) bar0 生成 BUY 100 股 -> bar1 开盘 10.5 成交:
        #    cash = 100000 - 100*10.5 = 98950, 持仓 100 股 @ 10.5
        # 3) bar1 起每日按收盘标记市值:
        #    equity = 98950 + 100*close = 100000, 100050, 100100, ...
        #    (bar2..bar10 收盘 11.0..15.0 -> 100050..100450)
        # 4) bar10 生成 SELL -> bar11 开盘 15.5 全部卖出:
        #    proceeds = 1550, cash = 100500, pnl = (15.5-10.5)*100 = 500
        # 5) total_return = (100500-100000)/100000*100 = 0.5 (%),
        #    final_equity = 100500, trades = 2 (buy@10.5 / sell@15.5)
        engine = _golden_engine()
        schedule = {
            0: Signal("buy", "TEST", shares=100),
            10: Signal("sell", "TEST"),
        }
        result = engine.run(_FixedSignalStrategy(schedule), GOLDEN_BARS, "TEST")

        assert result.strategy_name == "fixed_signal_golden"
        assert result.symbol == "TEST"
        assert result.equity_curve == pytest.approx(
            [
                100000,
                100000,
                100000,
                100050,
                100100,
                100150,
                100200,
                100250,
                100300,
                100350,
                100400,
                100450,
                100500,
            ]
        )
        assert result.dates == [f"2024-01-{i + 1:02d}" for i in range(12)]
        assert len(result.trades) == 2
        assert result.trades[0] == {
            "symbol": "TEST",
            "side": "buy",
            "shares": 100,
            "price": 10.5,
            "commission": 0.0,
            "pnl": 0.0,
            "timestamp": "2024-01-02",
        }
        assert result.trades[1] == {
            "symbol": "TEST",
            "side": "sell",
            "shares": 100,
            "price": 15.5,
            "commission": 0.0,
            "pnl": 500.0,
            "timestamp": "2024-01-12",
        }
        assert result.performance["total_return"] == pytest.approx(0.5)
        assert result.performance["final_equity"] == pytest.approx(100500.0)
        assert result.performance["total_trades"] == 2
        assert result.performance["trading_days"] == 12
        assert result.performance["win_rate"] == pytest.approx(100.0)
        assert result.performance["max_drawdown"] == pytest.approx(0.0)
        # 023 合并后非有限值统一为 None（06182ca 时为 float("inf")）
        assert result.performance["profit_factor"] is None
        assert result.risk_violations == []

    def test_engine_accounting_identity(self):
        """记账恒等式: final_equity == cash + Σ(shares_i * price_i)。

        引擎结果不直接暴露 cash/持仓，改为由 trades + 末根收盘价重建
        现金与持仓，再与 equity_curve[-1]（每点为标记市值）比对。
        """
        from backend.quant.strategies import MACDMomentumStrategy

        initial_capital = 100000
        engine = _golden_engine()
        result = engine.run(MACDMomentumStrategy(), SAMPLE_BARS, "TEST")

        assert result.equity_curve[0] == pytest.approx(initial_capital)
        assert len(result.equity_curve) == len(SAMPLE_BARS) + 1

        last_close_by_symbol: dict[str, float] = {}
        for bar in reversed(SAMPLE_BARS):
            sym = bar.get("symbol", "")
            if sym not in last_close_by_symbol:
                last_close_by_symbol[sym] = bar["close"]

        cash = float(initial_capital)
        shares_by_symbol: dict[str, int] = {}
        for t in result.trades:
            sym = t["symbol"]
            if t["side"] == "buy":
                cash -= t["price"] * t["shares"] + t["commission"]
                shares_by_symbol[sym] = shares_by_symbol.get(sym, 0) + t["shares"]
            else:
                cash += t["price"] * t["shares"] - t["commission"]
                shares_by_symbol[sym] = shares_by_symbol.get(sym, 0) - t["shares"]

        reconstructed = cash + sum(s * last_close_by_symbol[sym] for sym, s in shares_by_symbol.items() if s > 0)
        assert reconstructed == pytest.approx(result.equity_curve[-1], rel=1e-9)
        assert reconstructed == pytest.approx(result.performance["final_equity"], rel=1e-9)


# ================================================================
# Test API Endpoints
# ================================================================


class TestBacktestAPI:
    """Test the /api/quant/* API endpoints."""

    @pytest.fixture
    def client(self):
        pytest.importorskip("fastapi")
        pytest.importorskip("httpx")
        from fastapi.testclient import TestClient
        from backend.api.main import app

        return TestClient(app)

    def test_list_strategies(self, client):
        resp = client.get("/api/quant/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] in {True, False}
        strategies = data["data"].get("strategies", data["data"])
        assert isinstance(strategies, list)
        names = [s["name"] for s in strategies]
        assert "macd_momentum" in names

    def test_get_strategy(self, client):
        resp = client.get("/api/quant/strategies/macd_momentum")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "macd_momentum"

    def test_get_strategy_not_found(self, client):
        resp = client.get("/api/quant/strategies/nonexistent")
        assert resp.status_code == 404

    def test_list_builtin_strategies(self, client):
        resp = client.get("/api/quant/builtin-strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert len(data["data"]) >= 3
