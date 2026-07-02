"""
Runtime Orchestrator: 模式感知的 Agent 编排。

职责：
- run_agents_with_mode() - 根据 AnalysisMode 运行 Agent 分析
- _run_auto_mode() - Auto 模式：预筛 + 条件升级
- _mode_config_to_agent_dicts() - AgentModeConfig → agent dict 列表
- get_mode_model_table() - UI 显示用的模型表

从 llm_agents.py 拆分而来。
"""

import logging
import re
from dataclasses import asdict
from typing import Dict, Any, Optional, List

from backend.models.provider_gateway import VENDORS, _call_with, _extract_json
from backend.agents.base import (
    AGENT_PROMPTS,
    _agent_config_from_dict,
)
from backend.agents.chairman import summarize_with_chairman
from backend.runtime.rating import compute_rating

try:
    from backend.agent_modes import AnalysisMode, AgentModeConfig, get_mode_resolver
except ImportError:
    from agent_modes import AnalysisMode, AgentModeConfig, get_mode_resolver

logger = logging.getLogger(__name__)

CARD_STYLE_MAP = {
    "fundamental": "value",
    "technical": "technical",
    "sentiment": "growth",
    "risk": "risk",
    "retail": "macro",
}


def _resolve_evidence_ids(agent_text: Any, number_to_id: Dict[int, str]) -> List[str]:
    """从 Agent 结论文本里解析 [n] 引用, 映射回真实 evidence_id (v1.9.x)

    Agent 简报里以 [1] [2] ... 标注可用证据;Agent 在 reason/evidence 里会回引这些编号。
    本函数把文本里的编号解析成 evidence_pool 中的稳定 ID,实现"结论可反查证据"。
    未命中编号(模型幻觉引用)会被静默忽略,只保留真实存在的证据。
    """
    import re as _re

    text = " ".join(
        str(x)
        for x in (agent_text if isinstance(agent_text, (list, tuple)) else [agent_text])
        if x is not None
    )
    ids: List[str] = []
    seen = set()
    for match in _re.finditer(r"\[(\d{1,3})\]", text):
        num = int(match.group(1))
        eid = number_to_id.get(num)
        if eid and eid not in seen:
            seen.add(eid)
            ids.append(eid)
    return ids


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _format_price(value: Any) -> str:
    number = _safe_float(value)
    return f"¥{number:.2f}" if number else "N/A"


def _format_pct(value: Any) -> str:
    number = _safe_float(value)
    return f"{number:+.2f}%"


