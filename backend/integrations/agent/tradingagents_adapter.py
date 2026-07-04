"""TradingAgents Adapter — 外部多 Agent 投研团队 (Phase 2 第四个真实 adapter).

TradingAgents (TauricResearch, 多智能体 LLM 金融投研框架) 把「分析师团队 + 多空辩论 +
风控辩论 + 组合经理裁决」做成一个 LangGraph 工作流, 输出 BUY/SELL/HOLD 决策 + 完整
研究报告。本 adapter 把它接入 AlphaScope 的 Integration Registry, 作为「外部投研团队」
补齐自研 Agent Council 的视角多样性 (对应战略规划「TradingAgentsAdapter」「AgentHub
外部投研团队」, Phase 5)。

设计要点 (延续项目「确定性 · 失败安全 · 可溯源」基线):
- **可选依赖 + 优雅降级**: ``tradingagents`` 用 import-guard 包裹, 没装不影响其余功能
  (healthcheck 报 UNAVAILABLE)。
- **LLM 凭证必需**: 与 vectorbt/openbb/qlib 不同, TradingAgents **无离线模式**,
  .propagate() 必须有 LLM API key 才能跑; healthcheck 在已装但缺凭证时报 DEGRADED。
- **不触网交易**: 输出只是 BUY/SELL/HOLD **研究观点** + 报告文本, 绝不直接变成订单;
  ``allow_live_order=False``, 归一化观点带 ``forbidden_live_order=True``。
- **失败安全**: 不可用 / 缺凭证 / .propagate 抛错 → 返回空观点列表, 不抛破坏性异常。
- **归一化纯函数可单测**: ``map_decision_to_opinion`` 把 TradingAgents 的
  (final_state, decision) 归一化成 AlphaScope ``NormalizedAgentOpinion``, 不依赖
  tradingagents 即可单测。

API 已对照 TradingAgents v0.3.0 真实源码核对 (非臆测):
- 入口: ``from tradingagents.graph.trading_graph import TradingAgentsGraph``
- 运行: ``final_state, decision = ta.propagate(company_name, trade_date, asset_type)``
- 返回: decision ∈ {"BUY","SELL","HOLD"} (LLM 抽取的字符串); final_state 含
  market_report / news_report / fundamentals_report / final_trade_decision 等。

合规: 观点仅为研究辅助, **不据此给买卖指令、不预测、不构成投资建议**;
观点永远经证据 + 风控 + 人工确认, forbidden_live_order=True。
"""

from __future__ import annotations

import os
from typing import Any

# ----- 可选依赖: tradingagents 缺失时优雅降级 -----
try:
    from tradingagents.graph.trading_graph import (  # type: ignore[import-untyped]
        TradingAgentsGraph,
    )

    _TA_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    TradingAgentsGraph = None  # type: ignore[assignment]
    _TA_AVAILABLE = False

from backend.integrations.base import AgentTeamAdapter
from backend.integrations.schemas import (
    HealthStatus,
    IntegrationHealth,
    IntegrationMetadata,
    IntegrationMode,
    LicenseSafety,
    NormalizedAgentOpinion,
)
from backend.integrations.registry import register

# TradingAgents 支持的 asset_type (源码 propagate 第三参数)
_ASSET_TYPES = ("stock", "crypto")

# TradingAgents 的 BUY/SELL/HOLD → AlphaScope 买入/卖出/观望 口径 + 置信度默认值。
# (TradingAgents 不输出置信度数值, 用固定 60 表示「中等」; 真正置信度由 AlphaScope
# 的 rating 层从多 Agent 投票结构重算, 不依赖单一外部团队。)
_DECISION_MAP: dict[str, tuple[str, float]] = {
    "BUY": ("买入", 60.0),
    "SELL": ("卖出", 60.0),
    "HOLD": ("观望", 50.0),
}


# ============================================================
# 纯函数 (无需 tradingagents 即可单测)
# ============================================================


