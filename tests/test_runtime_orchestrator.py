from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent_modes import AnalysisMode
from backend.runtime import orchestrator


@pytest.fixture(autouse=True)
def _force_configured_provider():
    """Exercise the real multi-agent path (LLM is mocked per-test).

    Pin ``has_configured_provider()`` True so these tests never divert to the
    zero-key demo-fallback report in environments without a saved provider or
    API key (e.g. CI). Without this they pass only when ambient keys happen to
    be present.
    """
    with patch(
        "backend.agents.demo_fallback.has_configured_provider", return_value=True
    ):
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
        patch(
            "backend.runtime.context_builder.fetch_evidence_context", return_value=""
        ),
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
        patch(
            "backend.runtime.context_builder.fetch_evidence_context", return_value=""
        ),
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
        patch(
            "backend.runtime.context_builder.fetch_evidence_context", return_value=""
        ),
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
        patch(
            "backend.runtime.context_builder.fetch_evidence_context", return_value=""
        ),
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
