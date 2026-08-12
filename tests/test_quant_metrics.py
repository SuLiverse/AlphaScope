"""Unit tests for quant performance metrics JSON-safety guards."""

from __future__ import annotations

import json

from backend.quant.metrics import build_performance_summary


def test_build_performance_summary_all_win_no_inf():
    """全胜回测时 profit_factor 必须为 None(而非 inf), 且可被 json.dumps(allow_nan=False) 序列化。"""
    trades = [{"pnl": 100}, {"pnl": 200}, {"pnl": 300}]
    summary = build_performance_summary(
        equity_curve=[100000, 100300],
        trades=trades,
        initial_capital=100000,
        days=10,
    )

    assert summary["profit_factor"] is None
    json.dumps(summary, allow_nan=False)


def test_build_performance_summary_no_loss_all_zero():
    """无亏损且无盈利时 profit_factor 为有限值 0.0, 序列化不抛异常。"""
    summary = build_performance_summary(
        equity_curve=[100000, 100000],
        trades=[],
        initial_capital=100000,
        days=10,
    )

    assert summary["profit_factor"] == 0.0
    json.dumps(summary, allow_nan=False)