def _normalize_decision(raw: Any) -> str:
    """把 TradingAgents 的 decision (LLM 抽取的字符串) 归一化成 BUY/SELL/HOLD。

    容错: 大小写/空白/未知值 → HOLD (失败安全, 不因 LLM 输出异常而崩)。
    """
    if not isinstance(raw, str):
        return "HOLD"
    s = raw.strip().upper()
    # 处理 "BUY." / "BUY!" / "最终决策: BUY" 这类 LLM 噪声
    for tok in ("BUY", "SELL", "HOLD"):
        if tok in s:
            return tok
    return "HOLD"


def map_decision_to_opinion(
    final_state: dict[str, Any] | None,
    decision: Any,
    agent_name: str = "tradingagents",
) -> NormalizedAgentOpinion:
    """把 TradingAgents 的 (final_state, decision) 归一化成 NormalizedAgentOpinion。

    TradingAgents 不输出置信度数值 → 用 _DECISION_MAP 的默认值; 真正置信度由
    AlphaScope rating 层重算。thesis 取 final_trade_decision (Portfolio Manager 的
    完整文字结论), 失败时退到各 analyst report 拼接。
    """
    norm_decision = _normalize_decision(decision)
    signal, confidence = _DECISION_MAP.get(norm_decision, ("观望", 50.0))

    # thesis: 优先 final_trade_decision; 失败退到报告拼接; 全失败给占位
    thesis = ""
    state = final_state if isinstance(final_state, dict) else {}
    if state:
        thesis = str(state.get("final_trade_decision") or "").strip()
        if not thesis:
            parts = []
            for k in ("market_report", "news_report", "fundamentals_report"):
                v = state.get(k)
                if v:
                    parts.append(str(v))
            thesis = (" | ".join(parts))[:500] if parts else ""
    if not thesis:
        thesis = f"TradingAgents 决策: {norm_decision} (详细结论缺失)"

    return NormalizedAgentOpinion(
        agent_name=agent_name,
        role="external_team",
        thesis=thesis,
        confidence=confidence,
        horizon=None,
        supporting_evidence_ids=[],
        opposing_evidence_ids=[],
        risk_flags=[],
        suggested_action_type="generate_report",
        forbidden_live_order=True,
    )


def has_llm_credentials() -> bool:
    """探测是否配置了至少一个 TradingAgents 可用的 LLM 凭证。

    TradingAgents 通过环境变量读 key (OPENAI_API_KEY / ANTHROPIC_API_KEY /
    GOOGLE_API_KEY / DEEPSEEK_API_KEY 等)。无任何 key 时 .propagate() 会失败,
    所以 healthcheck 在此场景报 DEGRADED。纯函数, 仅看环境变量。
    """
    cred_keys = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GOOGLE_API_KEY",
        "DEEPSEEK_API_KEY",
        "XAI_API_KEY",
        "DASHSCOPE_API_KEY",  # qwen
        "ZHIPUAI_API_KEY",  # glm
    )
    return any(os.getenv(k) for k in cred_keys)


def _build_config(**overrides: Any) -> dict[str, Any]:
    """构造 TradingAgentsGraph 的 config (延迟读 DEFAULT_CONFIG, 避免模块导入副作用)。"""
    try:
        from tradingagents.default_config import (  # type: ignore[import-untyped]
            DEFAULT_CONFIG,
        )

        cfg = dict(DEFAULT_CONFIG)
    except Exception:
        # DEFAULT_CONFIG 读不到时用最小可识别默认 (provider/model 名按需由调用方覆盖)
        cfg = {
            "llm_provider": "openai",
            "deep_think_llm": "gpt-4o",
            "quick_think_llm": "gpt-4o-mini",
            "max_debate_rounds": 2,
        }
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    return cfg


# ============================================================
# Adapter
# ============================================================


