"""Reproducible research snapshot and cutoff tests."""

from __future__ import annotations

from backend.runtime.research_snapshot import (
    as_of_timestamp,
    build_research_snapshot,
    evidence_on_or_before,
    normalize_date,
)


def _stock(**overrides):
    data = {
        "symbol": "600519",
        "as_of": "2026-06-30",
        "price_data_date": "2026-06-30",
        "research_question": "利润增长是否可持续？",
    }
    data.update(overrides)
    return data


def test_normalize_date_accepts_common_storage_formats():
    assert normalize_date("2026-06-30 15:00:00") == "2026-06-30"
    assert normalize_date("2026/06/30") == "2026-06-30"
    assert normalize_date("20260630") == "2026-06-30"
    assert normalize_date("not-a-date") == ""


def test_historical_cutoff_rejects_future_and_undated_evidence():
    assert evidence_on_or_before("2026-06-30", "2026-06-30") is True
    assert evidence_on_or_before("2026-07-01", "2026-06-30") is False
    assert evidence_on_or_before("", "2026-06-30") is False
    assert evidence_on_or_before("", "") is True
    assert as_of_timestamp("2026-06-30") is not None


def test_snapshot_hash_is_stable_across_evidence_order():
    evidence = [
        {"evidence_id": "b", "source": "cls", "published_at": "2026-06-29"},
        {"evidence_id": "a", "source": "cninfo", "published_at": "2026-06-28"},
    ]

    first = build_research_snapshot(_stock(), evidence)
    second = build_research_snapshot(_stock(), list(reversed(evidence)))

    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["cutoff_enforced"] is True
    assert first["latest_evidence_date"] == "2026-06-29"


def test_snapshot_hash_changes_with_question_or_cutoff():
    base = build_research_snapshot(_stock(), [])
    changed_question = build_research_snapshot(_stock(research_question="估值是否合理？"), [])
    changed_cutoff = build_research_snapshot(_stock(as_of="2026-06-29"), [])

    assert len({base["snapshot_id"], changed_question["snapshot_id"], changed_cutoff["snapshot_id"]}) == 3


def test_snapshot_hash_changes_when_price_or_evidence_content_is_corrected():
    evidence = [{"evidence_id": "a", "source": "cninfo", "published_at": "2026-06-28", "preview": "old"}]
    base = build_research_snapshot(_stock(close=100), evidence)
    changed_price = build_research_snapshot(_stock(close=101), evidence)
    changed_content = build_research_snapshot(_stock(close=100), [{**evidence[0], "preview": "corrected"}])

    assert len({base["snapshot_id"], changed_price["snapshot_id"], changed_content["snapshot_id"]}) == 3


def test_dynamic_snapshot_warns_about_reproducibility_gaps():
    snapshot = build_research_snapshot(
        _stock(as_of="", price_data_date=""),
        [{"evidence_id": "x", "source": "unknown", "published_at": ""}],
    )

    assert snapshot["cutoff_enforced"] is False
    assert snapshot["undated_evidence_count"] == 1
    assert len(snapshot["warnings"]) == 3
