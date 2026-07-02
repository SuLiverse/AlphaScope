"""
Financial Agents: Agent 执行逻辑。

职责：
- run_one_agent() - 运行单个内置 Agent
- run_all_agents() - 并行运行全部内置 Agent
- run_custom_agent() - 运行单个自定义 Agent
- run_custom_agents() - 并行运行自定义 Agent 列表
- get_custom_agent_model_table() / get_agent_model_table() - UI 辅助

从 llm_agents.py 拆分而来。
"""

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from typing import Dict, Any, Optional, List

from backend.models.provider_gateway import (
    VENDORS,
    _call_with,
    _extract_json,
    get_configured_provider,
)
from backend.agents.base import (
    AGENT_MODEL_CONFIG,
    AGENT_PROMPTS,
    FALLBACK_VENDOR_MODEL,
    _agent_config_from_dict,
    _resolve_agent_ai_config,
    _strict_json_messages,
)

try:
    from backend.validators import validate_agent_output as _validate_agent_output
except Exception:

    def _validate_agent_output(data):
        if not isinstance(data, dict):
            return {}
        return data


logger = logging.getLogger(__name__)


def _sanitize_agent_error(error: Any) -> str:
    text = str(error or "").strip()
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
    if re.search(
        r"401|unauthori[sz]ed|authentication|authenticat|api\s*key|invalid\s*key|鉴权|认证|密钥",
        text,
        re.IGNORECASE,
    ):
        return "模型鉴权失败，请在系统设置中检查 Provider Base URL、API Key 和模型名。"
    return text[:180]


def _fallback_text_to_agent_result(text: str) -> Dict[str, Any]:
    """Turn a non-JSON model reply into a conservative Agent result."""
    clean_text = re.sub(r"\s+", " ", (text or "").strip())
    if not clean_text:
        return {}

    signal = "观望"
    if re.search(r"卖出|减持|看空|下行|风险较高|bear|sell|short", clean_text, re.I):
        signal = "卖出"
    elif re.search(r"买入|增持|看多|上行|机会|bull|buy|long", clean_text, re.I):
        signal = "买入"

    confidence = 50
    confidence_match = re.search(r"(\d{1,3})\s*(?:%|/100|分|置信)", clean_text)
    if confidence_match:
        confidence = max(0, min(100, int(confidence_match.group(1))))
    elif signal != "观望":
        confidence = 55

    return {
        "signal": signal,
        "confidence": confidence,
        "reason": clean_text[:2000],
        "structured_fallback": True,
        "evidence": [
            {
                "type": "other",
                "claim": "模型返回了自然语言分析，系统已进行结构化兜底。",
                "data_date": "",
            }
        ],
        "invalid_if": "模型未返回严格 JSON，建议复核原始回答。",
        "risks": ["结构化解析降级，结论需人工复核"],
    }


def _candidate_models(
    provider: str,
    model: str,
    *,
    api_key: Optional[str] = None,
    base_url: str = "",
) -> list[tuple[str, str, str, Optional[str]]]:
    candidates = [(provider, model, base_url, api_key)]
    fallback_provider, fallback_model = get_configured_provider()
    fallback = (fallback_provider, fallback_model, "", None)
    if (fallback_provider, fallback_model) != (provider, model):
        candidates.append(fallback)
    return candidates


