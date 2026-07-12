"""Deterministic research-trust scoring for evidence-backed analysis.

The score measures whether a research output is auditable, not whether its
market conclusion will be profitable. It deliberately rewards provenance,
dates, freshness, source quality, source diversity, and evidence coverage while
penalizing unresolved contradictions and unsupported claims.
"""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable as IterableABC
from datetime import datetime
from typing import Any, Iterable

from backend.quality.source_rank import SourceRanker

_UNKNOWN_SOURCES = {"", "unknown", "unavailable", "none", "n/a", "na", "未知"}
_HALF_LIFE_DAYS = {
    "price": 3.0,
    "prices": 3.0,
    "technical": 5.0,
    "fund_flow": 7.0,
    "news": 14.0,
    "sentiment": 14.0,
    "announcement": 120.0,
    "shareholder": 180.0,
    "report": 180.0,
    "research": 180.0,
    "fundamental": 365.0,
    "macro": 365.0,
}
_DEFAULT_HALF_LIFE_DAYS = 90.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, IterableABC) and not isinstance(value, (str, bytes, dict)):
        return list(value)
    return [value]


def normalize_evidence(items: Iterable[Any] | None) -> list[dict[str, Any]]:
    """Normalize Agent, RAG, and API evidence shapes into one small contract."""
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in _as_list(items):
        if isinstance(raw, str):
            item: dict[str, Any] = {"claim": raw.strip()}
        elif isinstance(raw, dict):
            item = {
                "claim": str(
                    raw.get("claim") or raw.get("title") or raw.get("preview") or raw.get("content_summary") or ""
                ).strip(),
                "type": str(raw.get("type") or raw.get("evidence_type") or raw.get("doc_type") or "other")
                .strip()
                .lower(),
                "source": str(raw.get("source") or raw.get("source_name") or "unknown").strip(),
                "data_date": str(
                    raw.get("data_date") or raw.get("published_at") or raw.get("date") or raw.get("period") or ""
                ).strip(),
                "source_url": str(raw.get("source_url") or raw.get("url") or "").strip(),
                "confidence": raw.get("confidence"),
                "evidence_id": str(raw.get("evidence_id") or raw.get("id") or "").strip(),
            }
        else:
            continue
        if not item.get("claim"):
            continue
        item.setdefault("type", "other")
        item.setdefault("source", "unknown")
        item.setdefault("data_date", "")
        item.setdefault("source_url", "")
        item.setdefault("confidence", None)
        item.setdefault("evidence_id", "")
        key = (item["claim"].casefold(), item["source"].casefold(), item["data_date"])
        if key not in seen:
            seen.add(key)
            normalized.append(item)
    return normalized


