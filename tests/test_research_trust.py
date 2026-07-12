"""Deterministic research-trust scorecard tests."""

from __future__ import annotations

from datetime import datetime

from backend.quality.research_trust import (
    assess_agent_research,
    assess_research_trust,
    compare_research_outputs,
    evidence_freshness,
    normalize_evidence,
)

NOW = datetime(2026, 7, 12).timestamp()


def _evidence(source: str, evidence_type: str = "news", date: str = "2026-07-12") -> dict:
    return {
        "claim": f"{source} confirms revenue growth",
        "source": source,
        "type": evidence_type,
        "data_date": date,
    }


def test_empty_research_is_explicitly_insufficient():
    result = assess_research_trust([], now=NOW)

    assert result["score"] == 0
    assert result["grade"] == "insufficient"
    assert result["warnings"][0]["code"] == "no_evidence"


def test_complete_multi_source_research_scores_high():
    result = assess_research_trust(
        [_evidence("cninfo"), _evidence("tushare"), _evidence("cls")],
        agent_signals=[{"agent": "fundamental", "signal": "买入", "has_evidence": True}],
        now=NOW,
    )

    assert result["score"] >= 80
    assert result["grade"] == "high"
    assert result["source_count"] == 3
    assert result["metrics"]["date_completeness"] == 1.0


def test_missing_provenance_and_date_are_visible_and_reduce_score():
    complete = assess_research_trust([_evidence("cninfo")], now=NOW)
    incomplete = assess_research_trust([{"claim": "revenue grew"}], now=NOW)

    assert incomplete["score"] < complete["score"]
    assert {warning["code"] for warning in incomplete["warnings"]} >= {
        "missing_source",
        "missing_date",
        "stale_evidence",
    }


def test_freshness_is_type_aware():
    old_date = "2026-01-12"

    news = evidence_freshness(old_date, "news", now=NOW)
    fundamentals = evidence_freshness(old_date, "fundamental", now=NOW)

    assert news < 0.01
    assert fundamentals > 0.6


def test_future_dated_evidence_scores_zero_freshness_and_warns():
    result = assess_research_trust(
        [_evidence("cninfo", date="2026-07-13")],
        now=NOW,
    )

    assert result["metrics"]["freshness"] == 0.0
    assert "future_date" in {warning["code"] for warning in result["warnings"]}


def test_agent_coverage_counts_bound_evidence():
    result = assess_agent_research(
        {
            "fundamental": {"ok": True, "signal": "买入", "evidence": [_evidence("cninfo")]},
            "technical": {"ok": True, "signal": "观望", "evidence": [], "evidence_ids": []},
        },
        now=NOW,
    )

    assert result["metrics"]["coverage"] == 0.5
    assert "low_coverage" in {warning["code"] for warning in result["warnings"]}


def test_critic_penalties_are_bounded_and_explained():
    result = assess_research_trust(
        [_evidence("cninfo"), _evidence("tushare"), _evidence("cls")],
        contradictions=["a", "b", "c", "d"],
        missing_evidence=["x", "y", "z"],
        now=NOW,
    )

    assert result["penalties"] == {"contradictions": 15, "missing_evidence": 15}
    assert result["score"] < 80


def test_compare_research_outputs_reports_metric_deltas():
    comparison = compare_research_outputs(
        {"evidence": [{"claim": "unsupported"}]},
        {"evidence": [_evidence("cninfo"), _evidence("tushare"), _evidence("cls")]},
        now=NOW,
    )

    assert comparison["verdict"] == "candidate_better"
    assert comparison["score_delta"] > 0
    assert comparison["metric_delta"]["source_diversity"] > 0


def test_normalize_evidence_accepts_rag_pool_aliases_and_deduplicates():
    raw = {
        "preview": "earnings release",
        "doc_type": "announcement",
        "source": "cninfo",
        "published_at": "2026-07-10",
        "evidence_id": "ev-1",
    }

    result = normalize_evidence([raw, raw])

    assert result == [
        {
            "claim": "earnings release",
            "type": "announcement",
            "source": "cninfo",
            "data_date": "2026-07-10",
            "source_url": "",
            "confidence": None,
            "evidence_id": "ev-1",
        }
    ]


def test_scalar_strings_are_single_items_not_character_sequences():
    evidence = normalize_evidence("revenue grew")
    result = assess_research_trust(
        "revenue grew",
        contradictions="single conflict",
        missing_evidence="missing filing",
        now=NOW,
    )

    assert len(evidence) == 1
    assert evidence[0]["claim"] == "revenue grew"
    assert result["evidence_count"] == 1
    assert result["penalties"] == {"contradictions": 5, "missing_evidence": 7.5}
