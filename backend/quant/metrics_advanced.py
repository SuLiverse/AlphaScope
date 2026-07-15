"""高级稳健指标 — Probabilistic Sharpe / Deflated Sharpe (López de Prado 口径)。

纯函数、无外部依赖。用于参数扫描 / 遗传寻优后的「多重检验」诚实披露:
样本内最优夏普在尝试次数变多时会被选择偏差抬高, DSR 用于下调。

参考文献思路:
- PSR: Bailey & López de Prado, "The Sharpe Ratio Efficient Frontier"
- DSR: Bailey & López de Prado, "The Deflated Sharpe Ratio"

合规: 指标描述历史回测统计性质, 不预测未来、不构成投资建议。
"""

from __future__ import annotations

import math
from statistics import NormalDist
from typing import Any, Optional, Sequence


_STANDARD_NORMAL = NormalDist()
_EULER_MASCHERONI = 0.5772156649015329


def _phi(x: float) -> float:
    """Standard normal CDF."""
    return _STANDARD_NORMAL.cdf(x)


def _ppf(p: float) -> float:
    """Inverse standard-normal CDF with finite guards at the open interval ends."""
    if p <= 0:
        return -8.0
    if p >= 1:
        return 8.0
    return _STANDARD_NORMAL.inv_cdf(p)


def _period_sharpe(sharpe: float, periods_per_year: int) -> float:
    """Convert an annualized Sharpe to the observation-frequency Sharpe."""
    periods = int(periods_per_year)
    if periods <= 0:
        raise ValueError("periods_per_year must be positive")
    return float(sharpe) / math.sqrt(periods)


def estimate_sharpe_variance(candidate_sharpes: Sequence[float] | None) -> float | None:
    """Estimate cross-sectional Sharpe variance from the tested candidates.

    Candidate Sharpes must use the same annualization convention as the
    selected Sharpe.  The sample variance (``ddof=1``) is used because the
    supplied candidates are observations from the strategy-search process,
    not the complete population of possible strategies.
    """
    values: list[float] = []
    for value in candidate_sharpes or []:
        try:
            candidate = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(candidate):
            values.append(candidate)
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return sum((value - mean) ** 2 for value in values) / (len(values) - 1)


def calc_expected_max_sharpe(sharpe_variance: float, effective_trials: float) -> float:
    """Return the López de Prado expected maximum Sharpe benchmark.

    ``sharpe_variance`` is the cross-sectional variance of candidate Sharpes;
    ``effective_trials`` is the number of independent trials, which may be
    fractional after correcting a correlated search.  The result has the same
    annualization convention as the candidate Sharpes.
    """
    variance = float(sharpe_variance)
    trials = float(effective_trials)
    if not math.isfinite(variance) or variance < 0:
        raise ValueError("sharpe_variance must be finite and non-negative")
    if not math.isfinite(trials) or trials < 1:
        raise ValueError("effective_trials must be finite and at least one")
    if trials <= 1.0 or variance == 0.0:
        return 0.0

    q_left = _ppf(1.0 - 1.0 / trials)
    q_right = _ppf(1.0 - 1.0 / (trials * math.e))
    expected_max_z = (1.0 - _EULER_MASCHERONI) * q_left + _EULER_MASCHERONI * q_right
    return math.sqrt(variance) * max(0.0, expected_max_z)


