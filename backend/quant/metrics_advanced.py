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
from typing import Any, Optional


def _phi(x: float) -> float:
    """Standard normal CDF (Abramowitz-Stegun 近似)。"""
    if x < -8:
        return 0.0
    if x > 8:
        return 1.0
    # Hart approximation
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    d = 0.3989422804014327  # 1/sqrt(2pi)
    p = d * math.exp(-x * x / 2.0) * (
        t
        * (
            0.319381530
            + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429)))
        )
    )
    return 1.0 - p if x > 0 else p


def _ppf(p: float) -> float:
    """Approximate inverse normal CDF for p in (0,1)."""
    if p <= 0:
        return -8.0
    if p >= 1:
        return 8.0
    # Beasley-Springer-Moro rough
    a = [2.50662823884, -18.61500062529, 41.39119773534, -25.44106049637]
    b = [-8.47351093090, 23.08336743743, -21.06224101826, 3.13082909833]
    c = [
        0.3374754822726147,
        0.9761690190917186,
        0.1607979323686187,
        0.0276438810333863,
        0.0038405729373609,
        0.0003951896511919,
        0.0000321767881768,
        0.0000002888167364,
        0.0000003960315187,
    ]
    y = p - 0.5
    if abs(y) < 0.42:
        r = y * y
        num = y * (((a[3] * r + a[2]) * r + a[1]) * r + a[0])
        den = ((((b[3] * r + b[2]) * r + b[1]) * r + b[0]) * r + 1.0)
        return num / den
    r = p if y > 0 else 1.0 - p
    s = math.log(-math.log(r))
    t = c[0] + s * (
        c[1]
        + s
        * (
            c[2]
            + s * (c[3] + s * (c[4] + s * (c[5] + s * (c[6] + s * (c[7] + s * c[8])))))
        )
    )
    return t if y > 0 else -t


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
) -> float:
    """Probabilistic Sharpe Ratio ∈ [0, 1]: P(true SR > sr_benchmark)。"""
    if n_obs < 2 or not math.isfinite(sharpe):
        return 0.0
    # se(SR) ≈ sqrt((1 - skew*SR + (kurt+3)/4 * SR^2) / (n-1))
    sr = float(sharpe)
    num = 1.0 - skew * sr + ((kurt_excess + 3.0) / 4.0) * sr * sr
    if num <= 0:
        num = 1e-9
    se = math.sqrt(num / (n_obs - 1))
    if se <= 0:
        return 1.0 if sr > sr_benchmark else 0.0
    z = (sr - sr_benchmark) / se
    return max(0.0, min(1.0, _phi(z)))


def calc_deflated_sharpe(
    sharpe: float,
    n_obs: int,
    n_trials: int = 1,
    skew: float = 0.0,
    kurt_excess: float = 0.0,
    sr_benchmark: Optional[float] = None,
) -> float:
    """Deflated Sharpe Ratio: 相对「多次尝试下的期望最大零夏普」的 PSR。

    n_trials: 参数网格 / 进化代数中的独立尝试次数(至少 1)。
    返回值在 [0,1], 越高表示在选择偏差校正后仍显著。
    尝试次数增加时, 基准门槛抬高, DSR 单调不增(选择偏差更严)。
    """
    trials = max(1, int(n_trials or 1))
    if n_obs < 2 or not math.isfinite(sharpe):
        return 0.0

    # 零假设下单次观测 SR 的尺度 ~ 1/sqrt(n); 多次尝试期望最大 |z|
    sigma0 = 1.0 / math.sqrt(max(n_obs - 1, 1))
    if trials <= 1:
        e_max_sr0 = 0.0
    else:
        # Φ^{-1}(1 - 1/N) * sigma — 正门槛, 尝试越多门槛越高
        u = 1.0 - 1.0 / trials
        u = min(max(u, 1e-6), 1.0 - 1e-6)
        e_max_sr0 = max(0.0, _ppf(u)) * sigma0

    if sr_benchmark is not None:
        bench = float(sr_benchmark)
    else:
        bench = e_max_sr0

    return calc_probabilistic_sharpe(
        sharpe, n_obs, skew=skew, kurt_excess=kurt_excess, sr_benchmark=bench
    )


def attach_selection_bias_metrics(
    summary: dict[str, Any],
    returns: list[float],
    *,
    n_trials: int = 1,
    sharpe_key: str = "sharpe",
) -> dict[str, Any]:
    """在绩效摘要上附加 PSR/DSR 字段(失败安全, 原地扩展拷贝)。"""
    out = dict(summary or {})
    try:
        sr = float(out.get(sharpe_key) or out.get("sharpe_ratio") or 0.0)
        skew, kurt = calc_skew_kurt(list(returns or []))
        n = len(returns or [])
        psr = calc_probabilistic_sharpe(sr, n, skew=skew, kurt_excess=kurt)
        dsr = calc_deflated_sharpe(sr, n, n_trials=n_trials, skew=skew, kurt_excess=kurt)
        out["probabilistic_sharpe"] = round(psr, 4)
        out["deflated_sharpe"] = round(dsr, 4)
        out["n_trials_for_dsr"] = max(1, int(n_trials or 1))
        out["return_skew"] = round(skew, 4)
        out["return_excess_kurtosis"] = round(kurt, 4)
        out["selection_bias_note"] = (
            "PSR/DSR 用于校正多重尝试下的选择偏差; 不代表未来可获得该夏普。"
        )
    except Exception:
        out.setdefault("deflated_sharpe", 0.0)
        out.setdefault("probabilistic_sharpe", 0.0)
    return out
