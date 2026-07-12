"""契约测试: Agent 结论绑定 evidence_id(可溯源招牌)。

验证 v1.9.x 的"结论可反查证据"能力:
- Agent reason/evidence 里的 [n] 引用被解析成真实 evidence_id
- 幻觉引用(编号不存在)被静默丢弃
- 三种模式(STANDARD/DEEP/AUTO)的响应都带 evidence_pool 字段
- 单 Agent 结论无证据引用时 evidence_ids 为空列表(非缺失)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent_modes import AnalysisMode
from backend.runtime import orchestrator


@pytest.fixture(autouse=True)
def _force_configured_provider():
    """Pin has_configured_provider() True so these tests exercise the real
    multi-agent path (LLM mocked per-test) instead of the zero-key demo
    fallback in key-less environments such as CI."""
    with patch("backend.agents.demo_fallback.has_configured_provider", return_value=True):
        yield


def _pool():
    """模拟 RAG 检索返回的结构化证据池(编号 → evidence_id)。"""
    return [
        {
            "number": 1,
            "evidence_id": "ev-news-1",
            "doc_type": "news",
            "source": "财联社",
            "source_url": "https://cls/1",
            "published_at": "",
            "preview": "利好消息",
        },
        {
            "number": 2,
            "evidence_id": "ev-report-2",
            "doc_type": "report",
            "source": "东财研报",
            "source_url": "",
            "published_at": "",
            "preview": "买入评级",
        },
    ]


def test_resolve_evidence_ids_maps_brackets_and_drops_hallucinations():
    m = {1: "ev-news-1", 2: "ev-report-2", 3: "ev-ann-3"}
    ids = orchestrator._resolve_evidence_ids(["参考[1]与[3]", ["指标见[2]"]], m)
    assert set(ids) == {"ev-news-1", "ev-report-2", "ev-ann-3"}
    # 编号 9 不存在 → 静默丢弃, 不报错
    assert orchestrator._resolve_evidence_ids("引用[1]和[9]", m) == ["ev-news-1"]
    # 去重
    assert orchestrator._resolve_evidence_ids("[1][1][1]", m) == ["ev-news-1"]
    # 空池 → 永远空
    assert orchestrator._resolve_evidence_ids("引用[1]", {}) == []


def test_standard_mode_binds_evidence_ids_to_each_agent():
    managed_agents = [
        {
            "id": "fundamental",
            "name": "基本面",
            "system_prompt": "",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        },
    ]

    def fake_agent(config, *_a, **_k):
        # 引用证据 [1](存在) 和 [9](幻觉)
        return {
            "key": config["key"],
            "signal": "买入",
            "confidence": 70,
            "reason": "财务强劲,参考[1];另见[9]",
            "evidence": [],
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=managed_agents),
        patch("backend.runtime.context_builder.build_market_brief", return_value="brief"),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=_pool()) as fetch_pool,
        patch("backend.runtime.context_builder.format_evidence_context", return_value="ctx") as format_context,
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch(
            "backend.critic.run_batch_critic",
            return_value={"agents": {}, "divergence": {"level": "无"}, "ok": False},
        ),
        patch("backend.runtime.orchestrator.summarize_with_chairman", return_value="主席总结"),
        patch("backend.agents.financial_agents.run_custom_agent", side_effect=fake_agent),
    ):
        result = orchestrator.run_agents_with_mode({"symbol": "600519", "name": "贵州茅台"}, mode=AnalysisMode.DEEP)

    agent = result["agents"]["fundamental"]
    assert agent["evidence_ids"] == ["ev-news-1"]  # [9] 被丢弃
    assert result["evidence_pool"] == _pool()
    fetch_pool.assert_called_once()
    format_context.assert_called_once_with(_pool(), as_of="")
    assert result["research_snapshot"]["evidence_count"] == 2


def test_standard_mode_no_evidence_pool_yields_empty_ids():
    managed_agents = [
        {
            "id": "technical",
            "name": "技术面",
            "system_prompt": "",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        },
    ]

    def fake_agent(config, *_a, **_k):
        return {
            "key": config["key"],
            "signal": "观望",
            "confidence": 50,
            "reason": "无明确证据",
            "evidence": [],
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=managed_agents),
        patch("backend.runtime.context_builder.build_market_brief", return_value="brief"),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=[]),
        patch("backend.runtime.context_builder.fetch_evidence_context", return_value=""),
        patch("backend.runtime.context_builder.fetch_factor_context", return_value=""),
        patch("backend.agents.financial_agents.run_custom_agent", side_effect=fake_agent),
    ):
        result = orchestrator.run_agents_with_mode({"symbol": "600519", "name": "贵州茅台"}, mode=AnalysisMode.STANDARD)

    # 无证据池时, evidence_ids 必须是空列表(非缺失键), 且 evidence_pool 为空
    assert result["agents"]["technical"]["evidence_ids"] == []
    assert result["evidence_pool"] == []


def test_auto_mode_direct_prescreen_carries_empty_evidence_contract():
    """AUTO 模式预筛直接输出时也要带 evidence_pool=[] 与 evidence_ids=[]。"""
    with (
        patch("backend.runtime.context_builder.build_market_brief", return_value="brief"),
        patch(
            "backend.runtime.orchestrator._call_with",
            return_value='{"signal":"买入","confidence":90,"reason":"高置信"}',
        ),
    ):
        result = orchestrator._run_auto_mode(
            {"symbol": "600519", "name": "贵州茅台"},
            orchestrator.get_mode_resolver().resolve(AnalysisMode.AUTO),
        )
    assert result["evidence_pool"] == []
    assert result["agents"]["pre_screen"]["evidence_ids"] == []


def test_historical_mode_uses_cutoff_for_trust_and_excludes_live_factors():
    managed_agents = [
        {
            "id": "fundamental",
            "name": "基本面",
            "system_prompt": "",
            "provider": "deepseek",
            "model": "deepseek-chat",
            "enabled": True,
        }
    ]
    pool = [
        {
            "number": 1,
            "evidence_id": "ev-historical",
            "doc_type": "announcement",
            "source": "cninfo",
            "source_url": "",
            "published_at": "2020-06-30",
            "preview": "历史公告",
        }
    ]

    def fake_agent(config, *_args, **_kwargs):
        return {
            "key": config["key"],
            "signal": "观望",
            "confidence": 60,
            "reason": "参考[1]",
            "evidence": [],
            "ok": True,
        }

    with (
        patch("backend.agent_store.list_agents", return_value=managed_agents),
        patch("backend.runtime.context_builder.fetch_evidence_pool", return_value=pool),
        patch("backend.runtime.context_builder.fetch_factor_context") as fetch_factors,
        patch("backend.agents.financial_agents.run_custom_agent", side_effect=fake_agent),
        patch("backend.agents.chairman.summarize_with_chairman", return_value="主席总结"),
        patch("backend.critic.run_batch_critic", return_value={"agents": {}, "ok": True}),
    ):
        result = orchestrator.run_agents_with_mode(
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "as_of": "2020-06-30",
                "price_data_date": "2020-06-30",
            },
            mode=AnalysisMode.DEEP,
        )

    fetch_factors.assert_not_called()
    assert result["research_snapshot"]["factor_data_policy"] == "excluded_unversioned"
    assert result["research_trust"]["metrics"]["freshness"] > 0.99
    assert "未来数据穿越" in result["brief"]