def _resolve_dsr_benchmark(
    *,
    n_obs: int,
    n_trials: int,
    periods_per_year: int,
    sr_benchmark: Optional[float],
    candidate_sharpes: Sequence[float] | None,
    sharpe_variance: Optional[float],
    effective_trials: Optional[float],
) -> tuple[float, float, float | None, str, int]:
    """Resolve the DSR benchmark and expose its audit metadata."""
    candidates = []
    for value in candidate_sharpes or []:
        try:
            candidate = float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(candidate):
            candidates.append(candidate)

    trials = float(effective_trials if effective_trials is not None else max(1, int(n_trials or 1)))
    if not math.isfinite(trials) or trials < 1:
        raise ValueError("effective_trials must be finite and at least one")

    if sr_benchmark is not None:
        benchmark = float(sr_benchmark)
        if not math.isfinite(benchmark):
            raise ValueError("sr_benchmark must be finite")
        return benchmark, trials, None, "explicit_benchmark", len(candidates)

    if sharpe_variance is not None:
        variance = float(sharpe_variance)
        source = "explicit_variance"
    else:
        estimated = estimate_sharpe_variance(candidates)
        if estimated is not None:
            variance = estimated
            source = "candidate_sharpes"
        else:
            # Compatibility fallback for legacy callers that only supplied
            # n_obs/n_trials.  In annualized units this is the null sampling
            # variance periods_per_year / (n_obs - 1).  Search integrations
            # should pass their actual candidate Sharpe distribution instead.
            variance = float(periods_per_year) / (n_obs - 1)
            source = "sampling_variance_fallback"

    benchmark = calc_expected_max_sharpe(variance, trials)
    return benchmark, trials, variance, source, len(candidates)


def calc_skew_kurt(returns: list[float]) -> tuple[float, float]:
    """样本偏度与超额峰度; 不足返回 (0, 0)。"""
    n = len(returns)
    if n < 4:
        return 0.0, 0.0
    mean = sum(returns) / n
    m2 = sum((r - mean) ** 2 for r in returns) / n
    if m2 <= 1e-18:
        return 0.0, 0.0
    m3 = sum((r - mean) ** 3 for r in returns) / n
    m4 = sum((r - mean) ** 4 for r in returns) / n
    skew = m3 / (m2**1.5)
    kurt = m4 / (m2**2) - 3.0  # excess kurtosis
    return float(skew), float(kurt)


