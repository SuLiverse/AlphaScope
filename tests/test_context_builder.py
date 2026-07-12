"""Context builder regression tests."""

from __future__ import annotations

from unittest.mock import patch

from backend.runtime.context_builder import (
    build_market_brief,
    fetch_evidence_pool,
    format_evidence_context,
)


def test_market_brief_handles_minimal_stock_data():
    brief = build_market_brief({"symbol": "600519", "name": "贵州茅台"})

    assert "贵州茅台" in brief
    assert "600519" in brief
    assert "暂无可用价格数据" in brief


def test_market_brief_accepts_change_pct_alias():
    brief = build_market_brief(
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "close": 100.0,
            "change_pct": 1.2,
            "volume": 10000,
            "amount": 2.5,
        }
    )

    assert "¥100.00" in brief
    assert "+1.20%" in brief
    assert "2.5 亿元" in brief


def test_market_brief_surfaces_question_and_historical_cutoff():
    brief = build_market_brief(
        {
            "symbol": "600519",
            "name": "贵州茅台",
            "research_question": "利润增长是否可持续？",
            "as_of": "2026-06-30",
        }
    )

    assert "研究问题: 利润增长是否可持续？" in brief
    assert "数据截止日: 2026-06-30" in brief
    assert "不得使用该日期之后的信息" in brief


def test_fetch_evidence_pool_filters_future_and_undated_results_then_renumbers():
    results = [
        {
            "id": "future",
            "text": "future",
            "metadata": {"source": "cls", "published_at": "2026-07-01", "doc_type": "news"},
        },
        {
            "id": "undated",
            "text": "undated",
            "metadata": {"source": "cls", "published_at": "", "doc_type": "news"},
        },
        {
            "id": "valid",
            "text": "valid",
            "metadata": {"source": "cninfo", "published_at": "2026-06-30", "doc_type": "announcement"},
        },
    ]
    with patch("backend.pipeline.search_evidence", return_value=results) as search:
        pool = fetch_evidence_pool(
            "600519",
            "贵州茅台",
            limit=2,
            as_of="2026-06-30",
            research_question="利润增长",
        )

    assert [item["evidence_id"] for item in pool] == ["valid"]
    assert pool[0]["number"] == 1
    assert search.call_args.kwargs["n_results"] == 8
    assert "利润增长" in search.call_args.args[0]


def test_format_evidence_context_uses_exact_pool_numbers_and_cutoff():
    pool = [
        {
            "number": 1,
            "evidence_id": "ev-1",
            "doc_type": "announcement",
            "source": "cninfo",
            "source_url": "https://example.test/1",
            "published_at": "2026-06-30",
            "preview": "业绩公告",
        }
    ]

    context = format_evidence_context(pool, as_of="2026-06-30")

    assert "[1]" in context
    assert "数据截止日: 2026-06-30" in context
    assert "业绩公告" in context