def run_one_agent(
    agent_key: str, market_brief: str, api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    运行单个 Agent,含 fallback 与稳健 JSON 解析。
    支持细粒度 API Key。
    """
    cfg = AGENT_PROMPTS[agent_key]
    vendor, model = AGENT_MODEL_CONFIG.get(agent_key, FALLBACK_VENDOR_MODEL)
    primary_vendor = vendor

    messages = [
        {"role": "system", "content": cfg["role"]},
        {"role": "user", "content": f"{cfg['instruction']}\n\n{market_brief}"},
    ]

    last_err = None
    for vd, md, base_url, key_override in _candidate_models(
        vendor, model, api_key=api_key
    ):
        try:
            mtokens = 3072 if vd == "mimo" else 2048
            text = _call_with(
                vd,
                md,
                messages,
                json_mode=True,
                max_tokens=mtokens,
                temperature=0.3,
                api_key=key_override,
                base_url=base_url,
            )
            data = _extract_json(text)
            if not data or not data.get("signal"):
                retry_tokens = mtokens
                text = _call_with(
                    vd,
                    md,
                    messages
                    + [
                        {"role": "assistant", "content": text},
                        {
                            "role": "user",
                            "content": "请只输出符合格式的 JSON 对象,不要任何前后说明。",
                        },
                    ],
                    json_mode=True,
                    max_tokens=retry_tokens,
                    temperature=0.1,
                    api_key=key_override,
                    base_url=base_url,
                )
                data = _extract_json(text)

            if not data or not data.get("signal"):
                last_err = f"{VENDORS.get(vd, {}).get('label', vd)} 未返回有效 JSON"
                data = _fallback_text_to_agent_result(text)
                if not data:
                    continue

            valid = _validate_agent_output(data or {})
            return {
                "key": agent_key,
                "name": cfg["name"],
                "signal": valid["signal"],
                "confidence": valid["confidence"],
                "reason": valid["reason"],
                "evidence": valid["evidence"],
                "invalid_if": valid["invalid_if"],
                "risks": valid["risks"],
                "vendor": VENDORS.get(vd, {}).get("label", vd),
                "model": md,
                "primary_vendor": VENDORS.get(primary_vendor, {}).get(
                    "label", primary_vendor
                ),
                "fallback_used": vd != primary_vendor,
                "structured_fallback": bool(data.get("structured_fallback")),
                "ok": True,
            }
        except Exception as e:
            last_err = _sanitize_agent_error(e)
            continue

    return {
        "key": agent_key,
        "name": cfg["name"],
        "signal": "观望",
        "confidence": 0,
        "reason": f"分析失败: {last_err}",
        "evidence": [],
        "invalid_if": "",
        "risks": [],
        "vendor": "?",
        "model": "?",
        "primary_vendor": VENDORS[primary_vendor]["label"],
        "fallback_used": True,
        "ok": False,
    }


def run_all_agents(
    stock_data: Dict[str, Any],
    include_retail: bool = True,
    api_keys: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    并行调用全部 Agent（4 核心 + 可选散户行为）。
    api_keys: {agent_key: api_key} 细粒度 API Key 映射。
    """
    from backend.runtime.context_builder import (
        build_market_brief,
        fetch_evidence_context,
        fetch_factor_context,
    )

    symbol = stock_data.get("symbol", "")
    stock_name = stock_data.get("name", "")
    evidence_ctx = fetch_evidence_context(symbol, stock_name)
    factor_ctx = fetch_factor_context(symbol, stock_name)
    brief = build_market_brief(
        stock_data, evidence_context=evidence_ctx, factor_context=factor_ctx
    )
    api_keys = api_keys or {}

    keys = ["fundamental", "technical", "sentiment", "risk"]
    if include_retail:
        keys.append("retail")

    results = {}
    with ThreadPoolExecutor(max_workers=len(keys)) as ex:
        futures = {ex.submit(run_one_agent, k, brief, api_keys.get(k)): k for k in keys}
        for fut in as_completed(futures):
            # 单 Agent 配置/编程 bug 不应让整批崩 — 记错误项(观望), 已成功结果保留。
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

    buy = sum(1 for r in results.values() if r["signal"] == "买入")
    sell = sum(1 for r in results.values() if r["signal"] == "卖出")
    hold = sum(1 for r in results.values() if r["signal"] == "观望")
    avg_conf = sum(r["confidence"] for r in results.values()) / max(len(results), 1)

    threshold = 3 if include_retail else 2
    if buy > sell and buy >= threshold:
        final = "建议买入"
    elif sell > buy and sell >= threshold:
        final = "建议卖出"
    else:
        final = "建议观望"

    return {
        "agents": results,
        "summary": {
            "final": final,
            "buy": buy,
            "sell": sell,
            "hold": hold,
            "avg_confidence": avg_conf,
        },
        "brief": brief,
    }


def run_custom_agent(
    agent_raw: dict,
    market_brief: str,
    api_key: Optional[str] = None,
    global_ai_settings: Optional[dict] = None,
    memory_context: str = "",
) -> Dict[str, Any]:
    """运行单个页面自定义 Agent。"""
    cfg = _agent_config_from_dict(agent_raw)
    resolved_provider, resolved_model, resolved_key, resolved_base_url = (
        _resolve_agent_ai_config(cfg, global_ai_settings)
    )
    if api_key:
        resolved_key = api_key
    messages = [
        {"role": "system", "content": cfg.role},
        {
            "role": "user",
            "content": (
                f"{cfg.instruction}\n\n{market_brief}\n\n"
                f"{memory_context}\n\n"
                "【输出要求】请用 JSON 返回,字段:\n"
                "- signal: 买入|卖出|观望\n"
                "- confidence: 0-100 整数\n"
                "- reason: 400 字以上的详细分析(必须包含核心逻辑、关键数据、主要风险与操作建议的完整逻辑链)\n"
                "- evidence: 数组,每条 {type, claim, data_date},type 取自 fund_flow/technical/fundamental/news/research/macro/sentiment/shareholder/other\n"
                "- invalid_if: 简短的失效条件\n"
                "- risks: 1-3 条主要风险(字符串数组)\n"
            ),
        },
    ]
    primary_vendor = resolved_provider
    last_err = None
    for vd, md, bu, key_override in _candidate_models(
        resolved_provider,
        resolved_model,
        api_key=resolved_key,
        base_url=resolved_base_url,
    ):
        try:
            mtokens = 3072 if vd == "mimo" else 2048
            call_messages = (
                _strict_json_messages(messages) if vd == "mimo" else messages
            )
            text = _call_with(
                vd,
                md,
                call_messages,
                json_mode=True,
                max_tokens=mtokens,
                temperature=0.3,
                api_key=key_override,
                base_url=bu,
            )
            data = _extract_json(text)
            if not data or not data.get("signal"):
                retry_messages = messages + [
                    {"role": "assistant", "content": text or ""},
                    {
                        "role": "user",
                        "content": '请只输出 JSON：{"signal": "买入|卖出|观望", "confidence": 75, "reason": "理由", "evidence": [], "invalid_if": "", "risks": []}',
                    },
                ]
                if vd == "mimo":
                    retry_messages = _strict_json_messages(retry_messages)
                text = _call_with(
                    vd,
                    md,
                    retry_messages,
                    json_mode=True,
                    max_tokens=mtokens,
                    temperature=0.1,
                    api_key=key_override,
                    base_url=bu,
                )
                data = _extract_json(text)
            if not data or not data.get("signal"):
                last_err = f"{vd} 未返回有效 JSON"
                data = _fallback_text_to_agent_result(text)
                if not data:
                    continue
            valid = _validate_agent_output(data)
            return {
                "key": cfg.key,
                "name": cfg.name,
                "signal": valid["signal"],
                "confidence": valid["confidence"],
                "reason": valid["reason"],
                "evidence": valid["evidence"],
                "invalid_if": valid["invalid_if"],
                "risks": valid["risks"],
                "vendor": VENDORS.get(vd, {}).get("label", vd),
                "model": md,
                "primary_vendor": VENDORS.get(primary_vendor, {}).get(
                    "label", primary_vendor
                ),
                "fallback_used": vd != primary_vendor,
                "structured_fallback": bool(data.get("structured_fallback")),
                "ok": True,
                "card_style": cfg.card_style,
            }
        except Exception as e:
            last_err = _sanitize_agent_error(e)
            continue
    return {
        "key": cfg.key,
        "name": cfg.name,
        "signal": "观望",
        "confidence": 0,
        "reason": f"分析失败: {last_err}",
        "evidence": [],
        "invalid_if": "",
        "risks": [],
        "vendor": "?",
        "model": "?",
        "primary_vendor": VENDORS.get(primary_vendor, {}).get("label", primary_vendor),
        "fallback_used": True,
        "ok": False,
        "card_style": cfg.card_style,
    }


def run_custom_agents(
    stock_data: Dict[str, Any],
    agent_configs: List[dict],
    global_ai_settings: Optional[dict] = None,
    api_keys: Optional[Dict[str, str]] = None,
    enable_critic: bool = True,
) -> Dict[str, Any]:
    """并行运行任意数量的页面自定义 Agent;并可选地批量调用 Critic 审稿。"""
    from backend.runtime.context_builder import (
        build_market_brief,
        fetch_evidence_context,
    )

    symbol = str(stock_data.get("symbol") or "")
    stock_name = str(stock_data.get("name") or "")
    preferences = {}
    try:
        from backend.settings_store import get_app_preferences

        preferences = get_app_preferences()
    except Exception:
        preferences = {}
    knowledge_preferences = preferences.get("knowledge", {})
    evidence_context = ""
    knowledge_enabled = knowledge_preferences.get("enabled", True)
    if knowledge_enabled and knowledge_preferences.get("shared_knowledge", True):
        evidence_context = fetch_evidence_context(symbol, stock_name)
    brief = build_market_brief(stock_data, evidence_context=evidence_context)
    memory_context = ""
    if knowledge_enabled and knowledge_preferences.get("agent_memory", True):
        try:
            from backend.agent_memory import build_agent_memory_context

            memory_context = build_agent_memory_context(symbol, stock_name)
        except Exception:
            memory_context = ""
    api_keys = api_keys or {}
    active = [
        _agent_config_from_dict(a)
        for a in agent_configs
        if bool(a.get("enabled", True))
    ]
    if not active:
        return {
            "agents": {},
            "summary": {
                "final": "建议观望",
                "buy": 0,
                "sell": 0,
                "hold": 0,
                "avg_confidence": 0,
            },
            "brief": brief,
            "agent_order": [],
            "critic": None,
        }
    results = {}
    with ThreadPoolExecutor(max_workers=len(active)) as ex:
        futures = {
            ex.submit(
                run_custom_agent,
                asdict(cfg),
                brief,
                api_keys.get(cfg.key),
                global_ai_settings,
                memory_context,
            ): cfg.key
            for cfg in active
        }
        for fut in as_completed(futures):
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

    critic_block = None
    if enable_critic and any(r.get("ok") for r in results.values()):
        try:
            from backend.critic import run_batch_critic

            critic_settings = (global_ai_settings or {}).get("critic") or {}
            inherit = bool(
                critic_settings.get(
                    "inherit_global_key",
                    (global_ai_settings or {}).get("use_unified_key", True),
                )
            )
            if inherit and (global_ai_settings or {}).get("api_key"):
                critic_api_key = (global_ai_settings or {}).get("api_key", "")
                critic_base_url = (global_ai_settings or {}).get("base_url", "")
            else:
                critic_api_key = critic_settings.get("api_key") or ""
                critic_base_url = critic_settings.get("base_url") or ""
            critic_block = run_batch_critic(
                stock_name=stock_data.get("name", "未知标的"),
                market_brief=brief,
                agent_results={k: r for k, r in results.items() if r.get("ok")},
                vendor=critic_settings.get("provider"),
                model=critic_settings.get("model"),
                api_key=critic_api_key or None,
                base_url=critic_base_url or None,
            )
            for ag_key, review in (critic_block.get("agents") or {}).items():
                if ag_key in results:
                    results[ag_key]["review"] = review
        except Exception as e:
            critic_block = {
                "agents": {},
                "divergence": {"level": "无", "main_axis": "", "summary": ""},
                "ok": False,
                "vendor": "",
                "model": "",
                "fallback_used": True,
                "error": str(e)[:200],
            }

    if knowledge_enabled and knowledge_preferences.get("auto_write_agent_memory", True):
        try:
            from backend.agent_memory import save_agent_run_memory

            save_agent_run_memory(stock_data, results)
        except Exception as exc:  # noqa: BLE001 — 记忆写入失败不阻断分析, 但需可见
            logger.warning("自动写入 Agent 记忆失败(不阻断分析): %s", exc)

    chairman_summary = None
    chairman_settings = (global_ai_settings or {}).get("chairman") or {}
    if chairman_settings.get("provider") and chairman_settings.get("model"):
        try:
            from backend.agents.chairman import summarize_with_chairman

            chairman_summary = summarize_with_chairman(
                {
                    "agents": results,
                    "summary": {"buy": buy, "sell": sell, "hold": hold},
                },
                stock_data.get("name", ""),
                vendor=chairman_settings.get("provider"),
                model=chairman_settings.get("model"),
            )
        except Exception as exc:
            chairman_summary = f"主席总结生成失败: {exc}"

    return {
        "agents": results,
        "summary": {
            "final": final,
            "buy": buy,
            "sell": sell,
            "hold": hold,
            "avg_confidence": avg_conf,
        },
        "brief": brief,
        "agent_order": [cfg.key for cfg in active],
        "critic": critic_block,
        "chairman_summary": chairman_summary,
    }


def get_custom_agent_model_table(agent_configs: List[dict]) -> list:
    rows = []
    for raw in agent_configs:
        if not raw.get("enabled", True):
            continue
        cfg = _agent_config_from_dict(raw)
        rows.append(
            (
                cfg.key,
                cfg.name,
                VENDORS.get(cfg.provider, {}).get("label", cfg.provider),
                cfg.model,
            )
        )
    return rows


def get_agent_model_table() -> list:
    """供 UI 显示：返回 [(agent_key, agent_name, vendor_label, model)]"""
    rows = []
    for key, (vendor, model) in AGENT_MODEL_CONFIG.items():
        if key == "chairman":
            name = "🎩 投资委员会主席"
        else:
            name = AGENT_PROMPTS[key]["name"]
        rows.append((key, name, VENDORS[vendor]["label"], model))
    return rows