def calc_probabilistic_sharpe(
    sharpe: float,
    n_obs: int,
    skew: float = 0.0,
    kurt_excess: float = 0.0,
    sr_benchmark: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Return ``P(true SR > sr_benchmark)`` for an annualized Sharpe.

    ``sharpe`` and ``sr_benchmark`` use the annualized convention returned by
    :func:`backend.quant.metrics.calc_sharpe`.  The sampling distribution is a
    single-observation-frequency formula, so both values are converted back to
    period Sharpe before applying the Bailey/López de Prado PSR statistic.
    Set ``periods_per_year=1`` only when passing an already unannualized Sharpe.
    """
    if n_obs < 2 or not math.isfinite(sharpe):
        return 0.0
    try:
        sr = _period_sharpe(sharpe, periods_per_year)
        benchmark = _period_sharpe(sr_benchmark, periods_per_year)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not all(math.isfinite(v) for v in (sr, benchmark, skew, kurt_excess)):
        return 0.0

    # gamma_4 is ordinary kurtosis.  With an excess-kurtosis input,
    # (gamma_4 - 1) / 4 becomes (kurt_excess + 2) / 4.
    num = 1.0 - skew * sr + ((kurt_excess + 2.0) / 4.0) * sr * sr
    if num <= 0:
        num = 1e-9
    se = math.sqrt(num / (n_obs - 1))
    if se <= 0:
        return 1.0 if sr > benchmark else 0.0
    z = (sr - benchmark) / se
    return max(0.0, min(1.0, _phi(z)))


def calc_deflated_sharpe(
    sharpe: float,
    n_obs: int,
    n_trials: int = 1,
    skew: float = 0.0,
    kurt_excess: float = 0.0,
    sr_benchmark: Optional[float] = None,
    periods_per_year: int = 252,
    *,
    candidate_sharpes: Sequence[float] | None = None,
    sharpe_variance: Optional[float] = None,
    effective_trials: Optional[float] = None,
) -> float:
    """Deflated Sharpe Ratio using the López de Prado benchmark.

    For a defensible search correction, pass ``candidate_sharpes`` (all
    candidates, before top-N selection) or an explicit ``sharpe_variance``.
    ``effective_trials`` can correct the raw trial count for correlated
    strategies.  The three new inputs are keyword-only, so existing callers
    using the historical positional API remain compatible.

    If no candidate distribution or variance is available, legacy callers
    retain the former null-sampling-variance approximation.  Integrations that
    perform a real search should not rely on that fallback.
    """
    if n_obs < 2 or not math.isfinite(sharpe):
        return 0.0

    try:
        periods = int(periods_per_year)
        if periods <= 0:
            return 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0

    try:
        benchmark, _, _, _, _ = _resolve_dsr_benchmark(
            n_obs=n_obs,
            n_trials=n_trials,
            periods_per_year=periods,
            sr_benchmark=sr_benchmark,
            candidate_sharpes=candidate_sharpes,
            sharpe_variance=sharpe_variance,
            effective_trials=effective_trials,
        )
    except (TypeError, ValueError, OverflowError):
        return 0.0

    return calc_probabilistic_sharpe(
        sharpe,
        n_obs,
        skew=skew,
        kurt_excess=kurt_excess,
        sr_benchmark=benchmark,
        periods_per_year=periods,
    )


def attach_selection_bias_metrics(
    summary: dict[str, Any],
    returns: list[float],
    *,
    n_trials: int = 1,
    sharpe_key: str = "sharpe",
    periods_per_year: int = 252,
    candidate_sharpes: Sequence[float] | None = None,
    sharpe_variance: Optional[float] = None,
    effective_trials: Optional[float] = None,
) -> dict[str, Any]:
    """在绩效摘要上附加 PSR/DSR 字段(失败安全, 原地扩展拷贝)。"""
    out = dict(summary or {})
    try:
        sr = float(out.get(sharpe_key) or out.get("sharpe_ratio") or 0.0)
        skew, kurt = calc_skew_kurt(list(returns or []))
        n = len(returns or [])
        out["n_trials_for_dsr"] = max(1, int(n_trials or 1))
        out["return_skew"] = round(skew, 4)
        out["return_excess_kurtosis"] = round(kurt, 4)
        out["sharpe_periods_per_year"] = max(1, int(periods_per_year))
        if n < 2:
            out["probabilistic_sharpe"] = None
            out["deflated_sharpe"] = None
            out["selection_bias_status"] = "insufficient"
            out["selection_bias_note"] = "观测数不足 2，无法计算 PSR/DSR。"
            return out
        benchmark, resolved_trials, resolved_variance, benchmark_source, candidate_count = _resolve_dsr_benchmark(
            n_obs=n,
            n_trials=n_trials,
            periods_per_year=periods_per_year,
            sr_benchmark=None,
            candidate_sharpes=candidate_sharpes,
            sharpe_variance=sharpe_variance,
            effective_trials=effective_trials,
        )
        psr = calc_probabilistic_sharpe(
            sr,
            n,
            skew=skew,
            kurt_excess=kurt,
            periods_per_year=periods_per_year,
        )
        dsr = calc_deflated_sharpe(
            sr,
            n,
            n_trials=n_trials,
            skew=skew,
            kurt_excess=kurt,
            periods_per_year=periods_per_year,
            candidate_sharpes=candidate_sharpes,
            sharpe_variance=sharpe_variance,
            effective_trials=effective_trials,
        )
        out["probabilistic_sharpe"] = round(psr, 4)
        out["deflated_sharpe"] = round(dsr, 4)
        out["effective_trials_for_dsr"] = round(resolved_trials, 4)
        out["candidate_sharpe_count"] = candidate_count
        out["candidate_sharpe_variance"] = round(resolved_variance, 8) if resolved_variance is not None else None
        out["dsr_benchmark"] = round(benchmark, 8)
        out["dsr_benchmark_source"] = benchmark_source
        out["selection_bias_status"] = "ok"
        if benchmark_source == "candidate_sharpes":
            basis = "DSR 使用本次搜索全部候选 Sharpe 的横截面方差"
        elif benchmark_source == "explicit_variance":
            basis = "DSR 使用调用方提供的候选 Sharpe 方差"
        else:
            basis = "DSR 未获得候选分布，使用兼容性抽样方差近似"
        out["selection_bias_note"] = f"{basis}与有效独立试验数校正选择偏差; PSR/DSR 不代表未来可获得该夏普。"
    except Exception:
        out.setdefault("deflated_sharpe", None)
        out.setdefault("probabilistic_sharpe", None)
        out.setdefault("selection_bias_status", "error")
    return out
