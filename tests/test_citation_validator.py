"""数值/引用 Citation Validator 测试 — 纯函数、离线、失败安全。

原则:研报与 Agent 文本中的关键数字应能 trace 到 stock_data 或 evidence,
否则标为未核验并下调可发布信任,绝不静默「干净成功」。
"""

from __future__ import annotations

import pytest

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

    def test_single_digit_price_is_not_skipped(self):
        facts = {**_facts(), "close": 8.0}
        r = validate_citations("当前股价 8 元。", stock_data=facts)

        assert r.n_claims == 1
        assert r.n_verified == 1
        assert r.claims[0].matched_field == "close"

    def test_negative_dif_preserves_sign(self):
        facts = {**_facts(), "dif": -0.5}
        verified = validate_citations("DIF 为 -0.5。", stock_data=facts)
        opposite = validate_citations("DIF 为 0.5。", stock_data=facts)

        assert verified.n_claims == 1
        assert verified.n_verified == 1
        assert verified.claims[0].value == -0.5
        assert opposite.n_unverified == 1

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

    def test_price_cannot_match_rsi_with_the_same_value(self):
        facts = {**_facts(), "close": 1680.5, "rsi": 55.0}
        r = validate_citations("当前股价 55 元。", stock_data=facts)

        assert r.n_claims == 1
        assert r.n_unverified == 1
        assert r.claims[0].kind == "close"
        assert r.claims[0].matched_field == ""

    def test_percentage_cannot_match_close_with_the_same_value(self):
        r = validate_citations("今日涨幅 1680.5%。", stock_data=_facts())

        assert r.n_claims == 1
        assert r.n_unverified == 1
        assert r.claims[0].kind == "day_change"
        assert r.claims[0].matched_field == ""

    @pytest.mark.parametrize(
        ("text", "actual_change"),
        [
            ("今日下跌 1.25%。", 1.25),
            ("今日上涨 1.25%。", -1.25),
        ],
    )
    def test_percentage_direction_cannot_match_opposite_move(self, text, actual_change):
        facts = {**_facts(), "day_change": actual_change}
        r = validate_citations(text, stock_data=facts)

        assert r.n_claims == 1
        assert r.n_unverified == 1

    def test_negative_direction_is_applied_to_unsigned_magnitude(self):
        facts = {**_facts(), "day_change": -1.25}
        r = validate_citations("今日下跌 1.25%。", stock_data=facts)

        assert r.n_verified == 1
        assert r.claims[0].value == -1.25

    @pytest.mark.parametrize("text", ["RSI 为 58.3%。", "今日涨幅 1.25 元。"])
    def test_incompatible_numeric_units_are_unverified(self, text):
        r = validate_citations(text, stock_data=_facts())

        assert r.n_claims == 1
        assert r.n_unverified == 1

    def test_day_change_cannot_match_period_change_with_the_same_value(self):
        facts = {**_facts(), "day_change": 9.9, "period_change": 1.25}
        r = validate_citations("今日涨幅 1.25%。", stock_data=facts)

        assert r.n_claims == 1
        assert r.n_unverified == 1
        assert r.claims[0].matched_field == ""

    def test_equal_numeric_values_remain_separate_semantic_claims(self):
        facts = {**_facts(), "close": 55.0, "rsi": 55.0}
        r = validate_citations("收盘价 55 元，RSI 55。", stock_data=facts)

        assert r.n_claims == 2
        assert r.n_verified == 2
        assert {(c.kind, c.matched_field) for c in r.claims} == {
            ("close", "close"),
            ("rsi", "rsi"),
        }

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
        assert r.status == DEGRADED
        assert r.n_citation_bad == 1

    def test_empty_pool_flags_hallucinated_reference(self):
        r = validate_citations("正文声称已有证据 [99]。", stock_data=_facts(), evidence_pool=[])

        assert r.n_citation_ok == 0
        assert r.n_citation_bad == 1
        assert any("[99]" in issue and "无可用证据池" in issue for issue in r.issues)


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


class TestReportTemplateRegression:
    def test_system_metadata_is_not_treated_as_market_data(self):
        facts = {
            **_facts(),
            "ma60": 1500.0,
            "total_amount": 20.0,
        }
        report = """【完整研报正文】
一、核心结论
- 标的: 贵州茅台 (600519)
- 平均置信度: 80.0%
- 研究可信度: 75/100 (证据良好)
- 数据截止日: 2026-07-15；行情日期: 2026-07-14
- 研究快照: a12b34c56d78e90f

二、行情与趋势判断
- 最新价: 1680.50 元，当日涨跌 1.25%。
- 近 30 日区间涨跌 5.6%，区间高低点 1720 / 1550 元。
- 均线: MA5 1670，MA20 1600，MA60 1500。
- 成交: 当日成交量 1,200,000 手，区间成交额 20.00 亿元。

三、多智能体会签摘要
- 专家席位: 3 / 5 完成，2 个席位降级。

四、证据与可信度审计
- 证据数量: 12 条，独立来源: 3 个。
- 证据覆盖率: 80%，来源完整度: 75%，日期完整度: 90%。
- 本次模型调用成本 20 美元。"""

        r = validate_citations(report, stock_data=facts)
        assert r.status == OK
        assert r.n_claims == 10
        assert r.n_verified == 10
        assert r.n_unverified == 0
        assert r.suggest_confidence_cap is None
        assert {c.matched_field for c in r.claims} == {
            "close",
            "day_change",
            "period_change",
            "period_high",
            "period_low",
            "ma5",
            "ma20",
            "ma60",
            "volume",
            "total_amount",
        }

    def test_template_still_flags_fabricated_price_and_change(self):
        report = "最新价: 99999 元，当日涨幅 1680.5%。近 30 日分析包含 12 条证据。"

        r = validate_citations(report, stock_data=_facts())

        assert r.n_claims == 2
        assert r.n_unverified == 2
        assert {c.kind for c in r.claims} == {"close", "day_change"}
        assert r.suggest_confidence_cap == 55.0
