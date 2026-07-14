"""数值/引用 Citation Validator 测试 — 纯函数、离线、失败安全。

原则:研报与 Agent 文本中的关键数字应能 trace 到 stock_data 或 evidence,
否则标为未核验并下调可发布信任,绝不静默「干净成功」。
"""

from __future__ import annotations

from backend.quality.citation_validator import (
    DEGRADED,
    OK,
    format_citation_section,
    validate_citations,
)


def _facts() -> dict:
    return {
        "symbol": "600519",
        "name": "贵州茅台",
        "close": 1680.50,
        "day_change": 1.25,
        "period_change": 5.6,
        "period_high": 1720.0,
        "period_low": 1550.0,
        "ma5": 1670.0,
        "ma20": 1600.0,
        "rsi": 58.3,
        "volume": 1_200_000,
    }


class TestNumericGrounding:
    def test_matching_close_is_verified(self):
        text = "最新价约 1680.50 元,基本面稳健。"
        r = validate_citations(text, stock_data=_facts())
        assert r.status == OK
        assert r.n_verified >= 1
        assert r.n_unverified == 0 or r.grounding_score >= 0.5

    def test_fabricated_price_is_unverified(self):
        text = "当前股价 99999 元,建议满仓。"
        r = validate_citations(text, stock_data=_facts())
        assert r.n_unverified >= 1
        assert r.grounding_score < 1.0
        assert any(c.status == "unverified" for c in r.claims)

    def test_percentage_near_day_change_verified(self):
        text = "今日涨幅 1.25%,成交活跃。"
        r = validate_citations(text, stock_data=_facts())
        assert r.n_verified >= 1

    def test_empty_text_is_ok_empty(self):
        r = validate_citations("", stock_data=_facts())
        assert r.n_claims == 0
        assert r.status in (OK, DEGRADED)


class TestEvidenceRefs:
    def test_valid_bracket_citation_verified(self):
        pool = [{"id": "ev1", "title": "公告"}, {"id": "ev2", "title": "新闻"}]
        # number_to_id style: [1] -> first evidence
        text = "根据公告 [1] 与新闻 [2],业绩稳健。"
        r = validate_citations(text, stock_data=_facts(), evidence_pool=pool)
        assert r.n_citation_ok >= 2
        assert r.n_citation_bad == 0

    def test_hallucinated_bracket_citation_flagged(self):
        pool = [{"id": "ev1"}]
        text = "参见证据 [1] 与 [9]。"
        r = validate_citations(text, stock_data=_facts(), evidence_pool=pool)
        assert r.n_citation_bad >= 1

    def test_no_pool_means_citations_skipped_or_degraded(self):
        text = "参见 [1]。"
        r = validate_citations(text, stock_data=_facts(), evidence_pool=None)
        assert r.status in (OK, DEGRADED)


class TestSafety:
    def test_none_inputs_do_not_raise(self):
        r = validate_citations(None, stock_data=None, evidence_pool=None)  # type: ignore[arg-type]
        assert r is not None
        d = r.to_dict()
        assert "grounding_score" in d
        assert "disclaimer" in d

    def test_agent_blob_dict_aggregated(self):
        agents = {
            "fund": {"reason": "收盘 1680.5, 涨 1.25%", "signal": "买入"},
            "tech": {"reason": "RSI 58.3 中性", "signal": "观望"},
        }
        r = validate_citations(
            agents=agents,
            research_report="综合最新价 1680.50。",
            stock_data=_facts(),
        )
        assert r.n_claims >= 1
        assert r.n_verified >= 1


class TestFormatAndConfidence:
    def test_low_grounding_suggests_downgrade(self):
        text = "目标价 88888, 必涨到 99999。"
        r = validate_citations(text, stock_data=_facts())
        assert r.suggest_confidence_cap is not None
        assert r.suggest_confidence_cap < 100

    def test_section_mentions_unverified(self):
        text = "股价 77777 元。"
        r = validate_citations(text, stock_data=_facts())
        section = format_citation_section(r)
        assert "引用" in section or "核验" in section or "Citation" in section
