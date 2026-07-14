"""确定性 Quant Referee 测试 — 纯规则、离线、失败安全。

Quant Referee 与 LLM 辩论并行:从行情/指标算出规则信号,作为 grounding,
不预测、不构成买卖指令。
"""

from __future__ import annotations

from backend.agents.quant_referee import (
    DEGRADED,
    INSUFFICIENT,
    OK,
    format_referee_section,
    referee_stock,
)


def _bullish_stock() -> dict:
    return {
        "symbol": "600519",
        "name": "贵州茅台",
        "close": 1800.0,
        "ma5": 1780.0,
        "ma20": 1700.0,
        "ma60": 1600.0,
        "rsi": 55.0,
        "dif": 12.0,
        "dea": 8.0,
        "macd": 8.0,
        "period_high": 1850.0,
        "period_low": 1500.0,
        "vol_ratio": 1.4,
    }


def _bearish_stock() -> dict:
    return {
        "symbol": "000001",
        "name": "平安银行",
        "close": 10.0,
        "ma5": 10.5,
        "ma20": 11.0,
        "ma60": 12.0,
        "rsi": 78.0,
        "dif": -1.2,
        "dea": -0.5,
        "macd": -1.4,
        "period_high": 13.0,
        "period_low": 9.5,
        "vol_ratio": 0.6,
    }


class TestStance:
    def test_bullish_alignment_is_net_positive(self):
        r = referee_stock(_bullish_stock())
        assert r.status == OK
        assert r.net_score > 0
        assert r.stance in ("偏多", "多头占优")
        assert any(s.rule_id == "ma_alignment" for s in r.signals)
        assert any(s.direction == "bullish" for s in r.signals)

    def test_bearish_overbought_is_net_negative(self):
        r = referee_stock(_bearish_stock())
        assert r.status == OK
        assert r.net_score < 0
        assert r.stance in ("偏空", "空头占优")
        assert any(s.rule_id == "rsi" for s in r.signals)

    def test_missing_price_is_insufficient(self):
        r = referee_stock({"symbol": "x"})
        assert r.status == INSUFFICIENT
        assert r.net_score == 0.0
        assert r.signals == []

    def test_partial_indicators_still_ok(self):
        r = referee_stock({"close": 100.0, "ma5": 99.0, "ma20": 95.0})
        assert r.status in (OK, DEGRADED)
        assert len(r.signals) >= 1


class TestSafety:
    def test_dirty_input_does_not_raise(self):
        r = referee_stock({"close": "bad", "rsi": None, "ma5": "x"})
        assert r.status in (INSUFFICIENT, DEGRADED, OK)
        d = r.to_dict()
        assert "disclaimer" in d
        assert d["status"] in (INSUFFICIENT, DEGRADED, OK)

    def test_to_dict_roundtrip_fields(self):
        r = referee_stock(_bullish_stock())
        d = r.to_dict()
        assert d["n_bull"] + d["n_bear"] + d["n_neutral"] == len(d["signals"])
        assert isinstance(d["signals"], list)
        assert d["symbol"] == "600519"


class TestLlmAlignment:
    def test_aligns_with_buy_summary(self):
        r = referee_stock(_bullish_stock(), llm_final="买入")
        assert r.llm_alignment in ("一致", "同向", "支持")

    def test_conflicts_with_sell_on_bullish_bars(self):
        r = referee_stock(_bullish_stock(), llm_final="卖出")
        assert r.llm_alignment in ("冲突", "背离", "不一致")

    def test_no_llm_is_unknown(self):
        r = referee_stock(_bullish_stock())
        assert r.llm_alignment in ("未知", "未对比")


class TestFormat:
    def test_section_contains_stance_and_disclaimer(self):
        r = referee_stock(_bullish_stock())
        text = format_referee_section(r)
        assert "Quant Referee" in text or "量化裁判" in text
        assert r.stance in text
        assert "不构成" in text or "免责" in text or "研究" in text

    def test_insufficient_section_is_empty_or_degraded_note(self):
        r = referee_stock({})
        text = format_referee_section(r)
        assert isinstance(text, str)
