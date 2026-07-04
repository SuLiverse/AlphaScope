"""M3 · 研报质量机械门控 测试(纯逻辑，不联网)。"""

from __future__ import annotations

import pytest

from backend.quality.report_gate import (
    ReportBlockedError,
    gate_or_raise,
    run_gate,
)

# 一份"干净"报告:足够长 + 含定量 + 有免责声明 + 无废话/占位
CLEAN = (
    "贵州茅台 2025Q1 营收同比 +18%，毛利率 91.2%，ROE 31%。DCF 内在价值 ¥1850，"
    "较现价 ¥1620 安全边际 +14%；但 Comps 显示 PE 处同业 78% 分位，存在分歧。"
    "**风险提示**: 以上分析仅供参考，不构成投资建议。投资有风险，入市需谨慎。"
)
GOOD_EC = {
    "coverage": 0.85,
    "overall_confidence": 0.72,
    "contradictions": [],
    "missing_evidence": [],
}


class TestIndividualChecks:
    def test_placeholder_is_critical(self):
        r = run_gate("这是一段足够长的报告正文，用于占位检查测试。" * 3 + " [TODO] 补充结论。风险提示")
        assert any(i["category"] == "placeholder" and i["severity"] == "critical" for i in r["issues"])
        assert r["passed"] is False

    def test_fluff_critical_phrase(self):
        text = "公司基本面良好，建议买入。" * 5 + " 风险提示：仅供参考。"
        r = run_gate(text)
        assert any(i["category"] == "fluff" and i["severity"] == "critical" for i in r["issues"])
        assert r["passed"] is False

    def test_fluff_warning_phrase(self):
        text = "公司业绩稳健增长，营收 +12%，净利 +9%，估值合理。" * 3 + " 风险提示：仅供参考。"
        r = run_gate(text)
        assert any(i["category"] == "fluff" and i["severity"] == "warning" for i in r["issues"])

    def test_low_coverage_critical(self):
        r = run_gate(
            CLEAN,
            evidence_chain={
                "coverage": 0.3,
                "contradictions": [],
                "missing_evidence": [],
            },
        )
        assert any(i["category"] == "evidence" and i["severity"] == "critical" for i in r["issues"])

    def test_mid_coverage_warning(self):
        r = run_gate(
            CLEAN,
            evidence_chain={
                "coverage": 0.5,
                "contradictions": [],
                "missing_evidence": [],
            },
        )
        sev = [i["severity"] for i in r["issues"] if i["category"] == "evidence"]
        assert "warning" in sev and "critical" not in sev

    def test_unsurfaced_contradiction_warning(self):
        text = "营收增长强劲，全面看多，目标价上调。" * 3 + " 风险提示：仅供参考。"
        r = run_gate(
            text,
            evidence_chain={
                "coverage": 0.9,
                "contradictions": ["买入/卖出信号冲突"],
                "missing_evidence": [],
            },
        )
        assert any(i["category"] == "contradiction" for i in r["issues"])

    def test_surfaced_contradiction_ok(self):
        # 正文已呈现"分歧" → 不再报矛盾未呈现
        r = run_gate(
            CLEAN,
            evidence_chain={
                "coverage": 0.9,
                "contradictions": ["x"],
                "missing_evidence": [],
            },
        )
        assert not any(i["category"] == "contradiction" for i in r["issues"])

    def test_missing_disclaimer_warning(self):
        text = "营收 +18%，DCF ¥1850，安全边际 +14%，估值处同业中位。" * 2
        r = run_gate(text)
        assert any(i["category"] == "compliance" for i in r["issues"])

    def test_empty_report_critical(self):
        r = run_gate("太短")
        assert any(i["category"] == "structure" and i["severity"] == "critical" for i in r["issues"])
        assert r["passed"] is False

    def test_critic_low_score_warning(self):
        r = run_gate(CLEAN, evidence_chain=GOOD_EC, critic={"quality_score": 30})
        assert any("审稿" in i["issue"] for i in r["issues"])


class TestRunGate:
    def test_clean_report_passes(self):
        r = run_gate(CLEAN, evidence_chain=GOOD_EC)
        assert r["passed"] is True
        assert r["critical_count"] == 0

    def test_gate_or_raise_blocks(self):
        bad = "公司前景广阔。" * 6 + " 风险提示：仅供参考。"
        with pytest.raises(ReportBlockedError):
            gate_or_raise(bad)

    def test_gate_or_raise_passes_clean(self):
        out = gate_or_raise(CLEAN, evidence_chain=GOOD_EC)
        assert out["passed"] is True


class TestIntegration:
    def test_generate_report_with_gate(self):
        from backend.ai_assistant.report_generator import generate_report_with_gate

        conversation = {
            "title": "茅台分析",
            "stock_symbol": "600519",
            "stock_name": "贵州茅台",
            "mode": "deep",
        }
        messages = [
            {"role": "user", "content": "帮我分析贵州茅台", "timestamp": "2026-06-18"},
            {
                "role": "assistant",
                "content": "营收同比 +18%，DCF ¥1850，安全边际 +14%。",
                "timestamp": "2026-06-18",
                "metadata": {},
            },
        ]
        out = generate_report_with_gate(conversation, messages)
        assert "report" in out and "gate" in out
        assert isinstance(out["gate"]["passed"], bool)
        assert "checks_run" in out["gate"]
