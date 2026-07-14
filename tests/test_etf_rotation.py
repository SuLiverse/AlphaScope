"""Tests for the clean-room ETF momentum + RSRS portfolio research baseline."""

from __future__ import annotations

import math
from datetime import datetime, timedelta


def _bars(n: int, *, base: float, drift: float, skip: set[int] | None = None):
    start = datetime(2020, 1, 1)
    rows = []
    for index in range(n):
        if index in (skip or set()):
            continue
        close = max(1.0, base + drift * index + 3.0 * math.sin(index / 4.0))
        open_price = max(0.5, close * (0.997 + 0.002 * math.sin(index / 3.0)))
        # Vary the high/low relationship so historical RSRS betas have variance.
        high = max(open_price, close) * (1.01 + 0.002 * math.sin(index / 5.0))
        low = min(open_price, close) * (0.99 - 0.001 * math.cos(index / 7.0))
        rows.append(
            {
                "date": (start + timedelta(days=index)).strftime("%Y-%m-%d"),
                "open": round(open_price, 4),
                "high": round(high, 4),
                "low": round(max(0.1, low), 4),
                "close": round(close, 4),
                "volume": 100000 + index * 100,
            }
        )
    return rows


def _params(**overrides):
    params = {
        "momentum_window": 10,
        "ma_window": 10,
        "rsrs_window": 5,
        "rsrs_history": 20,
        "rsrs_entry": -10.0,
        "rsrs_exit": -20.0,
        "rebalance_interval": 5,
        "top_k": 1,
        "commission_rate": 0.0002,
        "commission_min": 0.0,
        "slippage_rate": 0.0001,
        "lot_size": 100,
        "require_positive_momentum": False,
        "require_above_ma": False,
    }
    params.update(overrides)
    return params


def _universe(n: int = 160):
    return {
        "510300": _bars(n, base=100.0, drift=0.18),
        "518880": _bars(n, base=80.0, drift=0.08),
        "513100": _bars(n, base=60.0, drift=-0.02),
    }


def test_alignment_uses_only_common_dates_without_forward_fill():
    from backend.quant.etf_rotation import align_portfolio_bars

    dates, aligned = align_portfolio_bars(
        {
            "A": _bars(20, base=100.0, drift=0.1),
            "B": _bars(20, base=80.0, drift=0.1, skip={3, 7}),
        }
    )

    assert len(dates) == 18
    assert all(len(rows) == 18 for rows in aligned.values())
    assert dates == sorted(dates)


def test_backtest_uses_next_open_lots_and_declares_assumptions():
    from backend.quant.etf_rotation import run_etf_rotation_backtest

    result = run_etf_rotation_backtest(_universe(), initial_capital=100000.0, params=_params())

    assert result["status"] == "ok"
    assert result["decisions"]
    assert result["assumptions"]["signal_timing"].endswith("open[t+1].")
    assert result["assumptions"]["price_limit_filter"] is False
    assert all(trade["signal_date"] < trade["date"] for trade in result["trades"])
    assert all(trade["shares"] % 100 == 0 for trade in result["trades"])
    assert result["performance"]["total_orders"] == len(result["trades"])


def test_future_data_cannot_change_prior_decisions():
    from backend.quant.etf_rotation import run_etf_rotation_backtest

    baseline_data = _universe(130)
    params = _params()
    baseline = run_etf_rotation_backtest(baseline_data, params=params)
    changed = {symbol: [dict(bar) for bar in bars] for symbol, bars in baseline_data.items()}
    cutoff = 80
    for bars in changed.values():
        for bar in bars[cutoff:]:
            bar["open"] *= 3
            bar["high"] *= 3
            bar["low"] *= 3
            bar["close"] *= 3
    mutated = run_etf_rotation_backtest(changed, params=params)
    cutoff_date = baseline_data["510300"][cutoff - 1]["date"]
    before = [decision for decision in baseline["decisions"] if decision["signal_date"] <= cutoff_date]
    after = [decision for decision in mutated["decisions"] if decision["signal_date"] <= cutoff_date]
    assert before == after