def _parse_data_date(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    iso_candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(iso_candidate)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for fmt in ("%Y/%m/%d", "%Y%m%d", "%Y-%m", "%Y/%m"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    quarter = re.fullmatch(r"(\d{4})\s*(?:-|年)?\s*[Qq]([1-4])", text)
    if quarter:
        year, number = int(quarter.group(1)), int(quarter.group(2))
        return datetime(year, number * 3, 1)
    year = re.fullmatch(r"(\d{4})(?:年|年报)?", text)
    if year:
        return datetime(int(year.group(1)), 12, 31)
    return None


def evidence_freshness(data_date: str, evidence_type: str = "other", now: float | None = None) -> float:
    """Return a type-aware 0..1 freshness score; missing/unparseable dates score 0."""
    parsed = _parse_data_date(data_date)
    if parsed is None:
        return 0.0
    current = float(now if now is not None else time.time())
    age_seconds = current - parsed.timestamp()
    if age_seconds < 0:
        return 0.0
    age_days = age_seconds / 86400.0
    half_life = _HALF_LIFE_DAYS.get(str(evidence_type or "").lower(), _DEFAULT_HALF_LIFE_DAYS)
    return _clamp(math.exp(-math.log(2) * age_days / half_life))


def _normalize_agent_signals(agent_signals: Any) -> list[dict[str, Any]]:
    if isinstance(agent_signals, dict):
        rows = []
        for key, value in agent_signals.items():
            row = dict(value) if isinstance(value, dict) else {}
            row.setdefault("agent", key)
            rows.append(row)
        return rows
    return [dict(row) for row in _as_list(agent_signals) if isinstance(row, dict)]


def assess_research_trust(
    evidence_items: Iterable[Any] | None,
    *,
    agent_signals: Any = None,
    contradictions: Iterable[Any] | None = None,
    missing_evidence: Iterable[Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Compute a deterministic, explainable 0..100 research-trust score."""
    evidence = normalize_evidence(evidence_items)
    signals = _normalize_agent_signals(agent_signals)
    contradictions_list = [str(value) for value in _as_list(contradictions) if str(value).strip()]
    missing_list = [str(value) for value in _as_list(missing_evidence) if str(value).strip()]

    if not evidence:
        return {
            "score": 0,
            "grade": "insufficient",
            "label": "证据不足",
            "evidence_count": 0,
            "source_count": 0,
            "metrics": {
                "coverage": 0.0,
                "source_completeness": 0.0,
                "date_completeness": 0.0,
                "freshness": 0.0,
                "source_quality": 0.0,
                "source_diversity": 0.0,
            },
            "penalties": {
                "contradictions": min(len(contradictions_list) * 5, 15),
                "missing_evidence": min(len(missing_list) * 7.5, 15),
            },
            "warnings": [{"code": "no_evidence", "message": "没有可审计证据，方向性结论应视为待验证假设。"}],
        }

    known_sources = [
        item["source"] for item in evidence if str(item.get("source", "")).strip().casefold() not in _UNKNOWN_SOURCES
    ]
    dated = [item for item in evidence if _parse_data_date(item.get("data_date", "")) is not None]
    ranker = SourceRanker()
    source_scores = [ranker.get_trust_score(str(item.get("source", "unknown")).casefold()) for item in evidence]
    freshness_scores = [evidence_freshness(item["data_date"], item["type"], now=now) for item in evidence]
    current = float(now if now is not None else time.time())
    future_dated = [
        item
        for item in evidence
        if (parsed := _parse_data_date(item.get("data_date", ""))) is not None and parsed.timestamp() > current
    ]

    if signals:
        supported = sum(
            1
            for signal in signals
            if bool(signal.get("has_evidence")) or bool(signal.get("evidence")) or bool(signal.get("evidence_ids"))
        )
        coverage = supported / len(signals)
    else:
        coverage = 1.0

    unique_sources = {source.casefold() for source in known_sources}
    metrics = {
        "coverage": _clamp(coverage),
        "source_completeness": len(known_sources) / len(evidence),
        "date_completeness": len(dated) / len(evidence),
        "freshness": sum(freshness_scores) / len(evidence),
        "source_quality": sum(source_scores) / len(evidence),
        "source_diversity": min(len(unique_sources) / 3.0, 1.0),
    }
    weights = {
        "coverage": 25.0,
        "source_completeness": 15.0,
        "date_completeness": 15.0,
        "freshness": 15.0,
        "source_quality": 15.0,
        "source_diversity": 15.0,
    }
    raw_score = sum(metrics[key] * weight for key, weight in weights.items())
    penalties = {
        "contradictions": min(len(contradictions_list) * 5, 15),
        "missing_evidence": min(len(missing_list) * 7.5, 15),
    }
    score = int(round(_clamp(raw_score - sum(penalties.values()), 0.0, 100.0)))
    if score >= 80:
        grade, label = "high", "高可信"
    elif score >= 60:
        grade, label = "medium", "中等可信"
    elif score >= 35:
        grade, label = "low", "低可信"
    else:
        grade, label = "insufficient", "证据不足"

    warnings: list[dict[str, str]] = []
    warning_rules = (
        (metrics["coverage"] < 0.6, "low_coverage", "超过 40% 的分析席位缺少证据绑定。"),
        (metrics["source_completeness"] < 0.7, "missing_source", "部分证据没有明确来源。"),
        (metrics["date_completeness"] < 0.7, "missing_date", "部分证据没有可解析的数据日期。"),
        (metrics["freshness"] < 0.5, "stale_evidence", "证据整体时效性偏低。"),
        (bool(future_dated), "future_date", "存在晚于研究截止日的证据日期，已按零时效处理。"),
        (
            len(evidence) >= 2 and metrics["source_diversity"] < 0.67,
            "low_diversity",
            "证据来源集中，缺少独立交叉验证。",
        ),
        (bool(contradictions_list), "contradictions", "存在尚未消解的证据或结论冲突。"),
        (bool(missing_list), "unsupported_claims", "存在已识别但尚未补证的关键结论。"),
    )
    for triggered, code, message in warning_rules:
        if triggered:
            warnings.append({"code": code, "message": message})

    return {
        "score": score,
        "grade": grade,
        "label": label,
        "evidence_count": len(evidence),
        "source_count": len(unique_sources),
        "metrics": {key: round(value, 3) for key, value in metrics.items()},
        "penalties": penalties,
        "warnings": warnings,
    }


def assess_agent_research(
    agent_results: dict[str, Any] | None,
    evidence_pool: Iterable[Any] | None = None,
    critic: dict[str, Any] | None = None,
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Assess a complete Agent run, including generated and retrieved evidence."""
    results = agent_results or {}
    evidence = _as_list(evidence_pool)
    signals = []
    contradictions: list[Any] = []
    missing: list[Any] = []
    for key, result in results.items():
        if not isinstance(result, dict) or not result.get("ok", True):
            continue
        generated = _as_list(result.get("evidence"))
        evidence.extend(generated)
        signals.append(
            {
                "agent": result.get("name") or key,
                "signal": result.get("signal", ""),
                "has_evidence": bool(generated or result.get("evidence_ids")),
            }
        )
        review = result.get("review") or {}
        contradictions.extend(_as_list(review.get("contradictions")))
        missing.extend(_as_list(review.get("missing_evidence")))
    for review in ((critic or {}).get("agents") or {}).values():
        if isinstance(review, dict):
            contradictions.extend(_as_list(review.get("contradictions")))
            missing.extend(_as_list(review.get("missing_evidence")))
    contradictions = list(dict.fromkeys(str(item).strip() for item in contradictions if str(item).strip()))
    missing = list(dict.fromkeys(str(item).strip() for item in missing if str(item).strip()))
    if not signals:
        return assess_research_trust(
            [],
            agent_signals=[{"agent": "research_output", "has_evidence": False}],
            contradictions=contradictions,
            missing_evidence=missing,
            now=now,
        )
    return assess_research_trust(
        evidence,
        agent_signals=signals,
        contradictions=contradictions,
        missing_evidence=missing,
        now=now,
    )


def compare_research_outputs(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    now: float | None = None,
) -> dict[str, Any]:
    """Compare two research outputs with the same deterministic scorecard."""

    def assess(payload: dict[str, Any]) -> dict[str, Any]:
        return assess_research_trust(
            payload.get("evidence", []),
            agent_signals=payload.get("agents"),
            contradictions=payload.get("contradictions"),
            missing_evidence=payload.get("missing_evidence"),
            now=now,
        )

    baseline_score = assess(baseline or {})
    candidate_score = assess(candidate or {})
    delta = candidate_score["score"] - baseline_score["score"]
    verdict = "candidate_better" if delta >= 3 else "baseline_better" if delta <= -3 else "tie"
    metric_delta = {
        key: round(candidate_score["metrics"][key] - baseline_score["metrics"][key], 3)
        for key in baseline_score["metrics"]
    }
    return {
        "baseline": baseline_score,
        "candidate": candidate_score,
        "score_delta": delta,
        "metric_delta": metric_delta,
        "verdict": verdict,
    }


def format_research_trust_markdown(trust: dict[str, Any]) -> str:
    """Render the scorecard as a compact report section."""
    metrics = trust.get("metrics") or {}
    lines = [
        "## 研究可信度",
        "",
        f"> {trust.get('score', 0)}/100 · {trust.get('label', '证据不足')} | "
        f"证据 {trust.get('evidence_count', 0)} 条 | 独立来源 {trust.get('source_count', 0)} 个",
        "",
        f"- 证据覆盖率: {float(metrics.get('coverage', 0)):.0%}",
        f"- 来源完整度: {float(metrics.get('source_completeness', 0)):.0%}",
        f"- 日期完整度: {float(metrics.get('date_completeness', 0)):.0%}",
        f"- 时效性: {float(metrics.get('freshness', 0)):.0%}",
        f"- 来源质量: {float(metrics.get('source_quality', 0)):.0%}",
    ]
    warnings = trust.get("warnings") or []
    if warnings:
        lines.extend(["", "需要复核:"])
        lines.extend(f"- {warning.get('message', '')}" for warning in warnings[:5])
    return "\n".join(lines)
