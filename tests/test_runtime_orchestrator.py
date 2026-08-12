from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.agent_modes import AnalysisMode
from backend.integrations.schemas import HealthStatus, NormalizedAgentOpinion
from backend.runtime import orchestrator


@pytest.fixture(autouse=True)
def _force_configured_provider():
    """Exercise the real multi-agent path (LLM is mocked per-test).

    Pin ``has_configured_provider()`` True so these tests never divert to the
    zero-key demo-fallback report in environments without a saved provider or
    API key (e.g. CI). Without this they pass only when ambient keys happen to
    be present.
    """
    with patch("backend.agents.demo_fallback.has_configured_provider", return_value=True):
        yield


def test_managed_agent_to_runtime_config_uses_management_fields():
    config = orchestrator._managed_agent_to_runtime_config(
        {
            "id": "risk",
            "name": "风险专家",
            "description": "自定义角色",
            "system_prompt": "自定义风险提示",
            "provider": "claude",
            "model": "claude-sonnet-4-5",
            "enabled": False,
        }
    )

    assert config["key"] == "risk"
    assert config["name"] == "风险专家"
    assert config["role"] == "自定义角色"
    assert config["instruction"] == "自定义风险提示"
    assert config["provider"] == "claude"
    assert config["model"] == "claude-sonnet-4-5"
    assert config["enabled"] is False


def test_run_agents_with_mode_excludes_disabled_managed_agents():
    managed_agents = [
        {
            "id": "fundamental",
            "name": "基本面分析师",
            "description": "分析财报和估值",
            "system_prompt": "分析基本面",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        },
        {
            "id": "technical",
            "name": "技术面分析师",
            "description": "分析K线和指标",
            "system_prompt": "分析技术面",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": False,
        },
    ]

    def fake_run_custom_agent(config, *_args, **_kwargs):
        return {
            "key": config["key"],
            "signal": "观望",
            "confidence": 60,
            "reason": "测试结果",
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=managed_agents),
        patch(
            "backend.runtime.context_builder.build_market_brief",
            return_value="测试简报",
        ),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.agents.financial_agents.run_custom_agent",
            side_effect=fake_run_custom_agent,
        ) as run_custom_agent,
    ):
        result = orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.STANDARD,
        )

    assert result["agent_order"] == ["fundamental"]
    assert list(result["agents"].keys()) == ["fundamental"]
    assert "technical" not in result["agents"]
    assert run_custom_agent.call_count == 1


def test_run_agents_with_mode_single_agent_crash_doesnt_kill_batch():
    """单 Agent 执行抛错(配置/编程 bug)不应让整批崩, 失败 agent 记错误项, 其余正常。"""
    managed_agents = [
        {
            "id": "fundamental",
            "name": "基本面",
            "description": "",
            "system_prompt": "",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        },
        {
            "id": "technical",
            "name": "技术面",
            "description": "",
            "system_prompt": "",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        },
    ]

    def fake_run_custom_agent(config, *_args, **_kwargs):
        # fundamental 模拟配置 bug 抛错, technical 正常返回
        if config["key"] == "fundamental":
            raise RuntimeError("模拟配置 bug: asdict/resolve 失败")
        return {
            "key": config["key"],
            "signal": "买入",
            "confidence": 70,
            "reason": "正常",
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=managed_agents),
        patch(
            "backend.runtime.context_builder.build_market_brief",
            return_value="测试简报",
        ),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.agents.financial_agents.run_custom_agent",
            side_effect=fake_run_custom_agent,
        ),
    ):
        result = orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.STANDARD,
        )

    # 整批不崩: 两个 agent 都在结果里
    assert "fundamental" in result["agents"]
    assert "technical" in result["agents"]
    # 失败的 fundamental 记错误项(不崩), technical 正常
    assert result["agents"]["fundamental"]["ok"] is False
    assert result["agents"]["technical"]["ok"] is True
    assert result["agents"]["technical"]["signal"] == "买入"


