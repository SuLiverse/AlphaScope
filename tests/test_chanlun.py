"""Chanlun structure engine tests (plan 027). Offline, deterministic, no network."""

from __future__ import annotations

from datetime import datetime, timedelta

from backend.quant.chanlun import (
    Stroke,
    analyze_chanlun,
    find_zhongshus,
)


def _d(i: int) -> str:
    return (datetime(2024, 1, 1) + timedelta(days=i)).strftime("%Y-%m-%d")


def _bar(i: int, o: float, h: float, lo: float, c: float) -> dict:
    return {"date": _d(i), "open": o, "high": h, "low": lo, "close": c, "volume": 10000, "symbol": "T"}


def _leg(start_i: int, n: int, start: float, end: float) -> list[dict]:
    """Monotone leg with no inclusion (each bar makes a new high *and* new low)."""
    step = (end - start) / n
    bars = []
    for j in range(n):
        o = start + step * j
        c = start + step * (j + 1)
        if step >= 0:
            h = c + abs(step) * 0.2
            lo = o - abs(step) * 0.05
        else:
            h = o + abs(step) * 0.05
            lo = c - abs(step) * 0.2
        bars.append(_bar(start_i + j, o, h, lo, c))
    return bars


def _stroke(direction: str, start: float, end: float, i: int) -> Stroke:
    return Stroke(
        direction=direction,
        start_price=start,
        end_price=end,
        start_date=_d(i),
        end_date=_d(i + 5),
        start_idx=i,
        end_idx=i + 1,
        start_merged=i * 5,
        end_merged=i * 5 + 5,
    )


class TestInsufficient:
    def test_too_few_bars(self):
        bars = [_bar(i, 10, 10.2, 9.8, 10) for i in range(5)]
        r = analyze_chanlun(bars, "T")
        assert r.status == "insufficient"
        assert r.fractals == []
        assert r.strokes == []
        assert r.zhongshus == []

    def test_empty(self):
        r = analyze_chanlun([], "T")
        assert r.status == "insufficient"

    def test_dirty_ohlc(self):
        bars = [_bar(i, 10, 9.0, 11.0, 10) for i in range(15)]  # high < low
        r = analyze_chanlun(bars, "T")
        assert r.status == "insufficient"


class TestZhongshuThreeStrokeRule:
    def test_two_overlapping_strokes_are_not_a_zhongshu(self):
        strokes = [
            _stroke("up", 10.0, 20.0, 0),
            _stroke("down", 20.0, 12.0, 1),
        ]
        assert find_zhongshus(strokes) == []

    def test_three_overlapping_strokes_form_zhongshu(self):
        strokes = [
            _stroke("up", 10.0, 20.0, 0),
            _stroke("down", 20.0, 12.0, 1),
            _stroke("up", 12.0, 18.0, 2),
        ]
        zs = find_zhongshus(strokes)
        assert len(zs) == 1
        assert zs[0].zd == 12.0
        assert zs[0].zg == 18.0

    def test_three_non_overlapping_strokes_form_no_zhongshu(self):
        strokes = [
            _stroke("up", 10.0, 20.0, 0),
            _stroke("down", 20.0, 8.0, 1),
            _stroke("up", 8.0, 9.0, 2),
        ]
        assert find_zhongshus(strokes) == []


class TestAnalyzeZigzag:
    def _overlap_zigzag(self) -> list[dict]:
        # down → up → down → up → short down to close the third stroke
        bars = []
        bars += _leg(0, 6, 20.0, 10.0)
        bars += _leg(6, 6, 10.0, 20.0)
        bars += _leg(12, 6, 20.0, 12.0)
        bars += _leg(18, 6, 12.0, 18.0)
        bars += _leg(24, 4, 18.0, 16.0)
        return bars

    def _no_overlap_zigzag(self) -> list[dict]:
        bars = []
        bars += _leg(0, 6, 20.0, 10.0)
        bars += _leg(6, 6, 10.0, 20.0)
        bars += _leg(12, 6, 20.0, 8.0)
        bars += _leg(18, 6, 8.0, 9.0)
        bars += _leg(24, 4, 9.0, 8.6)
        return bars

    def test_overlap_case_detects_strokes_and_zhongshu(self):
        r = analyze_chanlun(self._overlap_zigzag(), "T")
        assert r.status == "ok"
        assert len(r.strokes) >= 3
        assert len(r.zhongshus) >= 1

    def test_no_overlap_case_has_strokes_but_no_zhongshu(self):
        r = analyze_chanlun(self._no_overlap_zigzag(), "T")
        assert r.status == "ok"
        assert len(r.strokes) >= 2
        assert r.zhongshus == []

    def test_two_legs_not_enough_for_zhongshu(self):
        bars = _leg(0, 6, 20.0, 10.0) + _leg(6, 6, 10.0, 20.0) + _leg(12, 6, 20.0, 12.0)
        r = analyze_chanlun(bars, "T")
        assert r.status == "ok"
        # At most two completed strokes (up + down); two-stroke overlap ≠ 中枢.
        assert len(r.zhongshus) == 0


