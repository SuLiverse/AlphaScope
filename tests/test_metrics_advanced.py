"""PSR / DSR unit tests."""

from __future__ import annotations

import math

import pytest

from backend.quant.metrics import calc_returns, calc_sharpe
from backend.quant.metrics_advanced import (
    _ppf,
    attach_selection_bias_metrics,
    calc_deflated_sharpe,
    calc_expected_max_sharpe,
    calc_probabilistic_sharpe,
    estimate_sharpe_variance,
)


def test_ppf_reference_upper_tail_and_strict_monotonicity():
    probabilities = [0.98, 0.99, 0.999]
    quantiles = [_ppf(p) for p in probabilities]

    assert quantiles == pytest.approx(
        [2.0537489106, 2.3263478740, 3.0902323062],
        abs=1e-10,
    )
    assert quantiles[0] < quantiles[1] < quantiles[2]
    assert _ppf(0.01) == pytest.approx(-_ppf(0.99), abs=1e-12)


def test_psr_uses_observation_frequency_not_annualized_sr_directly():
    # For normal returns, annualized SR=1 and 252 observations gives z≈0.997
    # after converting SR back to daily units, hence PSR≈0.840624.
    psr = calc_probabilistic_sharpe(1.0, 252)

    assert psr == pytest.approx(0.84062388, abs=1e-8)
    assert psr == pytest.approx(
        calc_probabilistic_sharpe(1.0 / math.sqrt(252), 252, periods_per_year=1),
        abs=1e-12,
    )


def test_psr_high_for_stable_positive():
    # 非零波动 + 正均值, 年化夏普应显著 > 0
    rets = [0.002 if i % 2 == 0 else 0.0005 for i in range(252)]
    sr = calc_sharpe(rets)
    assert sr > 0.5
    psr = calc_probabilistic_sharpe(sr, len(rets))
    assert psr >= 0.5


def test_dsr_decreases_with_more_trials():
    trials = [1, 2, 5, 10, 50, 100, 1000]
    values = [calc_deflated_sharpe(1.0, 252, n_trials=n) for n in trials]

    assert all(right < left for left, right in zip(values, values[1:]))
    assert values[5] == pytest.approx(0.06287594, abs=1e-8)


def test_dsr_matches_independent_candidate_distribution_reference():
    # Hand-calculated sample variance and López de Prado expected-maximum
    # benchmark for this complete five-candidate search distribution.
    candidates = [-0.2, 0.1, 0.4, 0.8, 1.0]
    variance = estimate_sharpe_variance(candidates)

    assert variance == pytest.approx(0.242, abs=1e-12)
    assert calc_expected_max_sharpe(variance, 5) == pytest.approx(0.5866786762820548, abs=1e-12)
    assert calc_deflated_sharpe(
        1.2,
        252,
        n_trials=5,
        candidate_sharpes=candidates,
        effective_trials=5,
    ) == pytest.approx(0.729476550140594, abs=1e-12)


def test_dsr_candidate_variance_and_effective_trials_are_explicit_and_monotonic():
    candidates = [-0.2, 0.1, 0.4, 0.8, 1.0]
    variance = estimate_sharpe_variance(candidates)
    effective_counts = [1.0, 2.0, 3.5, 5.0, 10.0, 25.0]
    values = [
        calc_deflated_sharpe(
            1.2,
            252,
            n_trials=25,
            candidate_sharpes=candidates,
            effective_trials=count,
        )
        for count in effective_counts
    ]

    assert all(right < left for left, right in zip(values, values[1:]))
    assert calc_deflated_sharpe(
        1.2,
        252,
        n_trials=5,
        sharpe_variance=variance,
        effective_trials=5,
    ) == pytest.approx(values[3], abs=1e-12)

    narrow = calc_deflated_sharpe(
        1.2,
        252,
        n_trials=5,
        candidate_sharpes=[0.0, 0.1, 0.2, 0.3, 0.4],
    )
    wide = calc_deflated_sharpe(
        1.2,
        252,
        n_trials=5,
        candidate_sharpes=[-1.0, -0.2, 0.4, 1.1, 1.8],
    )
    assert wide < narrow


def test_attach_summary():
    equity = [100.0]
    for _ in range(50):
        equity.append(equity[-1] * 1.001)
    rets = calc_returns(equity)
    summary = attach_selection_bias_metrics({"sharpe_ratio": calc_sharpe(rets)}, rets, n_trials=10)
    assert "deflated_sharpe" in summary
    assert summary["n_trials_for_dsr"] == 10
    assert summary["sharpe_periods_per_year"] == 252


def test_attach_summary_audits_candidate_distribution_basis():
    returns = [0.01, -0.005, 0.007, -0.002] * 20
    candidates = [-0.2, 0.1, 0.4, 0.8, 1.0]
    summary = attach_selection_bias_metrics(
        {"sharpe": calc_sharpe(returns)},
        returns,
        n_trials=5,
        candidate_sharpes=candidates,
        effective_trials=3.5,
    )

    assert summary["dsr_benchmark_source"] == "candidate_sharpes"
    assert summary["candidate_sharpe_count"] == 5
    assert summary["candidate_sharpe_variance"] == pytest.approx(0.242)
    assert summary["effective_trials_for_dsr"] == 3.5


def test_attach_summary_marks_insufficient_observations_without_fake_zero_probability():
    summary = attach_selection_bias_metrics({"sharpe": 0.0}, [0.01], n_trials=10)

    assert summary["selection_bias_status"] == "insufficient"
    assert summary["probabilistic_sharpe"] is None
    assert summary["deflated_sharpe"] is None
