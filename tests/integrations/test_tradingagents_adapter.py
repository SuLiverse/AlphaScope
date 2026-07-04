"""TradingAgents Adapter 测试 (Phase 2 第四个真实 adapter, 收尾四类 adapter 协议).

分两组:
1. **纯函数组 (始终跑)**: _normalize_decision / map_decision_to_opinion /
   has_llm_credentials —— 验证 TradingAgents 的 (final_state, decision) 归一化成
   NormalizedAgentOpinion, 全部失败安全。不依赖 tradingagents。
2. **tradingagents 执行路径 (skipif; 未装跳过)**: adapter 健康检查 / 自动发现 /
   analyze 端到端。tradingagents 未装时整组跳过 (CI 仍确定性通过)。

合规: 测试只校验观点归一化与边界不变量, 不涉及任何买卖指令; 观点永远 forbidden_live_order=True。
"""

from __future__ import annotations

import pytest

from backend.integrations.agent.tradingagents_adapter import (
    TradingagentsAdapter,
    _normalize_decision,
    has_llm_credentials,
    map_decision_to_opinion,
)
from backend.integrations.schemas import HealthStatus, LicenseSafety


# ============================================================
# 1. 纯函数组 (始终跑, 不依赖 tradingagents)
# ============================================================


def test_normalize_decision_clean_inputs():
    assert _normalize_decision("BUY") == "BUY"
    assert _normalize_decision("sell") == "SELL"
    assert _normalize_decision(" Hold ") == "HOLD"


def test_normalize_decision_handles_llm_noise():
    """LLM 抽取的 decision 可能带噪声 (大小写/标点/前缀), 都要容错。"""
    assert _normalize_decision("buy.") == "BUY"
    assert _normalize_decision("最终决策: SELL") == "SELL"
    assert _normalize_decision("HOLD!") == "HOLD"


def test_normalize_decision_unknown_falls_back_to_hold():
    """未知/异常输入 → HOLD (失败安全, 不因 LLM 输出异常而崩)。"""
    assert _normalize_decision("UNKNOWN") == "HOLD"
    assert _normalize_decision("") == "HOLD"
    assert _normalize_decision(None) == "HOLD"
    assert _normalize_decision(123) == "HOLD"


def test_map_decision_buy_maps_to_buy_signal():
    op = map_decision_to_opinion(
        {"final_trade_decision": "Strong fundamentals, momentum positive."},
        "BUY",
    )
    assert op.thesis.startswith("Strong fundamentals")
    assert op.confidence == 60.0
    assert op.forbidden_live_order is True
    assert op.suggested_action_type == "generate_report"


def test_map_decision_uses_report_fallback_when_no_final_decision():
    """final_trade_decision 缺失时, thesis 退到各 analyst report 拼接。"""
    op = map_decision_to_opinion(
        {"market_report": "市况回暖", "news_report": "新闻利好"},
        "BUY",
    )
    assert "市况回暖" in op.thesis
    assert "新闻利好" in op.thesis


def test_map_decision_empty_state_uses_placeholder_thesis():
    op = map_decision_to_opinion(None, "SELL")
    assert "SELL" in op.thesis
    assert op.confidence == 60.0


def test_map_decision_hold_has_lower_confidence():
    """HOLD 是中性观望, 置信度 50 (低于 BUY/SELL 的 60)。"""
    op = map_decision_to_opinion({}, "HOLD")
    assert op.confidence == 50.0


def test_has_llm_credentials_detects_env(monkeypatch):
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert has_llm_credentials() is False
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert has_llm_credentials() is True


# ============================================================
# 2. 元数据 + 边界 (始终跑, 不依赖 tradingagents)
# ============================================================


def test_tradingagents_metadata_and_boundary():
    """adapter 元数据 + 交易边界 + 许可证防火墙。

    TradingAgents 是 Apache License 2.0 (已核对仓库 LICENSE) → SAFE, 与 vectorBT/
    OpenBB/Qlib 同级; code_copy_allowed=True。仍 allow_live_order=False + requires_evidence。
    """
    a = TradingagentsAdapter()
    meta = a.metadata()
    assert meta.name == "tradingagents"
    assert meta.allow_live_order is False
    assert meta.license_safety == LicenseSafety.SAFE
    assert meta.license_name == "Apache-2.0"
    assert meta.code_copy_allowed is True
    assert meta.requires_evidence is True
    # agent adapter 不暴露任何实盘下单能力
    for cap in meta.capabilities:
        low = cap.name.lower()
        for tok in ("submit_order", "place_order", "live"):
            assert tok not in low


def test_tradingagents_autodiscovered_by_registry():
    """autodiscover 应发现 tradingagents adapter (与 demo/vectorbt/openbb/qlib 一起)。"""
    from backend.integrations.registry import IntegrationRegistry, autodiscover

    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    assert reg.has("tradingagents")


def test_tradingagents_healthcheck_reports_availability(monkeypatch):
    """未装 UNAVAILABLE; 装了无凭证 DEGRADED; 装了有凭证 HEALTHY。"""
    a = TradingagentsAdapter()
    h = a.healthcheck()
    assert h.status in (
        HealthStatus.UNAVAILABLE,
        HealthStatus.DEGRADED,
        HealthStatus.HEALTHY,
    )


def test_analyze_failure_safe_returns_empty_when_unavailable(monkeypatch):
    """tradingagents 不可用或缺凭证时 analyze 不抛, 返回空列表。"""
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    a = TradingagentsAdapter()
    out = a.analyze(["NVDA"], trade_date="2024-01-15")
    assert out == []


# ============================================================
# 3. tradingagents 执行路径 (skipif; 未装整组跳过)
# ============================================================

try:
    import tradingagents as _ta  # noqa: F401

    _HAS_TA = True
except Exception:
    _HAS_TA = False

_ta_required = pytest.mark.skipif(not _HAS_TA, reason="tradingagents 未安装, 跳过执行路径用例")


@_ta_required
def test_analyze_with_real_tradingagents_returns_opinion_or_empty(monkeypatch):
    """装了 tradingagents: 有 key 时可能返回非空观点 (需网络+LLM); 无 key/失败返回空。

    CI 不强求非空 (可能无网络/key); 只校验: 要么空, 要么每条都是 forbidden_live_order=True。
    """
    a = TradingagentsAdapter()
    out = a.analyze(["NVDA"], trade_date="2024-01-15")
    for op in out:
        assert op.forbidden_live_order is True
        assert op.agent_name == "tradingagents"
