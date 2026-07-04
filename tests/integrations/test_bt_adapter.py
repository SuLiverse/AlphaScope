"""bt Adapter 测试 (Phase B #2 / §9.4).

覆盖:
1. 纯函数组 (始终跑): bars_to_price_df / build_assumptions / extract_bt_stats
2. bt 执行路径 (skipif; 未装跳过): adapter 健康检查 / 自动发现 / run_backtest
3. 元数据 + 边界 (始终跑)

合规: 测试只校验回测归一化与边界, 不涉及任何买卖指令。
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.integrations.backtest.bt_adapter import (
    BtAdapter,
    bars_to_price_df,
    build_assumptions,
    extract_bt_stats,
)
from backend.integrations.schemas import BacktestMetrics, HealthStatus, LicenseSafety


def _bars_multi(n: int = 60, n_assets: int = 2) -> list[dict]:
    """造多标的 OHLCV bars (含 symbol 字段)。"""
    base = date(2023, 1, 1)
    out = []
    for i in range(n):
        for j in range(n_assets):
            sym = f"SYM{j}"
            out.append(
                {
                    "date": (base + timedelta(days=i)).isoformat(),
                    "symbol": sym,
                    "close": 100 + i + j * 5,
                }
            )
    return out


# ============================================================
# 1. 纯函数组 (始终跑)
# ============================================================


def test_bars_to_price_df_single_asset():
    if pd is None:
        pytest.skip("pandas 未装")
    bars = [
        {"date": "2024-01-01", "close": 100},
        {"date": "2024-01-02", "close": 101},
    ]
    df = bars_to_price_df(bars, symbols=["A"])
    assert df.shape == (2, 1)
    assert "A" in df.columns


def test_bars_to_price_df_multi_asset_pivot():
    if pd is None:
        pytest.skip("pandas 未装")
    df = bars_to_price_df(_bars_multi(10, 2))
    assert df.shape[0] == 10  # 10 个交易日
    assert set(df.columns) == {"SYM0", "SYM1"}


def test_bars_to_price_df_empty_safe():
    assert len(bars_to_price_df([])) == 0


def test_bars_to_price_df_renames_chinese():
    if pd is None:
        pytest.skip("pandas 未装")
    bars = [{"日期": "2024-01-01", "收盘": 100}]
    df = bars_to_price_df(bars, symbols=["X"])
    assert len(df) == 1


def test_build_assumptions_honestly_discloses_unmodeled_as_frictions():
    a = build_assumptions(engine_name="bt")
    assert a.engine_name == "bt"
    assert a.price_limit_filter is False
    assert "T+1" in (a.note or "")
    assert "印花税" in (a.note or "")
    assert "涨跌停" in (a.note or "")


def test_extract_bt_stats_empty_safe():
    m = extract_bt_stats(None)
    assert isinstance(m, BacktestMetrics)
    assert m.sharpe is None


def test_extract_bt_stats_from_series():
    """构造类 bt.stats 的 Series, 验证抽取 + 单位转换 (bt 返回小数, 我们转 %)。"""
    stats = pd.Series(
        {
            "total_return": 0.25,  # 25%
            "daily_sharpe": 1.5,
            "daily_sortino": 1.8,
            "max_drawdown": -0.15,  # -15%
            "calmar": 2.1,
            "cagr": 0.12,  # 12%
            "daily_vol": 0.18,  # 18%
        }
    )
    m = extract_bt_stats(stats)
    assert m.total_return == 25.0  # 转成 %
    assert m.sharpe == 1.5
    assert m.max_drawdown == -15.0
    assert m.annual_return == 12.0
    assert m.volatility == 18.0


def test_extract_bt_stats_nan_filtered():
    stats = pd.Series({"daily_sharpe": float("nan"), "total_return": None})
    m = extract_bt_stats(stats)
    assert m.sharpe is None
    assert m.total_return is None


# ============================================================
# 2. 元数据 + 边界 (始终跑)
# ============================================================


def test_bt_metadata_and_boundary():
    a = BtAdapter()
    meta = a.metadata()
    assert meta.name == "bt"
    assert meta.allow_live_order is False
    assert meta.license_safety == LicenseSafety.SAFE
    assert meta.license_name == "Apache-2.0"
    for cap in meta.capabilities:
        low = cap.name.lower()
        for tok in ("submit_order", "place_order", "live"):
            assert tok not in low


def test_bt_autodiscovered_by_registry():
    from backend.integrations.registry import IntegrationRegistry, autodiscover

    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    assert reg.has("bt")


def test_bt_healthcheck_reports_availability():
    a = BtAdapter()
    h = a.healthcheck()
    assert h.status in (HealthStatus.HEALTHY, HealthStatus.UNAVAILABLE)


def test_run_backtest_failure_safe_when_unavailable():
    a = BtAdapter()
    res = a.run_backtest("s1", ["SYM0"], "2024-01-01", "2024-06-30", bars=_bars_multi(30, 1))
    assert res.engine_name == "bt"
    assert res.research_only is True


# ============================================================
# 3. bt 执行路径 (skipif; 未装整组跳过)
# ============================================================

try:
    import bt as _bt_mod  # noqa: F401

    _HAS_BT = True
except Exception:
    _HAS_BT = False

_bt_required = pytest.mark.skipif(not _HAS_BT, reason="bt 未安装, 跳过执行路径用例")


@_bt_required
def test_run_backtest_with_real_bt_returns_result():
    """装了 bt: 多标的组合回测应跑出结果 (research_only=True, engine=bt)。"""
    a = BtAdapter()
    # 直接传 prices DataFrame (更接近 bt 原生用法)
    np.random.seed(42)
    prices = pd.DataFrame(
        {
            "A": 100 * np.cumprod(1 + np.random.normal(0.001, 0.02, 100)),
            "B": 100 * np.cumprod(1 + np.random.normal(0.0008, 0.025, 100)),
        },
        index=pd.bdate_range("2024-01-01", periods=100),
    )
    res = a.run_backtest(
        strategy_id="ew_monthly",
        symbols=["A", "B"],
        start="2024-01-01",
        end="2024-06-30",
        prices=prices,
        init_cash=1_000_000,
    )
    assert res.engine_name == "bt"
    assert res.research_only is True
    assert res.assumptions.engine_name == "bt"
    assert len(res.equity_curve) > 0