@register
class TradingagentsAdapter(AgentTeamAdapter):
    """TradingAgents 外部投研团队 adapter (Phase 2)。

    把 TradingAgents 的多 Agent 团队 (4 分析师 + 多空辩论 + 风控辩论 + 组合经理)
    接入 AlphaScope, 输出归一化研究观点 (BUY/SELL/HOLD → 买入/卖出/观望 + thesis)。
    tradingagents 不可用 / 缺凭证 / 抛错时返回空, 不抛。**绝不产生订单**。
    """

    NAME = "tradingagents"
    # CATEGORY 继承自 AgentTeamAdapter.AGENT

    def _metadata(self) -> IntegrationMetadata:
        return IntegrationMetadata(
            name=self.NAME,
            category=self.CATEGORY,
            mode=IntegrationMode.PYTHON_ADAPTER,
            version="0.1.0",
            display_name="TradingAgents 外部投研团队",
            description=(
                "多智能体 LLM 金融投研框架 (4 分析师 + 多空辩论 + 风控辩论 + 组合经理),"
                "输出 BUY/SELL/HOLD + 研报。作为外部投研团队补齐自研 Agent Council "
                "的视角多样性。可选依赖, 缺失时降级; 无离线模式, 需 LLM API key。"
            ),
            homepage="https://github.com/TauricResearch/TradingAgents",
            package="tradingagents",
            capabilities=[
                {
                    "name": "analyze",
                    "description": "对给定标的跑多 Agent 团队, 返回归一化观点",
                },
            ],
            # TradingAgents 是 Apache License 2.0 (已核对仓库 LICENSE 文件), 属可商用
            # 的宽松开源协议, 与 vectorBT(Apache)/OpenBB(MIT)/Qlib(MIT) 同级 → SAFE。
            license_name="Apache-2.0",
            license_safety=LicenseSafety.SAFE,
            code_copy_allowed=True,
            allow_live_order=False,
            requires_evidence=True,
        )

    def healthcheck(self) -> IntegrationHealth:
        if not _TA_AVAILABLE:
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.UNAVAILABLE,
                message=(
                    "tradingagents 未安装。安装后生效: "
                    "pip install git+https://github.com/TauricResearch/TradingAgents.git"
                ),
            )
        if not has_llm_credentials():
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.DEGRADED,
                message=(
                    "tradingagents 已安装但未检测到 LLM 凭证 (OPENAI_API_KEY 等)。"
                    "TradingAgents 无离线模式, .propagate() 需 LLM key 才能跑。"
                ),
            )
        return IntegrationHealth(
            name=self.NAME,
            status=HealthStatus.HEALTHY,
            message="tradingagents 就绪 (多 Agent 投研团队, 已配置 LLM 凭证)",
        )

    def analyze(self, symbols: list[str], **kw: Any) -> list[NormalizedAgentOpinion]:
        """对给定标的跑 TradingAgents 多 Agent 团队, 返回归一化观点列表。

        关键入参 (kw):
        - trade_date: str      交易日期 "YYYY-MM-DD" (TradingAgents 用历史数据回放)
        - asset_type: str      "stock"(默认) / "crypto"
        - company_name: str    TradingAgents 第一参数 (缺省取 symbols[0])
        - llm_provider / deep_think_llm / quick_think_llm: 覆盖默认 LLM 配置

        返回 [NormalizedAgentOpinion] (单标的单观点; 多标的时逐个跑, 失败安全)。
        失败安全: 不可用 / 缺凭证 / .propagate 抛错 → 返回空列表, 不抛。
        合规: 观点 forbidden_live_order=True, 绝不直接变成订单。
        """
        if not _TA_AVAILABLE or not has_llm_credentials():
            return []

        trade_date = str(kw.get("trade_date", ""))
        asset_type = str(kw.get("asset_type", "stock"))
        if asset_type not in _ASSET_TYPES:
            asset_type = "stock"
        cfg = _build_config(
            llm_provider=kw.get("llm_provider"),
            deep_think_llm=kw.get("deep_think_llm"),
            quick_think_llm=kw.get("quick_think_llm"),
            max_debate_rounds=kw.get("max_debate_rounds"),
        )

        out: list[NormalizedAgentOpinion] = []
        for sym in symbols:
            company = str(kw.get("company_name") or sym)
            try:
                graph = TradingAgentsGraph(debug=False, config=cfg)  # type: ignore[misc]
                final_state, decision = graph.propagate(company, trade_date, asset_type=asset_type)
                out.append(map_decision_to_opinion(final_state, decision))
            except Exception:
                # 单标的失败不影响其余 (失败安全); 不抛, 不记订单, 不污染证据
                continue
        return out
