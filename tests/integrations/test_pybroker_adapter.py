"""PyBroker Adapter 测试 (Phase 2 第六个 adapter, §9.4).

分两组:
1. 纯函数组 (始终跑): bars_to_pybroker_df / build_assumptions / extract_pybroker_metrics
2. pybroker 执行路径 (skipif; 未装跳过): adapter 健康检查 / 自动发现 / run_backtest

合规: 测试只校验回测归一化与边界, 不涉及任何买卖指令。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from backend.integrations.backtest.pybroker_adapter import (
    PybrokerAdapter,
    bars_to_pybroker_df,
    build_assumptions,
    extract_pybroker_metrics,
)
from backend.integrations.schemas import BacktestMetrics, HealthStatus, LicenseSafety


def _bars(n: int, start: float = 10.0) -> list[dict]:
    base = date(2023, 1, 1)
    return [
        {
            "date": (base + timedelta(days=i)).isoformat(),
            "open": start + i,
            "high": start + i + 1,
            "low": start + i - 0.5,
            "close": start + i + 0.5,
            "volume": 1000 + i,
        }
        for i in range(n)
    ]


# ============================================================
# 1. 纯函数组 (始终跑)
# ============================================================


def test_bars_to_pybroker_df_basic():
    if pd is None:
        pytest.skip("pandas 未装")
    df = bars_to_pybroker_df(_bars(5), symbol="TEST")
    assert len(df) == 5
    # PyBroker 要求的列
    for col in ("date", "symbol", "open", "high", "low", "close"):
        assert col in df.columns
    assert (df["symbol"] == "TEST").all()
    assert pd.api.types.is_datetime64_any_dtype(df["date"])


def test_bars_to_pybroker_df_empty_safe():
    df = bars_to_pybroker_df([])
    assert len(df) == 0


def test_bars_to_pybroker_df_renames_chinese_columns():
    if pd is None:
        pytest.skip("pandas 未装")
    bars = [
        {
            "日期": "2024-01-01",
            "开盘": 10,
            "最高": 11,
            "最低": 9,
            "收盘": 10.5,
            "成交量": 1000,
        }
    ]
    df = bars_to_pybroker_df(bars, symbol="X")
    assert len(df) == 1
    assert "close" in df.columns


def test_build_assumptions_honestly_discloses_unmodeled_as_frictions():
    a = build_assumptions(engine_name="pybroker", buy_delay=1, sell_delay=1)
    assert a.engine_name == "pybroker"
    assert a.price_limit_filter is False
    assert "T+1" in (a.note or "")
    assert "印花税" in (a.note or "")
    assert "涨跌停" in (a.note or "")
    assert "buy_delay=1" in (a.settlement_rule or "")


def test_extract_pybroker_metrics_empty_safe():
    """None/空 metrics → 空 BacktestMetrics。"""
    m = extract_pybroker_metrics(None)
    assert isinstance(m, BacktestMetrics)
    assert m.sharpe is None


def test_extract_pybroker_metrics_from_object():
    """构造类 EvalMetrics 对象, 验证抽取。"""

    class FakeMetrics:
        sharpe = 1.3
        sortino = 1.8
        max_drawdown_pct = -8.5
        total_return_pct = 15.2
        win_rate = 60.0
        profit_factor = 2.1

    m = extract_pybroker_metrics(FakeMetrics())
    assert m.sharpe == 1.3
    assert m.max_drawdown == -8.5
    assert m.total_return == 15.2
    assert m.win_rate == 60.0


def test_extract_pybroker_metrics_nan_filtered():
    """NaN/inf 被过滤成 None。"""

    class FakeMetrics:
        sharpe = float("nan")
        sortino = float("inf")

    m = extract_pybroker_metrics(FakeMetrics())
    assert m.sharpe is None
    assert m.sortino is None


# ============================================================
# 2. 元数据 + 边界 (始终跑)
# ============================================================


def test_pybroker_metadata_and_boundary():
    a = PybrokerAdapter()
    meta = a.metadata()
    assert meta.name == "pybroker"
    assert meta.allow_live_order is False
    assert meta.license_safety == LicenseSafety.SAFE
    assert meta.license_name == "Apache-2.0"
    # package 字段标注 PyPI 真实包名 lib-pybroker (易踩坑点)
    assert meta.package == "lib-pybroker"
    for cap in meta.capabilities:
        low = cap.name.lower()
        for tok in ("submit_order", "place_order", "live"):
            assert tok not in low


def test_pybroker_autodiscovered_by_registry():
    from backend.integrations.registry import IntegrationRegistry, autodiscover

    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    assert reg.has("pybroker")


def test_pybroker_healthcheck_reports_availability():
    a = PybrokerAdapter()
    h = a.healthcheck()
    assert h.status in (HealthStatus.HEALTHY, HealthStatus.UNAVAILABLE)


def test_run_backtest_failure_safe_when_unavailable():
    a = PybrokerAdapter()
    res = a.run_backtest("s1", ["000001"], "2024-01-01", "2024-06-30", bars=_bars(30))
    assert res.engine_name == "pybroker"
    assert res.research_only is True


# ============================================================
# 3. pybroker 执行路径 (skipif; 未装整组跳过)
# ============================================================

try:
    import pybroker as _pb  # noqa: F401

    _HAS_PB = True
except Exception:
    _HAS_PB = False

_pb_required = pytest.mark.skipif(not _HAS_PB, reason="lib-pybroker 未安装, 跳过执行路径用例")


@_pb_required
def test_run_backtest_with_real_pybroker_returns_result():
    """装了 pybroker: 单调上涨序列应能跑出结果 (research_only=True, engine=pybroker)。"""
    a = PybrokerAdapter()
    res = a.run_backtest(
        strategy_id="ma_rule",
        symbols=["DEMO"],
        start="2023-01-01",
        end="2023-06-30",
        bars=_bars(60),
        fast=5,
        slow=20,
    )
    assert res.engine_name == "pybroker"
    assert res.research_only is True
    assert res.assumptions.engine_name == "pybroker"
    # 至少有首末权益点 (若 backtest 产出 portfolio)
    assert isinstance(res.equity_curve, list)