def _sanitize_model_error(message: Any) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    try:
        from backend.security.log_sanitizer import sanitize_log_message

        text = sanitize_log_message(text)
    except Exception:
        pass
    text = re.sub(
        r"(api\s*key\s*[:：]?\s*)[^,\s'\"}]+",
        r"\1[REDACTED]",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[REDACTED]", text)
    text = re.sub(r"\s+", " ", text)
    return text[:220]


def _is_auth_error(text: str) -> bool:
    return bool(
        re.search(
            r"401|unauthori[sz]ed|authentication|authenticat|api\s*key|invalid\s*key|鉴权|认证|密钥",
            text or "",
            re.IGNORECASE,
        )
    )


def _clean_agent_reason(reason: Any) -> str:
    text = str(reason or "").strip()
    if not text:
        return ""
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"^json\s*", "", text, flags=re.IGNORECASE).strip()
    if text.startswith("{"):
        try:
            import json

            parsed = json.loads(text)
            if isinstance(parsed, dict) and parsed.get("reason"):
                text = str(parsed.get("reason") or "")
        except Exception:
            match = re.search(r'"reason"\s*:\s*"([^"]+)', text, re.DOTALL)
            if match:
                text = match.group(1)
            else:
                text = re.sub(r"[{}\"]", "", text)
    text = re.sub(r"\\n", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text or text in {"{", "}"}:
        return "模型返回内容未能稳定结构化，建议在修复模型配置后复核。"
    return text[:2000]


def _build_model_status(
    results: Dict[str, Any],
    critic_block: Optional[dict] = None,
    chairman_summary: Optional[str] = None,
) -> dict[str, Any]:
    total = len(results)
    ok_agents = [r for r in results.values() if r.get("ok")]
    failed_agents = [
        {
            "key": r.get("key", ""),
            "name": r.get("name", r.get("key", "Agent")),
            "reason": _sanitize_model_error(r.get("reason", "")),
        }
        for r in results.values()
        if not r.get("ok")
    ]
    failure_text = " ".join(item["reason"] for item in failed_agents)
    if critic_block and not critic_block.get("ok", True):
        failure_text += " " + _sanitize_model_error(critic_block.get("error", ""))
    if chairman_summary and "失败" in chairman_summary:
        failure_text += " " + _sanitize_model_error(chairman_summary)

    auth_error = _is_auth_error(failure_text)
    degraded = bool(failed_agents) or bool(
        critic_block and not critic_block.get("ok", True)
    )
    if chairman_summary and "失败" in chairman_summary:
        degraded = True

    if total and not ok_agents:
        message = "本次专家模型全部未能完成推理，页面展示的是系统基于真实行情快照生成的结构化投研底稿。"
    elif failed_agents:
        message = f"本次 {len(failed_agents)} 个专家席位未完成模型推理，已保留成功席位并降级生成报告。"
    else:
        message = "模型推理完成。"
    if auth_error:
        message += " 检测到疑似 API Key / Provider 鉴权问题，请到系统设置检查 Base URL、API Key 和模型名。"

    return {
        "status": "degraded" if degraded else "ok",
        "degraded": degraded,
        "failure_type": "auth" if auth_error else ("model" if degraded else ""),
        "message": message,
        "ok_agents": len(ok_agents),
        "total_agents": total,
        "failed_agents": failed_agents[:6],
        "action": "打开系统设置，重新检测 Provider 连通性和模型列表后再生成研报。"
        if auth_error
        else "建议检查模型路由、额度、网络或稍后重试。",
    }


def _trend_view(stock_data: Dict[str, Any]) -> str:
    close = _safe_float(stock_data.get("close"))
    ma5 = _safe_float(stock_data.get("ma5"))
    ma20 = _safe_float(stock_data.get("ma20"))
    ma60 = _safe_float(stock_data.get("ma60"))
    day_change = _safe_float(stock_data.get("day_change"))
    period_change = _safe_float(stock_data.get("period_change"))

    if not close:
        return "行情数据不足，暂不做趋势判断。"
    if ma5 and ma20 and close >= ma5 >= ma20 and period_change > 0:
        return "短中期均线保持偏强排列，趋势仍以强势震荡或上行为主。"
    if ma20 and ma60 and close < ma20 < ma60:
        return "价格位于中期均线下方，趋势偏弱，需要等待重新站上关键均线。"
    if abs(day_change) >= 5:
        return "单日波动较大，短线情绪占比较高，追价前需要确认成交与次日承接。"
    return "均线结构未形成单边确认，当前更适合按区间震荡和风险收益比处理。"


def _build_research_report_body(
    stock_data: Dict[str, Any],
    results: Dict[str, Any],
    summary: Dict[str, Any],
    model_status: Dict[str, Any],
    critic_block: Optional[dict] = None,
    chairman_summary: Optional[str] = None,
) -> str:
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
    final = summary.get("final", "建议观望")
    avg_conf = _safe_float(summary.get("avg_confidence"))
    if avg_conf <= 1:
        avg_conf *= 100

    ok_agents = [r for r in results.values() if r.get("ok")]
    failed_count = len(results) - len(ok_agents)
    agent_lines = []
    for r in results.values():
        state = "完成" if r.get("ok") else "未完成"
        reason = _clean_agent_reason(r.get("reason"))
        if not r.get("ok"):
            reason = "模型调用未完成，需检查 Provider 后重新生成。"
        agent_lines.append(
            f"- {r.get('name', r.get('key', 'Agent'))}: {state}; 信号 {r.get('signal', '观望')}; "
            f"置信度 {_safe_float(r.get('confidence')):.0f}%。{reason[:2000]}"
        )
    if not agent_lines:
        agent_lines.append("- 暂无启用专家席位。")

    risk_lines = [
        "- 价格和均线只能说明交易状态，不能替代财务、订单、利润率和估值约束。",
        "- 若后续成交量无法配合当前涨跌幅，短线信号可能快速失效。",
    ]
    for r in ok_agents:
        for risk in r.get("risks") or []:
            risk_text = str(risk).strip()
            if risk_text and len(risk_lines) < 5:
                risk_lines.append(f"- {risk_text}")
    if model_status.get("degraded"):
        risk_lines.append(
            "- 本次模型推理链路降级，所有方向性结论都应在修复 API 配置后复核。"
        )

    critic_text = ""
    if critic_block and critic_block.get("ok"):
        div = critic_block.get("divergence") or {}
        critic_text = str(div.get("summary") or div.get("main_axis") or "").strip()
    elif critic_block and critic_block.get("error"):
        critic_text = "风控复核模型未完成，暂以系统规则提示为主。"
    else:
        critic_text = "未返回独立风控复核，当前风险部分来自行情和专家席位摘要。"

    chairman_note = ""
    if chairman_summary and "失败" not in chairman_summary:
        chairman_note = f"\n\n【投委会主席补充】\n{chairman_summary.strip()}"

    return f"""【完整研报正文】

一、核心结论
- 标的: {name} ({symbol})
- 综合评级: {final}
- 平均置信度: {avg_conf:.1f}%
- 生成状态: {model_status.get("message", "模型推理完成。")}
- 操作含义: 当前报告先给出研究框架和风险收益约束；若模型链路降级，不建议把它视为最终投资结论。

二、行情与趋势判断
- 最新价: {_format_price(close)}，当日涨跌 {_format_pct(day_change)}。
- 近 {days or 30} 日区间涨跌 {_format_pct(period_change)}，区间高低点 {_format_price(high)} / {_format_price(low)}。
- 均线: MA5 {ma5}，MA20 {ma20}，MA60 {ma60}。
- 成交: 当日成交量 {volume:,.0f} 手，区间成交额 {amount:.2f} 亿元。
- 趋势解读: {_trend_view(stock_data)}

三、多智能体会签摘要
- 专家席位: {len(ok_agents)} / {len(results)} 完成，{failed_count} 个席位降级。
{chr(10).join(agent_lines)}

四、风控与反证
{chr(10).join(risk_lines)}
- 风控复核: {critic_text}

五、后续跟踪清单
- 重新检测 Provider 连通性后，补跑专家推理、主席摘要和 Critic 反证。
- 补充财务质量、行业景气、公告事件、研报评级和资金流向证据，避免只依赖 K 线结论。
- 重点观察价格是否继续站稳 MA20、成交是否放大、以及负面新闻或公告是否改变原有假设。{chairman_note}
"""


def _managed_agent_to_runtime_config(raw: dict) -> dict:
    key = str(raw.get("id") or raw.get("key") or "custom_agent").strip()
    prompt = AGENT_PROMPTS.get(key, {})
    role = (
        raw.get("description") or prompt.get("role") or "你是一位专业投资分析 Agent。"
    )
    instruction = (
        raw.get("system_prompt")
        or prompt.get("instruction")
        or "请基于市场简报输出投资信号、置信度和理由。"
    )
    name = raw.get("name") or prompt.get("name") or key
    return {
        "key": key,
        "name": name,
        "avatar": str(name)[:2].strip() or "🤖",
        "role": role,
        "instruction": instruction,
        "provider": raw.get("provider", "deepseek"),
        "model": raw.get("model", "deepseek-chat"),
        "enabled": bool(raw.get("enabled", True)),
        "inherit_global_key": True,
        "card_style": CARD_STYLE_MAP.get(key, "default"),
    }


def _load_managed_agent_configs() -> List[dict]:
    try:
        from backend.agent_store import list_agents

        agents = list_agents()
    except Exception as exc:
        logger.warning("Failed to load managed agent configs: %s", exc)
        return []
    return [_managed_agent_to_runtime_config(agent) for agent in agents]


def run_agents_with_mode(
    stock_data: Dict[str, Any],
    mode: AnalysisMode = AnalysisMode.DEEP,
    agent_configs: Optional[List[dict]] = None,
    global_ai_settings: Optional[dict] = None,
    api_keys: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Run agent analysis with mode-based configuration.

    Args:
        stock_data: Stock data dict with price, technical, fundamental info
        mode: AnalysisMode.STANDARD, .DEEP, or .AUTO
        agent_configs: Optional custom agent configs (overrides mode defaults)
        global_ai_settings: Optional global AI settings from dashboard
        api_keys: Optional per-agent API keys

    Returns:
        Same shape as run_custom_agents() with additional mode metadata
    """
    # 数据完整性预检(v1.9.4): 在任何 LLM 调用前做确定性核验, 缺失维度打标后
    # 注入简报, 杜绝下游 Agent 对缺失数据「脑补」。失败不阻断主流程。
    from backend.agents.data_verifier import verify_data

    verification = verify_data(stock_data)

    # Zero-key safety net: if no model provider is configured (first launch /
    # Demo mode), return a clearly-labelled demo skeleton instead of attempting
    # LLM calls that will all fail. Honest: never fabricates Agent conclusions.
    try:
        from backend.agents.demo_fallback import (
            has_configured_provider,
            build_demo_report,
        )

        if not has_configured_provider():
            logger.info("[orchestrator] no provider configured -> demo fallback report")
            demo = build_demo_report(stock_data)
            demo["mode"] = mode.value
            demo["mode_name"] = "Demo"
            demo["data_verification"] = verification.to_dict()
            return demo
    except Exception as exc:  # noqa: BLE001 - fallback module is optional
        logger.debug("demo fallback check skipped: %s", exc)

    resolver = get_mode_resolver()
    config = resolver.resolve(mode)

    if agent_configs is None:
        agent_configs = _load_managed_agent_configs()

    if mode == AnalysisMode.AUTO:
        return _run_auto_mode(
            stock_data,
            config,
            global_ai_settings,
            api_keys,
            agent_configs=agent_configs,
        )

    # STANDARD or DEEP mode
    if not agent_configs:
        agent_configs = _mode_config_to_agent_dicts(config)

    from backend.runtime.context_builder import (
        build_market_brief,
        fetch_evidence_context,
        fetch_evidence_pool,
        fetch_factor_context,
    )

    symbol = stock_data.get("symbol", "")
    stock_name = stock_data.get("name", "")

    evidence_ctx = ""
    factor_ctx = ""
    evidence_pool: List[dict] = []
    if config.enable_evidence:
        evidence_pool = fetch_evidence_pool(symbol, stock_name)
        evidence_ctx = fetch_evidence_context(symbol, stock_name)
    if config.enable_factors:
        factor_ctx = fetch_factor_context(symbol, stock_name)

    # 简报里的证据编号 [n] → 真实 evidence_id 映射, 供 Agent 结论反链溯源。
    number_to_id = {item["number"]: item["evidence_id"] for item in evidence_pool}

    brief = build_market_brief(
        stock_data, evidence_context=evidence_ctx, factor_context=factor_ctx
    )
    # 证据池就绪后重算核验(纳入 evidence 维度), 并把「严禁编造缺失维度」提示注入简报。
    verification = verify_data(stock_data, evidence_pool=evidence_pool)
    brief += verification.brief_warning()
    api_keys = api_keys or {}

    active = [
        _agent_config_from_dict(a)
        for a in agent_configs
        if bool(a.get("enabled", True))
    ]
    if not active:
        model_status = _build_model_status({})
        summary = {
            "final": "建议观望",
            "buy": 0,
            "sell": 0,
            "hold": 0,
            "avg_confidence": 0,
        }
        return {
            "agents": {},
            "summary": summary,
            "brief": brief,
            "research_report": _build_research_report_body(
                stock_data,
                {},
                summary,
                model_status,
            ),
            "agent_order": [],
            "critic": None,
            "chairman_summary": None,
            "evidence_pool": evidence_pool,
            "risk_gate": None,
            "debate": None,
            "model_status": model_status,
            "data_verification": verification.to_dict(),
            "mode": mode.value,
            "mode_name": config.name,
        }

    from backend.agents.financial_agents import run_custom_agent

    results = {}
    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=len(active)) as ex:
        futures = {
            ex.submit(
                run_custom_agent,
                asdict(cfg),
                brief,
                api_keys.get(cfg.key),
                global_ai_settings,
            ): cfg.key
            for cfg in active
        }
        for fut in as_completed(futures):
            # 单个 Agent 的配置 bug(asdict/resolve 抛错, 非 LLM 失败)不应让整批崩 —
            # 失败的 future 记成错误项, 已成功的 Agent 结果保留。
            try:
                r = fut.result()
                results[r["key"]] = r
            except Exception as exc:  # noqa: BLE001
                key = futures[fut]
                logger.exception("Agent %s 执行异常(整批不中断)", key)
                results[key] = {
                    "key": key,
                    "name": key,
                    "ok": False,
                    "error": f"Agent 执行异常: {exc}",
                    "view": "",
                    "confidence": 0,
                    "signal": "观望",
                }

    # 把每个 Agent 结论里的 [n] 证据引用解析成真实 evidence_id,
    # 实现"点开结论可反查来源"的可审计能力(evidence 招牌落地)。
    if number_to_id:
        for r in results.values():
            r["evidence_ids"] = _resolve_evidence_ids(
                [r.get("reason", ""), r.get("evidence", [])], number_to_id
            )
    else:
        for r in results.values():
            r.setdefault("evidence_ids", [])

    buy = sum(1 for r in results.values() if r["signal"] == "买入")
    sell = sum(1 for r in results.values() if r["signal"] == "卖出")
    hold = sum(1 for r in results.values() if r["signal"] == "观望")
    avg_conf = sum(r["confidence"] for r in results.values()) / max(len(results), 1)

    threshold = max(1, len(results) // 2 + 1)
    if buy > sell and buy >= threshold:
        final = "建议买入"
    elif sell > buy and sell >= threshold:
        final = "建议卖出"
    else:
        final = "建议观望"

    # Critic review (only in DEEP mode)
    critic_block = None
    if config.enable_critic and any(r.get("ok") for r in results.values()):
        try:
            from backend.critic import run_batch_critic

            critic_settings = (global_ai_settings or {}).get("critic") or {}
            critic_block = run_batch_critic(
                stock_name=stock_data.get("name", "未知标的"),
                market_brief=brief,
                agent_results={k: r for k, r in results.items() if r.get("ok")},
                vendor=critic_settings.get("provider") or config.critic_provider,
                model=critic_settings.get("model") or config.critic_model,
            )
            for ag_key, review in (critic_block.get("agents") or {}).items():
                if ag_key in results:
                    results[ag_key]["review"] = review
        except Exception as e:
            critic_block = {
                "agents": {},
                "divergence": {"level": "无", "main_axis": "", "summary": ""},
                "ok": False,
                "error": str(e)[:200],
            }

    # Chairman synthesis (only in DEEP mode)
    chairman_summary = None
    if config.enable_chairman:
        try:
            chairman_summary = summarize_with_chairman(
                {
                    "agents": results,
                    "summary": {"buy": buy, "sell": sell, "hold": hold},
                },
                stock_data.get("name", ""),
                vendor=((global_ai_settings or {}).get("chairman") or {}).get(
                    "provider"
                ),
                model=((global_ai_settings or {}).get("chairman") or {}).get("model"),
            )
        except Exception as e:
            chairman_summary = f"主席总结生成失败: {_sanitize_model_error(e)}"

    rating = compute_rating(list(results.values()), risk_vetoed=False)
    summary = {
        "final": final,
        "buy": buy,
        "sell": sell,
        "hold": hold,
        "avg_confidence": avg_conf,
        "score": rating["score"],
        "rating": rating["rating"],
        "rating_breakdown": rating["breakdown"],
    }
    model_status = _build_model_status(results, critic_block, chairman_summary)
    research_report = _build_research_report_body(
        stock_data,
        results,
        summary,
        model_status,
        critic_block,
        chairman_summary,
    )

    # 研报发布前风控 gate(v1.9.x): 评估黑名单/集中度/置信度等, critical 触发一票否决。
    # 合规红线: 风控只做提示与约束, 绝不输出买卖指令; 否决时研报保留(可追溯)但
    # 顶部红字写明理由, 且 summary 不给出买入方向。
    risk_gate = None
    try:
        from backend.quant.risk.engine import RiskEngine

        risk_gate = RiskEngine().gate(stock_data, summary).to_dict()
        if risk_gate.get("vetoed"):
            banner = (
                "⛔【风控一票否决】本研报因触发 critical 风控规则被否决, 方向性结论不作为投资依据:\n"
                + "\n".join(f"  - {r}" for r in risk_gate.get("veto_reasons", []))
            )
            research_report = f"{banner}\n\n{research_report}"
            vetoed_rating = compute_rating(list(results.values()), risk_vetoed=True)
            summary = {
                **summary,
                "final": "风控否决(结论不作为投资依据)",
                "score": vetoed_rating["score"],
                "rating": vetoed_rating["rating"],
                "rating_breakdown": vetoed_rating["breakdown"],
            }
    except Exception as exc:  # noqa: BLE001 - 风控 gate 失败不应阻断研报
        logger.debug("风控 gate 评估失败, 跳过: %s", exc)

    # 多空辩论裁决(v1.9.14): 确定性合成「看多/看空(反方质询)/裁决」, 复用已算出的
    # Agent 信号 + Critic 分歧 + 风控否决 + 数据缺失, 不新增任何 LLM 调用; 失败安全。
    debate = None
    try:
        from backend.agents.debate import format_debate_section, synthesize_debate

        debate_report = synthesize_debate(
            results,
            summary=summary,
            critic=critic_block,
            risk_gate=risk_gate,
            data_verification=verification.to_dict(),
        )
        debate = debate_report.to_dict()
        section = format_debate_section(debate_report)
        if section:
            research_report = f"{research_report}\n{section}"
    except Exception as exc:  # noqa: BLE001 - 辩论合成失败不应阻断研报
        logger.debug("多空辩论合成失败, 跳过: %s", exc)

    return {
        "agents": results,
        "summary": summary,
        "brief": brief,
        "agent_order": [cfg.key for cfg in active],
        "critic": critic_block,
        "chairman_summary": chairman_summary,
        "research_report": research_report,
        "model_status": model_status,
        "evidence_pool": evidence_pool,
        "risk_gate": risk_gate,
        "debate": debate,
        "data_verification": verification.to_dict(),
        "mode": mode.value,
        "mode_name": config.name,
    }


def _run_auto_mode(
    stock_data: Dict[str, Any],
    config: AgentModeConfig,
    global_ai_settings: Optional[dict] = None,
    api_keys: Optional[Dict[str, str]] = None,
    agent_configs: Optional[List[dict]] = None,
) -> Dict[str, Any]:
    """
    Auto mode: quick pre-screen with cheap model, escalate if ambiguous.

    Stage 1: Single agent with cheap model (DeepSeek)
    Stage 2: If confidence is between 30-70, escalate to full DEEP analysis
    """
    from backend.runtime.context_builder import build_market_brief
    from backend.agents.data_verifier import verify_data

    brief = build_market_brief(stock_data)
    verification = verify_data(stock_data)
    brief += verification.brief_warning()

    # Stage 1: Pre-screen
    pre_screen_messages = [
        {
            "role": "system",
            "content": "你是一位快速股票分析师。基于简报给出买入/卖出/观望信号和置信度。",
        },
        {
            "role": "user",
            "content": (
                f"{brief}\n\n"
                '请用 JSON 返回: {"signal": "买入|卖出|观望", "confidence": 0-100, "reason": "300字以上分析，包含：核心逻辑、关键数据、主要风险、操作建议"}'
            ),
        },
    ]

    try:
        text = _call_with(
            config.pre_screen_provider,
            config.pre_screen_model,
            pre_screen_messages,
            json_mode=True,
            max_tokens=config.pre_screen_max_tokens,
            temperature=config.pre_screen_temperature,
        )
        pre_result = _extract_json(text)
        pre_signal = pre_result.get("signal", "观望")
        pre_confidence = int(pre_result.get("confidence", 50))
        pre_reason = pre_result.get("reason", "")
    except Exception as e:
        pre_signal = "观望"
        pre_confidence = 50
        pre_reason = f"预筛失败: {e}"

    # Check if escalation is needed
    if pre_confidence < config.escalate_below or pre_confidence > config.escalate_above:
        return {
            "agents": {
                "pre_screen": {
                    "key": "pre_screen",
                    "name": "🔍 快速预筛",
                    "signal": pre_signal,
                    "confidence": pre_confidence,
                    "reason": pre_reason,
                    "evidence": [],
                    "invalid_if": "",
                    "risks": [],
                    "vendor": config.pre_screen_provider,
                    "model": config.pre_screen_model,
                    "ok": True,
                    "evidence_ids": [],
                }
            },
            "summary": {
                "final": f"建议{'买入' if pre_signal == '买入' else '卖出' if pre_signal == '卖出' else '观望'}",
                "buy": 1 if pre_signal == "买入" else 0,
                "sell": 1 if pre_signal == "卖出" else 0,
                "hold": 1 if pre_signal == "观望" else 0,
                "avg_confidence": pre_confidence,
            },
            "brief": brief,
            "agent_order": ["pre_screen"],
            "critic": None,
            "chairman_summary": None,
            "evidence_pool": [],
            "risk_gate": None,
            "data_verification": verification.to_dict(),
            "mode": "auto",
            "mode_name": "自动模式 (预筛直接输出)",
            "auto_escalated": False,
            "pre_screen_result": {
                "signal": pre_signal,
                "confidence": pre_confidence,
                "reason": pre_reason,
            },
        }

    # Escalation needed: run full DEEP analysis
    deep_result = run_agents_with_mode(
        stock_data,
        mode=AnalysisMode.DEEP,
        agent_configs=agent_configs or _mode_config_to_agent_dicts(config),
        global_ai_settings=global_ai_settings,
        api_keys=api_keys,
    )
    deep_result["mode"] = "auto"
    deep_result["mode_name"] = "自动模式 (已升级到深入分析)"
    deep_result["auto_escalated"] = True
    deep_result["pre_screen_result"] = {
        "signal": pre_signal,
        "confidence": pre_confidence,
        "reason": pre_reason,
    }
    return deep_result


def _mode_config_to_agent_dicts(config: AgentModeConfig) -> List[dict]:
    """Convert AgentModeConfig agents to list of dicts compatible with run_custom_agents()"""
    prompt_map = {
        "fundamental": AGENT_PROMPTS.get("fundamental", {}),
        "technical": AGENT_PROMPTS.get("technical", {}),
        "sentiment": AGENT_PROMPTS.get("sentiment", {}),
        "risk": AGENT_PROMPTS.get("risk", {}),
        "retail": AGENT_PROMPTS.get("retail", {}),
    }
    result = []
    for agent_entry in config.enabled_agents:
        prompt = prompt_map.get(agent_entry.key, {})
        result.append(
            {
                "key": agent_entry.key,
                "name": prompt.get("name", agent_entry.key),
                "avatar": str(prompt.get("name", "🤖"))[:2].strip() or "🤖",
                "role": prompt.get("role", ""),
                "instruction": prompt.get("instruction", ""),
                "provider": agent_entry.provider,
                "model": agent_entry.model,
                "enabled": agent_entry.enabled,
                "inherit_global_key": True,
                "card_style": CARD_STYLE_MAP.get(agent_entry.key, "default"),
            }
        )
    return result


def get_mode_model_table(mode: AnalysisMode) -> list:
    """Get agent model table for a specific mode (for UI display)"""
    config = get_mode_resolver().resolve(mode)
    rows = []
    for agent in config.enabled_agents:
        prompt = AGENT_PROMPTS.get(agent.key, {})
        name = prompt.get("name", agent.key)
        vendor_label = VENDORS.get(agent.provider, {}).get("label", agent.provider)
        rows.append((agent.key, name, vendor_label, agent.model))

    if config.enable_critic:
        rows.append(
            (
                "critic",
                "📝 Critic 审稿",
                VENDORS.get(config.critic_provider, {}).get(
                    "label", config.critic_provider
                ),
                config.critic_model,
            )
        )
    if config.enable_chairman:
        rows.append(
            (
                "chairman",
                "🎩 投资委员会主席",
                VENDORS.get(config.chairman_provider, {}).get(
                    "label", config.chairman_provider
                ),
                config.chairman_model,
            )
        )
    return rows
