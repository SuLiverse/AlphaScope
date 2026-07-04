"""风控引擎测试: 决策期一票否决 gate(v1.9.x)。

验证:
- 各规则(黑名单/仓位/集中度/置信度)纯函数行为
- engine.gate() 汇总: critical → vetoed=True
- 配置缺失时降级到安全默认, 不抛异常
- orchestrator 集成: ST 标的研报被否决, 顶部带红字 banner, summary 不给买入方向
- 合规红线: 风控只做提示, 永不输出买卖指令
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent_modes import AnalysisMode
from backend.quant.risk import (
    CRITICAL,
    INFO,
    WARN,
    check_blacklist,
    check_confidence_floor,
    check_position,
)
from backend.quant.risk.engine import RiskEngine
from backend.runtime import orchestrator


@pytest.fixture(autouse=True)
def _force_configured_provider():
    """Pin has_configured_provider() True so the orchestrator integration tests
    run the real agent path (LLM mocked per-test) instead of the zero-key demo
    fallback in key-less environments such as CI."""
    with patch("backend.agents.demo_fallback.has_configured_provider", return_value=True):
        yield


# ---------- 单规则 ----------


def test_blacklist_st_vetoes():
    f = check_blacklist(
        {"name": "*ST 康美", "symbol": "600 sh"},
        {"enabled": True, "name_patterns": ["ST", "*ST"]},
    )
    assert f is not None and f.severity == CRITICAL

    f = check_blacklist(
        {"name": "贵州茅台", "symbol": "600519"},
        {"enabled": True, "name_patterns": ["ST"]},
    )
    assert f is None

    # disabled → 不检查
    assert check_blacklist({"name": "ST 股"}, {"enabled": False, "name_patterns": ["ST"]}) is None


def test_position_warns_when_over_limit():
    f = check_position({}, {"suggested_position_pct": 45}, {"enabled": True, "limit": 30})
    assert f is not None and f.severity == WARN
    assert check_position({}, {"suggested_position_pct": 20}, {"enabled": True, "limit": 30}) is None
    # 研报无建议仓位时跳过
    assert check_position({}, {}, {"enabled": True, "limit": 30}) is None


def test_confidence_floor_warns_and_vetoes():
    veto = check_confidence_floor(
        {"avg_confidence": 0.10},
        {"enabled": True, "warn_below_pct": 35, "veto_below_pct": 15},
    )
    assert veto is not None and veto.severity == CRITICAL
    warn = check_confidence_floor(
        {"avg_confidence": 25},
        {"enabled": True, "warn_below_pct": 35, "veto_below_pct": 15},
    )
    assert warn is not None and warn.severity == WARN
    ok = check_confidence_floor(
        {"avg_confidence": 60},
        {"enabled": True, "warn_below_pct": 35, "veto_below_pct": 15},
    )
    assert ok is None
    # avg_confidence 以 0-100 给也正确
    veto2 = check_confidence_floor(
        {"avg_confidence": 10},
        {"enabled": True, "warn_below_pct": 35, "veto_below_pct": 15},
    )
    assert veto2 is not None and veto2.severity == CRITICAL


# ---------- engine.gate 汇总 ----------


def test_gate_st_stock_is_vetoed():
    eng = RiskEngine(
        config={
            "blacklist": {"enabled": True, "name_patterns": ["ST"]},
            "max_position_pct": {"enabled": True, "limit": 30},
            "concentration": {
                "enabled": True,
                "max_total_exposure_pct": 80,
                "max_single_sector_pct": 50,
            },
            "confidence_floor": {
                "enabled": True,
                "warn_below_pct": 35,
                "veto_below_pct": 15,
            },
        }
    )
    dec = eng.gate({"name": "ST 康美", "symbol": "600"}, {"avg_confidence": 60})
    assert dec.vetoed is True
    assert dec.max_severity == CRITICAL
    assert any("黑名单" in r for r in dec.veto_reasons)


def test_gate_clean_stock_passes():
    eng = RiskEngine()
    dec = eng.gate({"name": "贵州茅台", "symbol": "600519"}, {"avg_confidence": 70})
    assert dec.vetoed is False
    assert dec.max_severity == INFO


def test_gate_low_confidence_alone_vetoes():
    eng = RiskEngine(
        config={
            "blacklist": {"enabled": True, "name_patterns": ["ST"]},
            "max_position_pct": {"enabled": False, "limit": 30},
            "concentration": {"enabled": False},
            "confidence_floor": {
                "enabled": True,
                "warn_below_pct": 35,
                "veto_below_pct": 15,
            },
        }
    )
    dec = eng.gate({"name": "某股", "symbol": "000"}, {"avg_confidence": 8})
    assert dec.vetoed is True
    assert dec.to_dict()["max_severity"] == CRITICAL


def test_engine_falls_back_to_safe_defaults_when_config_missing(tmp_path):
    eng = RiskEngine(config_path=str(tmp_path / "nonexistent.yaml"))
    # 降级到安全默认: ST 仍会被否决
    dec = eng.gate({"name": "*ST 退市", "symbol": "x"}, {"avg_confidence": 50})
    assert dec.vetoed is True


# ---------- orchestrator 集成 ----------


def test_orchestrator_st_stock_report_is_vetoed_with_banner():
    managed = [
        {
            "id": "fundamental",
            "name": "基本面",
            "system_prompt": "",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        }
    ]

    def fake_agent(config, *_a, **_k):
        return {
            "key": config["key"],
            "signal": "买入",
            "confidence": 70,
            "reason": "ok",
            "evidence": [],
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=managed),
        patch("backend.runtime.context_builder.build_market_brief", return_value="brief"),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=[]),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.critic.run_batch_critic",
            return_value={"agents": {}, "divergence": {"level": "无"}, "ok": False},
        ),
        patch("backend.agents.chairman.summarize_with_chairman", return_value="总结"),
        patch("backend.agents.financial_agents.run_custom_agent", side_effect=fake_agent),
    ):
        result = orchestrator.run_agents_with_mode({"symbol": "600", "name": "*ST 康美"}, mode=AnalysisMode.DEEP)

    gate = result["risk_gate"]
    assert gate is not None and gate["vetoed"] is True
    # 研报顶部带一票否决 banner
    assert "风控一票否决" in result["research_report"]
    # 合规红线: summary 不给出买入方向
    assert "买入" not in result["summary"]["final"]
    # 永不输出买卖指令: gate findings 里没有 buy/sell 动作
    assert all(
        "买入" not in f["message"] and "卖出" not in f["message"] for f in gate["findings"] if f["severity"] == CRITICAL
    )


def test_orchestrator_clean_stock_not_vetoed():
    managed = [
        {
            "id": "fundamental",
            "name": "基本面",
            "system_prompt": "",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        }
    ]

    def fake_agent(config, *_a, **_k):
        return {
            "key": config["key"],
            "signal": "买入",
            "confidence": 70,
            "reason": "ok",
            "evidence": [],
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=managed),
        patch("backend.runtime.context_builder.build_market_brief", return_value="brief"),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=[]),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.critic.run_batch_critic",
            return_value={"agents": {}, "divergence": {"level": "无"}, "ok": False},
        ),
        patch("backend.agents.chairman.summarize_with_chairman", return_value="总结"),
        patch("backend.agents.financial_agents.run_custom_agent", side_effect=fake_agent),
    ):
        result = orchestrator.run_agents_with_mode({"symbol": "600519", "name": "贵州茅台"}, mode=AnalysisMode.DEEP)

    assert result["risk_gate"] is not None
    assert result["risk_gate"]["vetoed"] is False
    assert "风控一票否决" not in result["research_report"]
