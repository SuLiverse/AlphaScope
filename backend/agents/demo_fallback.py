"""Demo-mode research report fallback (zero-key safety net).

When no LLM provider is configured (first launch / Demo mode), the orchestrator
cannot call any model. Instead of surfacing that as an "all agents failed"
error, this module produces a **clearly-labelled demo report skeleton** built
from the real price snapshot passed in ``stock_data``.

Honesty contract (consistent with the project's "不用静态样本伪装后端结果" rule):
- The report never fabricates Agent conclusions, signals, or confidence scores.
- It presents the verifiable price facts (close / change / MA / volume) that
  come from the seed DB or a real source, plus a fixed research framework.
- A prominent banner states this is a demo skeleton and that a model API key is
  required for real multi-Agent analysis.
- Every result carries ``demo_sample=True`` so the frontend can label it.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


def has_configured_provider() -> bool:
    """Return True if at least one enabled model provider is configured.

    Used by the orchestrator to decide whether to run real agents or fall back
    to the demo skeleton. Falls back to env-var keys for the dev path.
    """
    try:
        from backend.settings_store import list_providers

        providers = list_providers()
        if any(p.get("enabled", True) and p.get("api_key_masked") not in ("", None, "—") for p in providers):
            return True
    except Exception as exc:  # noqa: BLE001 - settings optional in some envs
        logger.debug("provider list unavailable: %s", exc)
    # Dev fallback: any of the well-known env keys set non-empty.
    import os

    for env_key in (
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
    ):
        value = os.environ.get(env_key, "").strip()
        if value and not value.startswith("sk-xxx") and value != "your_api_key":
            return True
    return False


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _fmt_price(value: Any) -> str:
    n = _safe_float(value)
    return f"¥{n:,.2f}" if n else "N/A"


def _fmt_pct(value: Any) -> str:
    n = _safe_float(value)
    return f"{n:+.2f}%" if n else "0.00%"


def _trend_view(stock_data: Dict[str, Any]) -> str:
    """Pure rule-based trend comment derived from the price snapshot."""
    close = _safe_float(stock_data.get("close"))
    ma5 = _safe_float(stock_data.get("ma5"))
    ma20 = _safe_float(stock_data.get("ma20"))
    ma60 = _safe_float(stock_data.get("ma60"))
    day_change = _safe_float(stock_data.get("day_change"))
    period_change = _safe_float(stock_data.get("period_change"))
    if not close:
        return "行情数据不足，暂不做趋势判断。"
    if ma5 and ma20 and close >= ma5 >= ma20 and period_change > 0:
        return "短中期均线保持偏强排列，趋势以强势震荡或上行为主。"
    if ma20 and ma60 and close < ma20 < ma60:
        return "价格位于中期均线下方，趋势偏弱，需等待重新站上关键均线。"
    if abs(day_change) >= 5:
        return "单日波动较大，短线情绪占比较高，追价前需确认成交与次日承接。"
    return "均线结构未形成单边确认，当前更适合按区间震荡和风险收益比处理。"


def build_demo_report(stock_data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a clearly-labelled demo research report response.

    Returns the same top-level shape as
    :func:`backend.runtime.orchestrator.run_agents_with_mode` so the API and
    frontend need no special-casing, but with ``agents={}`` (no fabricated
    conclusions) and a prominent demo banner in the report body.
    """
    name = stock_data.get("name") or "未知标的"
    symbol = stock_data.get("symbol") or ""
    close = stock_data.get("close")
    day_change = stock_data.get("day_change")
    period_change = stock_data.get("period_change")
    high = stock_data.get("period_high")
    low = stock_data.get("period_low")
    days = int(stock_data.get("days") or 0)
    ma5 = stock_data.get("ma5", "N/A")
    ma20 = stock_data.get("ma20", "N/A")
    ma60 = stock_data.get("ma60", "N/A")
    volume = _safe_float(stock_data.get("volume"))
    amount = _safe_float(stock_data.get("total_amount"))

    report_body = f"""【演示样本 · DEMO】以下为基于真实行情快照的研究框架，未调用大模型。

> ⚠️ 这是演示样本：行情数据来自内置种子库 / 真实数据源，但多智能体分析、Critic 复核与主席会签均未运行。
> 要获得真实的 AI 投研报告，请在「系统设置 → 模型 Provider」中配置至少一个模型 API Key 后重新生成。

一、标的概览（真实行情）
- 标的: {name} ({symbol})
- 最新价: {_fmt_price(close)}，当日涨跌 {_fmt_pct(day_change)}。
- 近 {days or 30} 日区间涨跌 {_fmt_pct(period_change)}，区间高低点 {_fmt_price(high)} / {_fmt_price(low)}。
- 均线: MA5 {ma5}，MA20 {ma20}，MA60 {ma60}。
- 成交: 当日成交量 {volume:,.0f} 手，区间成交额 {amount:.2f} 亿元。
- 趋势解读（纯规则）: {_trend_view(stock_data)}

二、研究框架（待 AI 填充）
本报告仅展示研究流程骨架。配置 Key 后，下列席位会给出真实结论：
- 基本面研究员：财务质量、估值、行业景气
- 技术面研究员：量价结构、指标信号、关键价位
- 情绪面研究员：新闻、公告、舆情影响
- 风控官：仓位、回撤、集中度、一票否决
- 主席：综合会签、置信度、分歧呈现

三、风控与免责
- 本演示样本不构成任何投资建议，不预测涨跌，不承诺收益。
- 行情数据可能存在延迟，请以真实数据源与个人风险承受能力独立核验。
- 配置 Key 后生成的正式报告会附带证据链、Critic 反证与模型链路状态。
"""

    model_status = {
        "status": "demo",
        "degraded": True,
        "failure_type": "no_provider",
        "message": (
            "当前未配置任何模型 Provider，已生成标注为「演示样本」的研究框架。"
            "请在系统设置中配置模型 API Key 后重新生成，以获得真实的多智能体投研报告。"
        ),
        "ok_agents": 0,
        "total_agents": 0,
        "failed_agents": [],
        "action": "打开「系统设置 → 模型 Provider」，添加一个 OpenAI 兼容 Provider 并填入 API Key。",
    }

    summary = {
        "final": "演示样本（未运行 AI）",
        "buy": 0,
        "sell": 0,
        "hold": 0,
        "avg_confidence": 0,
    }
    from backend.quality.research_trust import assess_agent_research
    from backend.runtime.research_snapshot import build_research_snapshot

    research_trust = assess_agent_research({}, [])
    research_snapshot = build_research_snapshot({**stock_data, "factor_data_policy": "not_enabled"}, [])

    return {
        "agents": {},
        "summary": summary,
        "brief": f"【演示样本】{name} ({symbol}) 行情快照已就绪，AI 分析待配置 Key 后运行。",
        "research_report": report_body,
        "agent_order": [],
        "critic": None,
        "chairman_summary": None,
        "evidence_pool": [],
        "research_trust": research_trust,
        "research_snapshot": research_snapshot,
        "risk_gate": None,
        "model_status": model_status,
        "demo_sample": True,
    }
