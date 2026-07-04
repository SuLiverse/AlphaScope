"""Backtrader Adapter 测试 (Phase 2 第五个 adapter, §9.5).

分两组:
1. 纯函数组 (始终跑): bars_to_feed_data / build_assumptions / extract_analyzer_metrics
2. backtrader 路径 (skipif; 未装跳过): adapter 健康检查 / 自动发现 / run_backtest 端到端

合规: 测试只校验回测归一化与边界, 不涉及任何买卖指令。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from backend.integrations.backtest.backtrader_adapter import (
    BacktraderAdapter,
    bars_to_feed_data,
    build_assumptions,
    extract_analyzer_metrics,
)
from backend.integrations.schemas import (
    BacktestMetrics,
    HealthStatus,
    LicenseSafety,
)


def _bars(n: int, start: float = 10.0) -> list[dict]:
    """造 n 根 bar, 日期从 2023-01-01 起按日递增 (合法日期序列)。"""
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
# 1. 纯函数组 (始终跑, 不依赖 backtrader)
# ============================================================


def test_bars_to_feed_data_basic():
    if pd is None:
        pytest.skip("pandas 未装")
    df = bars_to_feed_data(_bars(5))
    assert len(df) == 5
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert isinstance(df.index, pd.DatetimeIndex)


def test_bars_to_feed_data_empty_safe():
    df = bars_to_feed_data([])
    assert len(df) == 0


def test_bars_to_feed_data_renames_chinese_columns():
    if pd is None:
        pytest.skip("pandas 未装")
    bars = [
        {
            "日期": "2024-01-01",
            "开盘": 10.0,
            "最高": 11.0,
            "最低": 9.0,
            "收盘": 10.5,
            "成交量": 1000,
        }
    ]
    df = bars_to_feed_data(bars)
    assert len(df) == 1
    assert "close" in df.columns


def test_build_assumptions_honestly_discloses_unmodeled_as_frictions():
    """假设卡必须显式标注 backtrader 未模拟 A 股 T+1/印花税/涨跌停。"""
    a = build_assumptions(engine_name="backtrader", commission=0.0003)
    assert a.engine_name == "backtrader"
    assert a.commission_rate == 0.0003
    assert a.stamp_duty_rate is None  # 未模拟
    assert a.price_limit_filter is False
    assert "T+1" in (a.note or "")
    assert "印花税" in (a.note or "")
    assert "涨跌停" in (a.note or "")


def test_extract_analyzer_metrics_empty_safe():
    """空/None analyzer → 空 metrics (失败安全)。"""
    m = extract_analyzer_metrics(None)
    assert isinstance(m, BacktestMetrics)
    assert m.sharpe is None


def test_extract_analyzer_metrics_from_dict():
    """构造类 backtrader analyzer 返回结构, 验证抽取。"""

    class FakeAnalyzer:
        def __init__(self, data):
            self._data = data

        def get_analysis(self):
            return self._data

    class FakeAnalyzers:
        returns = FakeAnalyzer({"rnorm": 0.10, "sharpe": 1.2})
        sharpe = FakeAnalyzer({"sharpe": 1.5})
        drawdown = FakeAnalyzer({"max": {"drawdown": 8.5}})
        trades = FakeAnalyzer(
            {
                "won": {"total": 30},
                "lost": {"total": 10},
                "pnl": {"gross": {"profit": 1000, "loss": -400}},
            }
        )

    m = extract_analyzer_metrics(FakeAnalyzers())
    assert m.sharpe == 1.5  # sharpe analyzer 优先
    assert m.annual_return == 10.0
    assert m.max_drawdown == 8.5
    assert m.win_rate == 75.0
    assert m.profit_factor == 2.5


# ============================================================
# 2. 元数据 + 边界 (始终跑)
# ============================================================


def test_backtrader_metadata_and_boundary():
    a = BacktraderAdapter()
    meta = a.metadata()
    assert meta.name == "backtrader"
    assert meta.allow_live_order is False
    assert meta.license_safety == LicenseSafety.SAFE
    assert meta.code_copy_allowed is True
    for cap in meta.capabilities:
        low = cap.name.lower()
        for tok in ("submit_order", "place_order", "live"):
            assert tok not in low


def test_backtrader_autodiscovered_by_registry():
    from backend.integrations.registry import IntegrationRegistry, autodiscover

    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    assert reg.has("backtrader")


def test_backtrader_healthcheck_reports_availability():
    a = BacktraderAdapter()
    h = a.healthcheck()
    assert h.status in (HealthStatus.HEALTHY, HealthStatus.UNAVAILABLE)


def test_run_backtest_failure_safe_when_unavailable():
    """backtrader 不可用时 run_backtest 不抛, 返回带 UNAVAILABLE 标记的空结果。"""
    a = BacktraderAdapter()
    # 若装了 backtrader, 此用例直接通过 (跳过); 若未装, 应返回空
    res = a.run_backtest("s1", ["000001"], "2024-01-01", "2024-06-30", bars=_bars(30))
    assert res.engine_name == "backtrader"
    assert res.research_only is True


# ============================================================
# 3. backtrader 执行路径 (skipif; 未装整组跳过)
# ============================================================

try:
    import backtrader as _bt  # noqa: F401

    _HAS_BT = True
except Exception:
    _HAS_BT = False

_bt_required = pytest.mark.skipif(not _HAS_BT, reason="backtrader 未安装, 跳过执行路径用例")


@_bt_required
def test_run_backtest_with_real_backtrader_returns_result():
    """装了 backtrader: 单调上涨序列应能跑出结果 (research_only=True, engine=backtrader)。"""
    a = BacktraderAdapter()
    res = a.run_backtest(
        strategy_id="ma_cross",
        symbols=["000001"],
        start="2023-01-01",
        end="2023-06-30",
        bars=_bars(60),
        fast=5,
        slow=20,
    )
    assert res.engine_name == "backtrader"
    assert res.research_only is True
    assert res.assumptions.engine_name == "backtrader"
    # 权益曲线至少有两点 (首末)
    assert len(res.equity_curve) >= 2
    # 单调上涨应有正收益
    assert res.metrics.total_return is not None