def test_auto_escalation_excludes_disabled_managed_agents():
    managed_agents = [
        {
            "id": "fundamental",
            "name": "基本面分析师",
            "description": "分析财报和估值",
            "system_prompt": "分析基本面",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        },
        {
            "id": "technical",
            "name": "技术面分析师",
            "description": "分析K线和指标",
            "system_prompt": "分析技术面",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": False,
        },
    ]

    def fake_run_custom_agent(config, *_args, **_kwargs):
        return {
            "key": config["key"],
            "signal": "观望",
            "confidence": 60,
            "reason": "升级分析结果",
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=managed_agents),
        patch(
            "backend.runtime.context_builder.build_market_brief",
            return_value="测试简报",
        ),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.runtime.orchestrator._call_with",
            return_value='{"signal":"观望","confidence":50,"reason":"需要升级"}',
        ),
        patch(
            "backend.agents.financial_agents.run_custom_agent",
            side_effect=fake_run_custom_agent,
        ) as run_custom_agent,
    ):
        result = orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.AUTO,
        )

    assert result["mode"] == "auto"
    assert result["auto_escalated"] is True
    assert result["agent_order"] == ["fundamental"]
    assert "technical" not in result["agents"]
    assert run_custom_agent.call_count == 1


def test_run_agents_with_mode_falls_back_to_default_agents_without_managed_configs():
    calls: list[str] = []

    def fake_run_custom_agent(config, *_args, **_kwargs):
        calls.append(config["key"])
        return {
            "key": config["key"],
            "signal": "观望",
            "confidence": 50,
            "reason": "默认配置测试",
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=[]),
        patch(
            "backend.runtime.context_builder.build_market_brief",
            return_value="测试简报",
        ),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.agents.financial_agents.run_custom_agent",
            side_effect=fake_run_custom_agent,
        ),
    ):
        result = orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.STANDARD,
        )

    assert result["agent_order"]
    assert result["agent_order"] == calls


def test_runtime_routes_critic_and_chairman_models(monkeypatch):
    routed: dict[str, tuple[str, str]] = {}
    monkeypatch.delenv("ALPHASCOPE_EXTERNAL_AGENT", raising=False)

    def fake_agent(config, *_args, **_kwargs):
        return {
            "key": config["key"],
            "name": config["name"],
            "signal": "买入",
            "confidence": 70,
            "reason": "有证据支持的测试观点",
            "evidence": [],
            "risks": [],
            "ok": True,
        }

    def fake_critic(*_args, **kwargs):
        routed["critic"] = (kwargs["vendor"], kwargs["model"])
        return {
            "agents": {},
            "divergence": {"level": "无", "main_axis": "", "summary": ""},
            "ok": True,
        }

    def fake_chairman(*_args, **kwargs):
        routed["chairman"] = (kwargs["vendor"], kwargs["model"])
        return "主席测试总结"

    settings = {
        "routes": {
            "critic": {"providerId": "deepseek", "modelId": "deepseek-reasoner"},
            "chairman": {"providerId": "claude", "modelId": "claude-opus-routed"},
        }
    }
    agent_configs = [
        {
            "key": "fundamental",
            "name": "基本面",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        }
    ]

    with (
        patch("backend.runtime.context_builder.build_market_brief", return_value="测试简报"),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=[]),
        patch("backend.runtime.context_builder.format_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch("backend.agents.financial_agents.run_custom_agent", side_effect=fake_agent),
        patch("backend.critic.run_batch_critic", side_effect=fake_critic),
        patch("backend.runtime.orchestrator.summarize_with_chairman", side_effect=fake_chairman),
    ):
        orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.DEEP,
            agent_configs=agent_configs,
            global_ai_settings=settings,
        )

    assert routed == {
        "critic": ("deepseek", "deepseek-reasoner"),
        "chairman": ("claude", "claude-opus-routed"),
    }


