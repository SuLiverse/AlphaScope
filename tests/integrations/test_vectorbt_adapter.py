"""vectorBT Adapter 测试 (Phase 2 第一个真实 adapter).

分两组:
1. **纯函数组 (始终跑)**: bars_to_close_series / build_ma_cross_signals /
   parse_param_grid / build_assumptions / map_vbt_stats_to_metrics —— 这些函数
   不依赖 vectorbt, 验证信号生成 / 假设卡诚实披露 / 网格解析 / 失败安全。
2. **vectorbt 组 (importorskip)**: adapter 健康检查 / 自动发现 / 单次回测 /
   参数扫描的端到端路径。vectorbt 未装时整组跳过 (CI 无 vectorbt 仍确定性通过)。

合规: 测试只校验历史回测的归一化结构与边界不变量, 不涉及任何买卖指令。
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backend.integrations.backtest.vectorbt_adapter import (
    VectorbtAdapter,
    annualized_sharpe_from_returns,
    bars_to_close_series,
    build_assumptions,
    build_ma_cross_signals,
    count_param_trials,
    equity_curve_returns,
    map_vbt_stats_to_metrics,
    parse_param_grid,
)
from backend.integrations.schemas import HealthStatus, LicenseSafety


# ============================================================
# 1. 纯函数组 (始终跑, 不依赖 vectorbt)
# ============================================================


def _bars(n: int, start: float = 10.0) -> list[dict]:
    """造 n 根单调上涨的 bar, 保证 ma_cross 能产生信号。

    日期从 2023-01-01 起按日递增 (用合法日期序列, 避免 to_datetime 解析失败)。
    """
    from datetime import date, timedelta

    base = date(2023, 1, 1)
    return [
        {
            "date": (base + timedelta(days=i)).isoformat(),
            "close": start + i,
            "open": start + i - 0.5,
        }
        for i in range(n)
    ]


def test_bars_to_close_series_basic():
    s = bars_to_close_series(_bars(5))
    assert len(s) == 5
    assert float(s.iloc[0]) == 10.0


def test_bars_to_close_series_empty_is_safe():
    s = bars_to_close_series([])
    assert len(s) == 0


def test_bars_to_close_series_skips_garbage():
    bars = [
        {"date": "2024-01-01", "close": 10.0},
        {"date": "2024-01-02", "close": "garbage"},  # 跳过
        {"date": "2024-01-03"},  # 跳过 (缺 close)
        {"date": "2024-01-04", "close": 13.0},
    ]
    s = bars_to_close_series(bars)
    assert len(s) == 2


def test_build_ma_cross_signals_insufficient_data():
    """数据长度 <= slow 时不产生任何信号 (失败安全)。"""
    entries, exits = build_ma_cross_signals(bars_to_close_series(_bars(5)), fast=3, slow=20)
    assert not entries.any()
    assert not exits.any()


def test_build_ma_cross_signals_invalid_params():
    """fast >= slow 或 fast <= 0 时不产生信号。"""
    close = bars_to_close_series(_bars(60))
    e1, x1 = build_ma_cross_signals(close, fast=20, slow=10)  # fast >= slow
    assert not e1.any()
    e2, x2 = build_ma_cross_signals(close, fast=0, slow=10)  # fast <= 0
    assert not e2.any()


def test_build_ma_cross_signals_produces_entries_on_trend():
    """单调上涨序列里 fast 线恒在 slow 线上方 → 开仓产生至少一次 entry。"""
    close = bars_to_close_series(_bars(40))
    entries, _ = build_ma_cross_signals(close, fast=5, slow=20)
    assert entries.any()


def test_ma_cross_executes_one_bar_after_close_decision_without_lookahead():
    index = pd.date_range("2024-01-01", periods=6, freq="D")
    close = pd.Series([3.0, 2.0, 1.0, 2.0, 4.0, 5.0], index=index)
    changed_execution_bar = pd.Series([3.0, 2.0, 1.0, 2.0, 4.0, -100.0], index=index)

    entries, _ = build_ma_cross_signals(close, fast=2, slow=3)
    changed_entries, _ = build_ma_cross_signals(changed_execution_bar, fast=2, slow=3)

    # The cross is known at index[4], but vectorbt receives the order only at
    # index[5].  Changing close[5] cannot change the already-decided order.
    assert not entries.loc[index[4]]
    assert entries.loc[index[5]]
    assert changed_entries.loc[index[5]]


def test_parse_param_grid_list_and_scalar():
    grid = parse_param_grid({"fast": [5, 10], "slow": 20})
    assert grid["fast"] == [5, 10]
    assert grid["slow"] == [20]


def test_parse_param_grid_non_dict_returns_empty():
    assert parse_param_grid(None) == {}
    assert parse_param_grid("not a dict") == {}


def test_count_param_trials_uses_only_valid_ma_pairs():
    assert count_param_trials({"fast": [5, 20], "slow": [10, 30]}) == 3
    assert count_param_trials() == 11


def test_equity_curve_returns_accepts_normalized_points():
    returns = equity_curve_returns([{"value": 100.0}, {"value": 110.0}, {"value": 99.0}])
    assert returns == pytest.approx([0.1, -0.1])


def test_sharpe_stock_daily_annualization_defaults_to_252():
    returns = [0.01, -0.004, 0.006, -0.002, 0.003]
    one_period = annualized_sharpe_from_returns(returns, periods_per_year=1)
    default_daily = annualized_sharpe_from_returns(returns)
    calendar_daily = annualized_sharpe_from_returns(returns, periods_per_year=365)

    assert default_daily == pytest.approx(one_period * math.sqrt(252))
    assert calendar_daily == pytest.approx(one_period * math.sqrt(365))


def test_build_assumptions_honestly_discloses_unmodeled_as_frictions():
    """假设卡必须显式标注 vectorbt 未模拟 A 股 T+1/印花税/涨跌停 (想法 #4)。"""
    a = build_assumptions("vectorbt", fees=0.0003)
    assert a.engine_name == "vectorbt"
    assert a.commission_rate == 0.0003
    assert a.stamp_duty_rate is None  # 未模拟
    assert a.price_limit_filter is False  # 未模拟涨跌停
    assert "T+1" in (a.note or "")
    assert "印花税" in (a.note or "")
    assert "涨跌停" in (a.note or "")
    assert "close[t+1]" in (a.execution_price or "")
    assert "252" in (a.note or "")


def test_map_vbt_stats_to_metrics_from_dict():
    """stats 是 dict 时也能容错抽取。"""
    m = map_vbt_stats_to_metrics({"Total Return [%]": 12.3, "Sharpe Ratio": 1.5, "Max Drawdown [%]": -8.0})
    assert m.total_return == 12.3
    assert m.sharpe == 1.5
    assert m.max_drawdown == -8.0


def test_map_vbt_stats_to_metrics_missing_fields_are_none():
    m = map_vbt_stats_to_metrics({})
    assert m.total_return is None
    assert m.sharpe is None


def test_map_vbt_stats_to_metrics_garbage_is_safe():
    m = map_vbt_stats_to_metrics({"Sharpe Ratio": "not a number"})
    assert m.sharpe is None


# ============================================================
# 2. 元数据 + 边界 (始终跑, 不依赖 vectorbt)
# ============================================================


def test_vectorbt_metadata_and_boundary():
    """adapter 元数据 + 交易边界 + 许可证防火墙。"""
    a = VectorbtAdapter()
    meta = a.metadata()
    assert meta.name == "vectorbt"
    assert meta.allow_live_order is False
    assert meta.license_safety == LicenseSafety.SAFE
    assert meta.license_name == "Apache-2.0"
    assert meta.code_copy_allowed is True
    # 不暴露任何实盘下单能力
    cap_names = {c.name for c in meta.capabilities}
    assert "run_backtest" in cap_names
    assert "param_sweep" in cap_names
    for name in cap_names:
        low = name.lower()
        for tok in ("submit_order", "place_order", "live"):
            assert tok not in low


def test_vectorbt_autodiscovered_by_registry():
    """autodiscover 应发现 vectorbt adapter (与 demo 一起)。"""
    from backend.integrations.registry import IntegrationRegistry, autodiscover

    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    assert reg.has("vectorbt")


def test_vectorbt_healthcheck_reports_availability():
    """vectorbt 未装时 UNAVAILABLE, 装了 HEALTHY; 不抛错。"""
    a = VectorbtAdapter()
    h = a.healthcheck()
    assert h.status in (HealthStatus.HEALTHY, HealthStatus.UNAVAILABLE)


# ============================================================
# 3. vectorbt 执行路径 (仅本组跳过; 纯函数组始终跑)
# ============================================================

# 用 skipif 标记每个执行路径用例, 而非模块级 importorskip —— 否则会把上面所有
# 纯函数用例也一并跳过 (vectorbt 未装时整文件 0 跑)。
try:
    import vectorbt as _vbt  # noqa: F401

    _HAS_VBT = True
except Exception:
    _HAS_VBT = False

_vbt_required = pytest.mark.skipif(not _HAS_VBT, reason="vectorbt 未安装, 跳过执行路径用例")


@_vbt_required
def test_run_backtest_returns_normalized_result():
    a = VectorbtAdapter()
    bars = _bars(60)
    res = a.run_backtest(
        strategy_id="ma_cross",
        symbols=["000001"],
        start="2024-01-01",
        end="2024-03-01",
        bars=bars,
        fast=5,
        slow=20,
        fees=0.0003,
    )
    assert res.engine_name == "vectorbt"
    assert res.research_only is True
    assert res.assumptions.engine_name == "vectorbt"
    # 单调上涨序列应有非空权益曲线
    assert len(res.equity_curve) > 0
    assert "close[t+1]" in (res.assumptions.execution_price or "")


@_vbt_required
def test_run_backtest_sharpe_uses_explicit_periods_per_year():
    adapter = VectorbtAdapter()
    kwargs = {
        "strategy_id": "ma_cross",
        "symbols": ["000001"],
        "start": "2024-01-01",
        "end": "2024-03-01",
        "bars": _bars(60),
        "fast": 5,
        "slow": 20,
        "fees": 0.0,
    }

    stock_daily = adapter.run_backtest(**kwargs)
    calendar_daily = adapter.run_backtest(**kwargs, periods_per_year=365)

    assert stock_daily.metrics.sharpe is not None
    assert calendar_daily.metrics.sharpe is not None
    assert calendar_daily.metrics.sharpe == pytest.approx(
        stock_daily.metrics.sharpe * math.sqrt(365 / 252),
        rel=1e-12,
    )


@_vbt_required
def test_param_sweep_ranks_and_caps_top_n():
    a = VectorbtAdapter()
    bars = _bars(60)
    results = a.param_sweep(
        bars=bars,
        param_grid={"fast": [3, 5], "slow": [10, 20]},
        metric="sharpe",
        top_n=3,
    )
    assert 0 < len(results) <= 3
    # 每条都有 params + metrics
    for r in results:
        assert "params" in r and "metrics" in r
        assert "fast" in r["params"] and "slow" in r["params"]
        assert "probabilistic_sharpe" in r["metrics"]
        assert "deflated_sharpe" in r["metrics"]
        assert r["n_trials"] == 4
        assert r["observations"] > 0
        assert r["metrics"]["sharpe_periods_per_year"] == 252
        assert r["metrics"]["dsr_benchmark_source"] == "candidate_sharpes"
        # DSR is based on all four grid candidates, even though top_n returns 3.
        assert r["metrics"]["candidate_sharpe_count"] == 4


@_vbt_required
def test_param_sweep_empty_when_insufficient_data():
    a = VectorbtAdapter()
    # 数据不足 -> 每组返回空 metrics, 但结果列表本身按结构返回 (过滤后)
    results = a.param_sweep(bars=_bars(5), top_n=5)
    assert isinstance(results, list)
