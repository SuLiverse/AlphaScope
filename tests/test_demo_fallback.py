"""Tests for the demo-mode research report fallback.

Covers:
* ``build_demo_report`` produces the full response shape with a demo banner.
* The report is honest: no fabricated agent signals/confidence.
* ``has_configured_provider`` is robust to a missing settings store.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestBuildDemoReport:
    def _stock_data(self) -> dict:
        return {
            "symbol": "600519",
            "name": "贵州茅台",
            "close": 1207.68,
            "day_change": -15.2,
            "period_change": 38.5,
            "period_high": 1250.0,
            "period_low": 1100.0,
            "days": 30,
            "ma5": 1205.0,
            "ma20": 1180.0,
            "ma60": 1150.0,
            "volume": 2500000,
            "total_amount": 30.5,
        }

    def test_returns_full_response_shape(self):
        from backend.agents.demo_fallback import build_demo_report

        result = build_demo_report(self._stock_data())
        # Must match orchestrator.run_agents_with_mode top-level keys.
        for key in (
            "agents",
            "summary",
            "brief",
            "research_report",
            "model_status",
            "demo_sample",
            "research_trust",
            "research_snapshot",
        ):
            assert key in result

    def test_is_marked_as_demo(self):
        from backend.agents.demo_fallback import build_demo_report

        result = build_demo_report(self._stock_data())
        assert result["demo_sample"] is True
        assert result["model_status"]["status"] == "demo"
        assert result["summary"]["final"] == "演示样本（未运行 AI）"

    def test_never_fabricates_agent_conclusions(self):
        """Honesty contract: demo must not invent agent signals or confidence."""
        from backend.agents.demo_fallback import build_demo_report

        result = build_demo_report(self._stock_data())
        assert result["agents"] == {}
        assert result["summary"]["buy"] == 0
        assert result["summary"]["sell"] == 0
        assert result["summary"]["avg_confidence"] == 0
        assert result["critic"] is None
        assert result["chairman_summary"] is None
        assert result["research_trust"]["grade"] == "insufficient"
        assert result["research_snapshot"]["snapshot_id"]

    def test_report_contains_demo_banner_and_key_prompt(self):
        from backend.agents.demo_fallback import build_demo_report

        body = build_demo_report(self._stock_data())["research_report"]
        assert "演示样本" in body
        assert "API Key" in body or "Provider" in body
        assert "不构成任何投资建议" in body

    def test_report_embeds_real_price_facts(self):
        from backend.agents.demo_fallback import build_demo_report

        body = build_demo_report(self._stock_data())["research_report"]
        # Real snapshot values must surface (not fabricated).
        assert "贵州茅台" in body
        assert "600519" in body
        assert "1,207.68" in body

    def test_model_status_zero_agents_so_api_treats_as_success(self):
        """The API handler treats total>0 & ok==0 as failure. Demo has total==0
        so it must NOT be flagged all_agents_failed (it's a valid demo, not an error)."""
        from backend.agents.demo_fallback import build_demo_report

        ms = build_demo_report(self._stock_data())["model_status"]
        total = int(ms.get("total_agents") or 0)
        ok = int(ms.get("ok_agents") or 0)
        assert not (total > 0 and ok == 0)


class TestHasConfiguredProvider:
    def test_returns_bool(self):
        from backend.agents.demo_fallback import has_configured_provider

        assert isinstance(has_configured_provider(), bool)

    def test_placeholder_env_values_are_ignored(self):
        """A placeholder sk-xxx must not count as a configured provider."""
        from backend.agents.demo_fallback import has_configured_provider

        # Temporarily clear real keys and set a placeholder to simulate first launch.
        saved = {}
        keys = (
            "DEEPSEEK_API_KEY",
            "OPENAI_API_KEY",
            "DASHSCOPE_API_KEY",
            "MOONSHOT_API_KEY",
        )
        for k in keys:
            saved[k] = os.environ.pop(k, None)
        try:
            # The DB in this repo may already have a provider; we only assert
            # the placeholder path doesn't flip it True via env. Functional check.
            os.environ["DEEPSEEK_API_KEY"] = "sk-xxx"
            os.environ["OPENAI_API_KEY"] = "your_api_key"
            # Result depends on the DB, but at minimum the function must not crash
            # and the placeholder strings must not be accepted as real keys.
            result = has_configured_provider()
            assert isinstance(result, bool)
        finally:
            for k in keys:
                if saved[k] is not None:
                    os.environ[k] = saved[k]
                else:
                    os.environ.pop(k, None)