def test_tradingagents_opinion_joins_council_before_decisions(monkeypatch):
    observed: dict[str, object] = {}

    class FakeAdapter:
        def healthcheck(self):
            return SimpleNamespace(status=HealthStatus.HEALTHY, message="ready")

        def analyze_with_status(self, *, symbols, trade_date):
            observed["symbols"] = symbols
            observed["trade_date"] = trade_date
            return (
                [
                    NormalizedAgentOpinion(
                        agent_name="tradingagents",
                        role="external_team",
                        signal="卖出",
                        thesis="外部团队认为下行风险占优",
                        confidence=90,
                    )
                ],
                {"status": "success", "message": "done", "trade_date": trade_date},
            )

    class FakeRegistry:
        def has(self, name):
            return name == "tradingagents"

        def get(self, _name):
            return FakeAdapter()

    def fake_agent(config, *_args, **_kwargs):
        return {
            "key": config["key"],
            "name": config["name"],
            "signal": "买入",
            "confidence": 70,
            "reason": "内部团队认为基本面稳健",
            "evidence": [],
            "risks": [],
            "ok": True,
        }

    def fake_critic(*_args, **kwargs):
        observed["critic_keys"] = set(kwargs["agent_results"])
        return {
            "agents": {},
            "divergence": {"level": "无", "main_axis": "", "summary": ""},
            "ok": True,
        }

    def fake_chairman(results, *_args, **_kwargs):
        observed["chairman_keys"] = set(results["agents"])
        return "主席已纳入外部意见"

    monkeypatch.setenv("ALPHASCOPE_EXTERNAL_AGENT", "tradingagents")
    agent_configs = [
        {
            "key": "fundamental",
            "name": "基本面",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        }
    ]

    with (
        patch("backend.integrations.registry.get_registry", return_value=FakeRegistry()),
        patch("backend.runtime.context_builder.build_market_brief", return_value="测试简报"),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=[]),
        patch("backend.runtime.context_builder.format_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch("backend.agents.financial_agents.run_custom_agent", side_effect=fake_agent),
        patch("backend.critic.run_batch_critic", side_effect=fake_critic),
        patch("backend.runtime.orchestrator.summarize_with_chairman", side_effect=fake_chairman),
    ):
        result = orchestrator.run_agents_with_mode(
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "price_data_date": "2026-07-14",
            },
            mode=AnalysisMode.DEEP,
            agent_configs=agent_configs,
        )

    assert observed["symbols"] == ["600519"]
    assert observed["trade_date"] == "2026-07-14"
    assert "external_tradingagents" in observed["critic_keys"]
    assert "external_tradingagents" in observed["chairman_keys"]
    assert result["agents"]["external_tradingagents"]["signal"] == "卖出"
    assert result["summary"]["buy"] == 1
    assert result["summary"]["sell"] == 1
    assert result["summary"]["rating_breakdown"]["n_agents"] == 2
    assert result["debate"]["n_bear"] >= 1
    assert result["external_agent"]["status"] == "success"
    assert result["agent_order"][-1] == "external_tradingagents"


def test_explicit_tradingagents_bypasses_zero_key_demo_and_exposes_failure(monkeypatch):
    monkeypatch.setenv("ALPHASCOPE_EXTERNAL_AGENT", "tradingagents")
    external_status = {
        "name": "tradingagents",
        "status": "unavailable",
        "error": "tradingagents 未安装",
    }

    with (
        patch("backend.agents.demo_fallback.has_configured_provider", return_value=False),
        patch("backend.runtime.context_builder.build_market_brief", return_value="测试简报"),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=[]),
        patch("backend.runtime.context_builder.format_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.runtime.orchestrator._run_external_agent",
            return_value=({}, external_status),
        ) as run_external,
    ):
        result = orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.STANDARD,
            agent_configs=[{"key": "disabled", "enabled": False}],
        )

    run_external.assert_called_once()
    assert result["mode_name"] != "Demo"
    assert result["external_agent"] == external_status