class TestReportShape:
    def test_to_dict_has_disclaimer(self):
        bars = [_bar(i, 10 + i * 0.1, 10.3 + i * 0.1, 9.8 + i * 0.1, 10.1 + i * 0.1) for i in range(15)]
        d = analyze_chanlun(bars, "600519").to_dict()
        for key in (
            "status",
            "symbol",
            "bars_used",
            "fractals",
            "strokes",
            "zhongshus",
            "divergences",
            "note",
            "disclaimer",
        ):
            assert key in d
        assert "不构成买卖建议" in d["disclaimer"]
        assert d["symbol"] == "600519"

    def test_deterministic(self):
        bars = _leg(0, 6, 20.0, 10.0) + _leg(6, 6, 10.0, 20.0) + _leg(12, 6, 20.0, 12.0) + _leg(18, 6, 12.0, 18.0)
        a = analyze_chanlun(bars, "T").to_dict()
        b = analyze_chanlun(bars, "T").to_dict()
        assert a == b


class TestApiPayload:
    def test_local_chanlun_payload(self):
        from unittest.mock import patch

        from backend.api.quant_core import _run_chanlun_local
        from backend.api.quant_schemas import ChanlunRequestBody

        bars = _leg(0, 6, 20.0, 10.0) + _leg(6, 6, 10.0, 20.0) + _leg(12, 6, 20.0, 12.0) + _leg(18, 6, 12.0, 18.0)
        body = ChanlunRequestBody(symbol="600519", start_date="2024-01-01", end_date="2024-12-31", lookback=120)
        with patch("backend.api.quant_core._require_bars", return_value=(bars, "local_price_store")):
            payload = _run_chanlun_local(body)
        assert payload["status"] == "ok"
        assert "不构成买卖建议" in payload["disclaimer"]
        assert payload["data_source"] == "local_price_store"
        assert "action" not in payload


class TestStrategyContract:
    def test_chanlun_structure_signal_length(self):
        from backend.quant.strategies.chanlun_structure import ChanlunStructureStrategy

        bars = _leg(0, 6, 20.0, 10.0) + _leg(6, 6, 10.0, 20.0) + _leg(12, 6, 20.0, 12.0) + _leg(18, 6, 12.0, 18.0)
        sigs = ChanlunStructureStrategy().generate_signals(bars)
        assert len(sigs) == len(bars)
        assert all(s.action in {"buy", "sell", "hold"} for s in sigs)


class TestExpertBrief:
    def test_format_section_on_ok_report(self):
        from backend.quant.chanlun import format_chanlun_section

        bars = _leg(0, 6, 20.0, 10.0) + _leg(6, 6, 10.0, 20.0) + _leg(12, 6, 20.0, 12.0) + _leg(18, 6, 12.0, 18.0)
        section = format_chanlun_section(analyze_chanlun(bars, "T"))
        assert "【缠论结构标注】" in section
        assert "不构成买卖建议" in section

    def test_format_section_empty_when_insufficient(self):
        from backend.quant.chanlun import format_chanlun_section

        assert format_chanlun_section(analyze_chanlun([], "T")) == ""

    def test_analysis_stock_data_injects_brief(self):
        from backend.api.analysis_stock_data import build_analysis_stock_data

        bars = _leg(0, 6, 20.0, 10.0) + _leg(6, 6, 10.0, 20.0) + _leg(12, 6, 20.0, 12.0) + _leg(18, 6, 12.0, 18.0)
        data = build_analysis_stock_data("T", "测试", bars)
        assert "【缠论结构标注】" in (data.get("chanlun_brief") or "")

    def test_market_brief_includes_chanlun_block(self):
        from backend.runtime.context_builder import build_market_brief

        brief = build_market_brief(
            {"symbol": "T", "name": "测试", "close": 10.0, "chanlun_brief": "【缠论结构标注】\n- 中枢: 无"}
        )
        assert "【缠论结构标注】" in brief

    def test_only_chanlun_expert_keeps_geometry(self):
        from backend.expert_panel import ExpertConfig, _build_user_message

        brief = "行情摘要\n【缠论结构标注】\n- 中枢 10-12"
        chan = ExpertConfig(key="chanlun", name="缠论", style="缠论")
        other = ExpertConfig(key="buffett", name="巴菲特", style="价值")
        assert "【缠论结构标注】" in _build_user_message(chan, brief, "茅台")
        assert "【缠论结构标注】" not in _build_user_message(other, brief, "茅台")

    def test_prompt_no_longer_demands_entry_points(self):
        from pathlib import Path

        text = Path("prompts/experts/chanlun.md").read_text(encoding="utf-8")
        assert "明确入场点和止损位" not in text
        assert "不编造" in text
