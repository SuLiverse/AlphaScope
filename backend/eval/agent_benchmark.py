"""Agent 级确定性评测套件 — 幻觉数字 / 引用一致性 / 信号边界。

不调用 LLM: 用固定 fixture 文本 + stock_data 跑 citation_validator /
quant_referee / research_trust 等纯函数, 作为回归基准。

用法::
    from backend.eval.agent_benchmark import run_benchmark_suite
    report = run_benchmark_suite()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "checks": self.checks,
            "error": self.error,
        }


def _case_fabricated_price() -> CaseResult:
    from backend.quality.citation_validator import validate_citations

    facts = {"symbol": "600519", "close": 1680.5, "day_change": 1.2, "rsi": 55.0}
    text = "当前股价 99999 元, 必涨到 120000。"
    r = validate_citations(text, stock_data=facts)
    checks = [
        {
            "name": "flags_unverified",
            "ok": r.n_unverified >= 1,
            "detail": f"n_unverified={r.n_unverified}",
        },
        {
            "name": "grounding_below_one",
            "ok": r.grounding_score < 1.0,
            "detail": f"score={r.grounding_score}",
        },
        {
            "name": "suggests_cap",
            "ok": r.suggest_confidence_cap is not None and r.suggest_confidence_cap < 100,
            "detail": f"cap={r.suggest_confidence_cap}",
        },
    ]
    return CaseResult("fabricated_price", all(c["ok"] for c in checks), checks)


def _case_grounded_price() -> CaseResult:
    from backend.quality.citation_validator import validate_citations

    facts = {"symbol": "600519", "close": 1680.5, "rsi": 58.3}
    text = "最新价 1680.50, RSI 58.3 中性。"
    r = validate_citations(text, stock_data=facts)
    checks = [
        {"name": "verified_positive", "ok": r.n_verified >= 1, "detail": f"v={r.n_verified}"},
        {"name": "no_unverified", "ok": r.n_unverified == 0, "detail": f"u={r.n_unverified}"},
    ]
    return CaseResult("grounded_price", all(c["ok"] for c in checks), checks)


def _case_hallucinated_citation() -> CaseResult:
    from backend.quality.citation_validator import validate_citations

    pool = [{"id": "a"}, {"id": "b"}]
    text = "参见证据 [1] 与 [9]。"
    r = validate_citations(text, stock_data={"close": 10}, evidence_pool=pool)
    checks = [
        {"name": "bad_citation", "ok": r.n_citation_bad >= 1, "detail": f"bad={r.n_citation_bad}"},
        {"name": "ok_citation", "ok": r.n_citation_ok >= 1, "detail": f"ok={r.n_citation_ok}"},
    ]
    return CaseResult("hallucinated_citation", all(c["ok"] for c in checks), checks)


def _case_quant_referee_bull() -> CaseResult:
    from backend.agents.quant_referee import referee_stock

    data = {
        "symbol": "600519",
        "close": 1800,
        "ma5": 1780,
        "ma20": 1700,
        "ma60": 1600,
        "rsi": 55,
        "dif": 1,
        "dea": 0.5,
        "macd": 1,
        "period_high": 1850,
        "period_low": 1500,
    }
    r = referee_stock(data, llm_final="买入")
    checks = [
        {"name": "status_ok", "ok": r.status in ("ok", "degraded"), "detail": r.status},
        {"name": "net_positive", "ok": r.net_score > 0, "detail": str(r.net_score)},
        {
            "name": "aligns_buy",
            "ok": r.llm_alignment in ("一致", "同向"),
            "detail": r.llm_alignment,
        },
    ]
    return CaseResult("quant_referee_bull", all(c["ok"] for c in checks), checks)


def _case_dsr_basic() -> CaseResult:
    from backend.quant.metrics_advanced import calc_deflated_sharpe, calc_probabilistic_sharpe

    sr = 1.0
    n_obs = 252
    psr = calc_probabilistic_sharpe(sr, n_obs)
    dsr1 = calc_deflated_sharpe(sr, n_obs, n_trials=1)
    dsr100 = calc_deflated_sharpe(sr, n_obs, n_trials=100)
    checks = [
        {
            "name": "psr_reference",
            "ok": abs(psr - 0.84062388) < 1e-8,
            "detail": f"psr={psr} sr={sr}",
        },
        {
            "name": "dsr_strictly_decreases_with_trials",
            "ok": dsr100 < dsr1,
            "detail": f"{dsr100}<{dsr1}",
        },
    ]
    return CaseResult("dsr_basic", all(c["ok"] for c in checks), checks)


_CASES: list[Callable[[], CaseResult]] = [
    _case_fabricated_price,
    _case_grounded_price,
    _case_hallucinated_citation,
    _case_quant_referee_bull,
    _case_dsr_basic,
]


def run_benchmark_suite() -> dict[str, Any]:
    """跑完全部确定性用例。永不抛出。"""
    results: list[CaseResult] = []
    for fn in _CASES:
        try:
            results.append(fn())
        except Exception as exc:  # noqa: BLE001
            results.append(CaseResult(fn.__name__, False, error=f"{type(exc).__name__}: {exc}"))
    passed = sum(1 for r in results if r.passed)
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "all_passed": passed == len(results),
        "cases": [r.to_dict() for r in results],
        "disclaimer": "确定性离线基准, 不调用 LLM, 不构成实盘策略评估。",
    }