def test_citation_confidence_cap_updates_summary_and_report(monkeypatch):
    class CitationCap:
        suggest_confidence_cap = 55.0

        def to_dict(self):
            return {"suggest_confidence_cap": self.suggest_confidence_cap}

    def fake_agent(config, *_args, **_kwargs):
        return {
            "key": config["key"],
            "name": config["name"],
            "signal": "买入",
            "confidence": 80,
            "reason": "测试观点",
            "evidence": [],
            "risks": [],
            "ok": True,
        }

    monkeypatch.delenv("ALPHASCOPE_EXTERNAL_AGENT", raising=False)
    with (
        patch("backend.runtime.context_builder.build_market_brief", return_value="测试简报"),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=[]),
        patch("backend.runtime.context_builder.format_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch("backend.agents.financial_agents.run_custom_agent", side_effect=fake_agent),
        patch("backend.quality.citation_validator.validate_citations", return_value=CitationCap()),
        patch("backend.quality.citation_validator.format_citation_section", return_value=""),
    ):
        result = orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.STANDARD,
            agent_configs=[
                {
                    "key": "fundamental",
                    "name": "基本面",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "enabled": True,
                }
            ],
        )

    assert result["summary"]["avg_confidence"] == 55.0
    assert result["summary"]["confidence_capped_by_citation"] is True
    assert "- 平均置信度: 55.0%" in result["research_report"]
    assert "- 平均置信度: 80.0%" not in result["research_report"]


def test_auto_mode_prescreen_failure_degrades_without_escalation():
    """预筛 LLM 调用抛异常时, Auto 模式就地降级返回, 不再升级 DEEP。"""
    real_run_agents_with_mode = orchestrator.run_agents_with_mode

    def spy_run_agents_with_mode(*args, **kwargs):
        return real_run_agents_with_mode(*args, **kwargs)

    with (
        patch(
            "backend.runtime.context_builder.build_market_brief",
            return_value="测试简报",
        ),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.runtime.orchestrator._call_with",
            side_effect=RuntimeError("模拟 Provider 挂掉"),
        ),
        patch(
            "backend.runtime.orchestrator.run_agents_with_mode",
            side_effect=spy_run_agents_with_mode,
        ) as run_agents_with_mode,
    ):
        result = orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.AUTO,
        )

    assert result["auto_escalated"] is False
    assert "降级" in result["mode_name"]
    assert result["agent_order"] == ["pre_screen"]
    deep_calls = [c for c in run_agents_with_mode.call_args_list if c.kwargs.get("mode") == AnalysisMode.DEEP]
    assert deep_calls == []
    assert "预筛失败" in result["pre_screen_result"]["reason"]


def test_auto_mode_confidence_50_still_escalates_to_deep():
    """预筛正常返回模糊置信度(50)时仍然升级 DEEP, 防止误短路正常升级路径。"""
    managed_agents = [
        {
            "id": "fundamental",
            "name": "基本面分析师",
            "description": "分析财报和估值",
            "system_prompt": "分析基本面",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        }
    ]

    def fake_run_custom_agent(config, *_args, **_kwargs):
        return {
            "key": config["key"],
            "signal": "观望",
            "confidence": 60,
            "reason": "升级分析结果",
            "ok": True,
        }

    real_run_agents_with_mode = orchestrator.run_agents_with_mode

    def spy_run_agents_with_mode(*args, **kwargs):
        return real_run_agents_with_mode(*args, **kwargs)

    with (
        patch("backend.agent_store.list_agents", return_value=managed_agents),
        patch(
            "backend.runtime.context_builder.build_market_brief",
            return_value="测试简报",
        ),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.runtime.orchestrator._call_with",
            return_value='{"signal":"观望","confidence":50,"reason":"模糊结论"}',
        ),
        patch(
            "backend.runtime.orchestrator.run_agents_with_mode",
            side_effect=spy_run_agents_with_mode,
        ) as run_agents_with_mode,
        patch(
            "backend.agents.financial_agents.run_custom_agent",
            side_effect=fake_run_custom_agent,
        ),
    ):
        result = orchestrator.run_agents_with_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            mode=AnalysisMode.AUTO,
        )

    assert result["auto_escalated"] is True
    assert "升级" in result["mode_name"]
    assert any(c.kwargs.get("mode") == AnalysisMode.DEEP for c in run_agents_with_mode.call_args_list)
