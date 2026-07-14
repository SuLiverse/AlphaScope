"""PSR / DSR unit tests."""

from __future__ import annotations

from backend.quant.metrics import calc_returns, calc_sharpe
from backend.quant.metrics_advanced import (
    attach_selection_bias_metrics,
    calc_deflated_sharpe,
    calc_probabilistic_sharpe,
)


def test_psr_high_for_stable_positive():
    # 非零波动 + 正均值, 年化夏普应显著 > 0
    rets = [0.002 if i % 2 == 0 else 0.0005 for i in range(252)]
    sr = calc_sharpe(rets)
    assert sr > 0.5
    psr = calc_probabilistic_sharpe(sr, len(rets))
    assert psr >= 0.5


def test_dsr_decreases_with_more_trials():
    rets = [0.002 if i % 2 == 0 else 0.0005 for i in range(200)]
    sr = calc_sharpe(rets)
    d1 = calc_deflated_sharpe(sr, len(rets), n_trials=1)
    d50 = calc_deflated_sharpe(sr, len(rets), n_trials=50)
    assert d50 <= d1 + 1e-9


def test_attach_summary():
    equity = [100.0]
    for _ in range(50):
        equity.append(equity[-1] * 1.001)
    rets = calc_returns(equity)
    summary = attach_selection_bias_metrics({"sharpe_ratio": calc_sharpe(rets)}, rets, n_trials=10)
    assert "deflated_sharpe" in summary
    assert summary["n_trials_for_dsr"] == 10