def test_higher_costs_do_not_improve_same_rotation_result():
    from backend.quant.etf_rotation import run_etf_rotation_backtest

    low_cost = run_etf_rotation_backtest(_universe(), initial_capital=100000.0, params=_params())
    high_cost = run_etf_rotation_backtest(
        _universe(),
        initial_capital=100000.0,
        params=_params(commission_rate=0.01, slippage_rate=0.01),
    )

    assert high_cost["performance"]["final_equity"] <= low_cost["performance"]["final_equity"] + 1e-6


def test_zero_momentum_ranks_above_negative_momentum_when_filter_is_disabled():
    from backend.quant.etf_rotation import _target_symbols, make_config

    targets, _reason = _target_symbols(
        [
            {"symbol": "zero", "momentum": 0.0, "rsrs": 1.0, "eligible": True},
            {"symbol": "negative", "momentum": -0.01, "rsrs": 1.0, "eligible": True},
        ],
        {},
        make_config({"top_k": 1}),
        rebalance=True,
    )

    assert targets == ["zero"]


def test_fee_aware_equal_weight_targets_are_not_symbol_order_dependent():
    from backend.quant.etf_rotation import _execute_targets, make_config

    config = make_config({"commission_rate": 0.01, "commission_min": 0.0, "slippage_rate": 0.0})

    def execute(prices):
        holdings = {}
        trades = []
        cash = _execute_targets(
            holdings=holdings,
            cash=100_000.0,
            bars_at_open={symbol: {"open": price} for symbol, price in prices.items()},
            target_symbols=list(prices),
            config=config,
            execution_date="2020-01-02",
            signal_date="2020-01-01",
            reason="scheduled_rebalance",
            trades=trades,
        )
        return {prices[symbol]: position["shares"] for symbol, position in holdings.items()}, cash, trades

    first_weights, first_cash, first_trades = execute({"AAA": 100.0, "ZZZ": 125.0})
    second_weights, second_cash, second_trades = execute({"AAA": 125.0, "ZZZ": 100.0})

    assert first_weights == second_weights == {100.0: 400, 125.0: 300}
    assert first_cash == second_cash == 21_725.0
    assert [trade["shares"] for trade in first_trades] == [400, 300]
    assert [trade["shares"] for trade in second_trades] == [300, 400]


def test_fee_aware_equal_weight_targets_include_minimum_commissions():
    from backend.quant.etf_rotation import _execute_targets, make_config

    holdings = {}
    trades = []
    cash = _execute_targets(
        holdings=holdings,
        cash=10_000.0,
        bars_at_open={"AAA": {"open": 10.0}, "ZZZ": {"open": 25.0}},
        target_symbols=["AAA", "ZZZ"],
        config=make_config({"commission_rate": 0.0, "commission_min": 50.0, "slippage_rate": 0.0}),
        execution_date="2020-01-02",
        signal_date="2020-01-01",
        reason="scheduled_rebalance",
        trades=trades,
    )

    assert {symbol: position["shares"] for symbol, position in holdings.items()} == {"AAA": 400, "ZZZ": 100}
    assert cash == 3_400.0
    assert len(trades) == 2


def test_walk_forward_uses_dates_and_produces_chronological_oos_windows():
    from backend.quant.etf_rotation import run_etf_rotation_walk_forward

    report = run_etf_rotation_walk_forward(_universe(160), params=_params(), n_splits=3, scheme="anchored")

    assert report["status"] == "ok"
    assert report["n_windows"] >= 2
    assert report["aggregate"]["windows_evaluated"] == report["n_windows"]
    previous_end = ""
    for window in report["windows"]:
        assert window["is_end_date"] < window["oos_start_date"]
        assert window["oos_start_date"] >= previous_end
        previous_end = window["oos_end_date"]


def test_insufficient_history_is_explicit_not_a_preview_result():
    from backend.quant.etf_rotation import run_etf_rotation_backtest

    result = run_etf_rotation_backtest(_universe(20), params=_params())

    assert result["status"] == "insufficient_data"
    assert result["trades"] == []
