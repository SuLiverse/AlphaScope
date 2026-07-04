"""组合优化测试 / Portfolio Optimizer Hub (Phase B #5/#6/#7).

覆盖:
1. 纯函数 (始终跑): normalize_returns_input / equal_weight / build_rebalance_draft
2. 优化器路径 (装了): skfolio/riskfolio/pypfopt 三选一能跑出 max_sharpe
3. 降级路径: 全部优化器不可用 → 等权兜底 + degraded
4. 边界: 数据不足/单资产/非法 method

合规: 测试只校验优化输出结构与边界, 所有结果 forbidden_live_order=True。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend import portfolio_optimizer as po


def _good_returns(n_assets: int = 4, n_periods: int = 252) -> pd.DataFrame:
    """造 n_assets × n_periods 的收益 DataFrame (有信号, 优化器能解)。"""
    np.random.seed(42)
    return pd.DataFrame(
        {f"A{i}": np.random.normal(0.001 + i * 0.0003, 0.02 - i * 0.002, n_periods) for i in range(n_assets)}
    )


# ============================================================
# 1. 纯函数 (始终跑)
# ============================================================


def test_equal_weight_basic():
    w = po.equal_weight(4)
    assert len(w) == 4
    assert all(abs(v - 0.25) < 1e-6 for v in w.values())


def test_equal_weight_zero_safe():
    assert po.equal_weight(0) == {}
    assert po.equal_weight(-1) == {}


def test_normalize_returns_dataframe_passthrough():
    df = _good_returns(3, 50)
    out = po.normalize_returns_input(df)
    assert out is df  # DataFrame 直接返回


def test_normalize_returns_from_list():
    data = [[0.01, 0.02], [0.0, -0.01]]
    df = po.normalize_returns_input(data, asset_names=["X", "Y"])
    assert df is not None
    assert list(df.columns) == ["X", "Y"]


def test_normalize_returns_none_safe():
    assert po.normalize_returns_input(None) is None


def test_build_rebalance_draft_structure_and_normalizes():
    """草案应归一化权重 + 标 research_only/forbidden_live_order。"""
    draft = po.build_rebalance_draft(
        {"A": 0.6, "B": 0.6},  # 和 1.2, 应被归一化到 0.5/0.5
        method="max_sharpe",
        total_value=1_000_000,
    )
    assert draft["target_weights"]["A"] == pytest.approx(0.5)
    assert draft["target_weights"]["B"] == pytest.approx(0.5)
    assert draft["research_only"] is True
    assert draft["forbidden_live_order"] is True
    assert draft["total_value"] == 1_000_000
    assert "不自动下单" in draft["disclaimer"]


def test_build_rebalance_draft_zero_total_safe():
    """权重全 0 时 total=0, 归一化后全 0 (失败安全)。"""
    draft = po.build_rebalance_draft({"A": 0, "B": 0}, "min_variance")
    assert all(v == 0.0 for v in draft["target_weights"].values())


def test_build_disclaimer_mentions_method():
    d = po.build_disclaimer("max_sharpe")
    assert "max_sharpe" in d
    assert "不代表未来收益" in d


# ============================================================
# 2. available_optimizers / is_available
# ============================================================


def test_available_optimizers_returns_list():
    opts = po.available_optimizers()
    assert isinstance(opts, list)
    # 可用性与优化器列表一致 (本机装 skfolio/riskfolio/pypfopt 任一 → True; CI 精简依赖 → 空+False)
    assert bool(po.is_available()) is (len(opts) > 0)


def test_describe_reports_state():
    info = po.describe()
    assert "available" in info
    assert "optimizers" in info
    assert "supported_methods" in info
    assert "max_sharpe" in info["supported_methods"]


# ============================================================
# 3. optimize_portfolio 端到端
# ============================================================


def test_optimize_max_sharpe_returns_weights():
    r = po.optimize_portfolio(_good_returns(4, 252), method="max_sharpe", rf=0.02)
    assert r["research_only"] is True
    assert r["forbidden_live_order"] is True
    assert len(r["weights"]) == 4
    # 权重和应接近 1 (允许数值误差)
    total = sum(r["weights"].values())
    assert 0.95 <= total <= 1.05
    # 至少有一个优化器被使用
    assert r["optimizer"] != "none"


def test_optimize_min_variance_returns_weights():
    r = po.optimize_portfolio(_good_returns(4, 252), method="min_variance")
    assert len(r["weights"]) == 4
    assert r["optimizer"] != "none"


def test_optimize_equal_weight_method_no_optimizer_needed():
    """method=equal_weight 不需要优化库, 直接等权。"""
    r = po.optimize_portfolio(_good_returns(3, 252), method="equal_weight")
    assert r["optimizer"] == "equal_weight"
    assert all(abs(v - 1 / 3) < 1e-6 for v in r["weights"].values())


def test_optimize_includes_disclaimer():
    r = po.optimize_portfolio(_good_returns(3, 252), method="max_sharpe")
    assert "disclaimer" in r
    assert "不代表未来收益" in r["disclaimer"]


# ============================================================
# 4. 边界 / 失败安全
# ============================================================


def test_optimize_insufficient_data_returns_degraded():
    """数据不足 → degraded + error。"""
    r = po.optimize_portfolio(
        pd.DataFrame({"A": [0.01] * 10, "B": [0.02] * 10}),  # 只有 10 行
        method="max_sharpe",
    )
    assert r["degraded"] is True
    assert "error" in r


def test_optimize_single_asset_fails_safe():
    r = po.optimize_portfolio(pd.DataFrame({"A": np.random.normal(0, 0.02, 252)}), method="max_sharpe")
    assert r["degraded"] is True


def test_optimize_none_input_fails_safe():
    r = po.optimize_portfolio(None, method="max_sharpe")
    assert r["degraded"] is True
    assert "error" in r


def test_optimize_unknown_method_uses_default():
    """未知 method 不抛, 走默认优化路径 (MeanRisk() 默认)。"""
    r = po.optimize_portfolio(_good_returns(3, 252), method="totally_unknown")
    # 应该跑出权重 (走默认优化或等权兜底)
    assert isinstance(r["weights"], dict)


# ============================================================
# 5. 降级路径 (强制全部不可用)
# ============================================================


@pytest.fixture
def all_degraded(monkeypatch):
    """强制全部优化器不可用, 模拟未装任何库。"""
    monkeypatch.setattr(po, "_SKFOLIO", False)
    monkeypatch.setattr(po, "_RISKFOLIO", False)
    monkeypatch.setattr(po, "_PYPFOPT", False)


def test_degraded_max_sharpe_falls_back_to_equal_weight(all_degraded):
    """无优化库时 max_sharpe 退化等权 + degraded=True。"""
    r = po.optimize_portfolio(_good_returns(4, 252), method="max_sharpe")
    assert r["optimizer"] == "equal_weight(fallback)"
    assert r["degraded"] is True
    assert all(abs(v - 0.25) < 1e-6 for v in r["weights"].values())


def test_degraded_available_optimizers_empty(all_degraded):
    assert po.available_optimizers() == []
    assert po.is_available() is False


def test_degraded_describe_reports_unavailable(all_degraded):
    info = po.describe()
    assert info["available"] is False
    assert "未装" in info["note"]
