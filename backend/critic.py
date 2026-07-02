"""
Critic / 审稿 Agent 服务(v0.9)。

设计目标:
- 单次 LLM 调用对多个 Agent 输出进行批量审稿,避免 N 次调用的成本。
- 输入:市场简报 + N 个 agent 结果(含 evidence/signal/confidence)。
- 输出:每个 agent 的 quality_score / supported / contradictions / missing_evidence /
  overconfident / comment,以及一个 divergence 块(level / main_axis / summary)。
- 失败时返回空结果,不阻塞主流程,UI 只是不显示审稿区块。

模块对外只暴露:
- :func:`run_batch_critic` 主入口,提供 fail-soft 行为
- :func:`build_critic_prompt` / :func:`parse_critic_response` 纯函数,便于测试

依赖:
- llm_agents.call_llm 与 _extract_json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import llm_agents as _llm_agents  # noqa: E402

call_llm = getattr(_llm_agents, "call_llm", _llm_agents._call_with)
_extract_json = _llm_agents._extract_json
VENDORS = _llm_agents.VENDORS

PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "critic.md"

# 默认审稿模型:用与主席相同的高端模型,因为我们关心的是判断质量而非速度。
DEFAULT_CRITIC_MODEL = ("claude", "claude-opus-4-7")

VALID_DIVERGENCE_LEVELS = ("高", "中", "低", "无")


# ============== 系统 prompt ==============
def load_critic_system_prompt() -> str:
    """从 prompts/critic.md 加载审稿人设;文件缺失时返回内置兜底。"""
    if PROMPT_FILE.exists():
        try:
            text = PROMPT_FILE.read_text(encoding="utf-8").strip()
            if text:
                return text
        except Exception:
            pass
    return (
        "你是投研审稿人,负责给同事的股票分析输出打 0-100 的 quality_score,"
        "列出 supported / contradictions / missing_evidence / comment,以及全局 divergence。"
        "只返回 JSON,不要 Markdown。"
    )


# ============== 输入序列化 ==============
def _serialize_evidence(evidence: Any) -> List[str]:
    """把 agent 的 evidence 字段(可能是 list[dict] 或 list[str])收敛成可读字符串列表。"""
    if not evidence:
        return []
    out: List[str] = []
    items = evidence if isinstance(evidence, list) else [evidence]
    for ev in items:
        if isinstance(ev, dict):
            claim = (ev.get("claim") or "").strip()
            if not claim:
                continue
            etype = ev.get("type") or ""
            date = ev.get("data_date") or ""
            tail = []
            if etype and etype != "other":
                tail.append(f"[{etype}]")
            if date:
                tail.append(f"({date})")
            out.append(claim + (" " + " ".join(tail) if tail else ""))
        else:
            text = str(ev).strip()
            if text:
                out.append(text)
    return out


def build_critic_prompt(
    stock_name: str,
    market_brief: str,
    agent_results: Dict[str, Dict[str, Any]],
    available_evidence: str = "",
    factor_context: str = "",
) -> str:
    """组装给审稿人的 user message。

    传入的是 agent 主键 -> 结果 dict,要求每个 dict 至少有 name/signal/confidence/reason,
    可选有 evidence/invalid_if/risks。
    available_evidence: v0.12 RAG 检索到的可用证据列表 (用于评估证据覆盖率)
    factor_context: v0.12 量化因子分析 (用于评估因子一致性)
    """
    lines: List[str] = [
        f"标的:{stock_name}",
        "",
        "==== 市场简报(原始数据) ====",
        market_brief.strip() or "(无)",
        "",
    ]
    if factor_context:
        lines += ["==== 量化因子分析 ====", factor_context.strip(), ""]
    if available_evidence:
        lines += ["==== 可用证据 (数据源平台检索) ====", available_evidence.strip(), ""]
    lines += ["==== 待审稿的 Agent 输出 ===="]
    for key, r in agent_results.items():
        lines.append(f"--- key: {key} ---")
        lines.append(f"name: {r.get('name', key)}")
        lines.append(f"signal: {r.get('signal', '观望')}")
        lines.append(f"confidence: {r.get('confidence', 0)}")
        lines.append(f"reason: {r.get('reason', '')}")
        ev_text = _serialize_evidence(r.get("evidence"))
        if ev_text:
            lines.append("evidence:")
            for ev in ev_text:
                lines.append(f"  - {ev}")
        if r.get("invalid_if"):
            lines.append(f"invalid_if: {r['invalid_if']}")
        risks = r.get("risks") or []
        if risks:
            lines.append("risks:")
            for x in risks:
                lines.append(f"  - {x}")
        lines.append("")

    lines += [
        "==== 任务 ====",
        "请按系统人设里的要求,只返回一个 JSON 对象,字段为 agents (数组) 与 divergence (对象)。",
        "agents 数组中每个元素的 key 必须严格对应上面给出的 key,不要新增、不要省略。",
    ]
    return "\n".join(lines)


# ============== 输出校验 ==============
def _safe_int_score(v: Any) -> int:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 50
    if x != x:  # NaN
        return 50
    return max(0, min(100, int(round(x))))


def _safe_str_list(values: Any, limit: int = 3, max_len: int = 120) -> List[str]:
    if not values:
        return []
    if isinstance(values, str):
        items = [p.strip(" -·•\t") for p in values.splitlines() if p.strip()]
    elif isinstance(values, (list, tuple)):
        items = values
    else:
        items = [values]
    out: List[str] = []
    for it in items:
        s = str(it).strip()
        if not s:
            continue
        out.append(s[:max_len])
        if len(out) >= limit:
            break
    return out


def _safe_str(value: Any, max_len: int = 200, default: str = "") -> str:
    if value is None:
        return default
    s = str(value).strip()
    if not s:
        return default
    return s[:max_len]


def parse_critic_response(
    raw: Any,
    expected_keys: List[str],
) -> Dict[str, Any]:
    """把 LLM 返回的对象规范化成 {agents: {key: review}, divergence: {...}}。

    - 输入既可以是 LLM 直接返回的 dict,也可以是字符串(自动 _extract_json);
    - 缺失或多余的 key 都会过滤,保证输出的 agents 字段集合 = expected_keys ∩ 模型给出的;
      未被模型审到的 agent 不会出现在结果里(由调用方自行决定是否当作"无审稿")。
    """
    data: Any = raw
    if isinstance(raw, str):
        data = _extract_json(raw) or {}
    if not isinstance(data, dict):
        data = {}

    agents_out: Dict[str, Dict[str, Any]] = {}
    raw_agents = data.get("agents")
    if isinstance(raw_agents, list):
        seen = set()
        for item in raw_agents:
            if not isinstance(item, dict):
                continue
            key = _safe_str(item.get("key"), max_len=64)
            if not key or key not in expected_keys or key in seen:
                continue
            seen.add(key)
            agents_out[key] = {
                "quality_score": _safe_int_score(item.get("quality_score")),
                "supported": _safe_str_list(item.get("supported")),
                "contradictions": _safe_str_list(item.get("contradictions")),
                "missing_evidence": _safe_str_list(item.get("missing_evidence")),
                "overconfident": bool(item.get("overconfident", False)),
                "comment": _safe_str(item.get("comment"), max_len=200),
            }

    div_raw = data.get("divergence") if isinstance(data.get("divergence"), dict) else {}
    level = _safe_str(div_raw.get("level"), max_len=4)
    if level not in VALID_DIVERGENCE_LEVELS:
        level = "无" if len(expected_keys) <= 1 else "中"
    divergence = {
        "level": level,
        "main_axis": _safe_str(div_raw.get("main_axis"), max_len=40),
        "summary": _safe_str(div_raw.get("summary"), max_len=240),
    }

    return {"agents": agents_out, "divergence": divergence}


# ============== 主入口 ==============
def run_batch_critic(
    stock_name: str,
    market_brief: str,
    agent_results: Dict[str, Dict[str, Any]],
    *,
    vendor: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout_max_tokens: int = 2048,
) -> Dict[str, Any]:
    """对一组 agent 输出做一次批量审稿。

    Returns:
        {
            "agents":     {agent_key: review_dict},
            "divergence": {level, main_axis, summary},
            "ok":         bool,
            "vendor":     str,        # 实际使用的 vendor label
            "model":      str,
            "fallback_used": bool,
            "error":      str,        # ok=False 时填充
        }
    """
    if not agent_results:
        return {
            "agents": {},
            "divergence": {"level": "无", "main_axis": "", "summary": ""},
            "ok": True,
            "vendor": "",
            "model": "",
            "fallback_used": False,
            "error": "",
        }

    expected_keys = list(agent_results.keys())
    system_prompt = load_critic_system_prompt()

    # v0.12: 获取因子上下文
    factor_ctx = ""
    try:
        from backend.llm_agents import fetch_factor_context

        # 从 market_brief 中提取 symbol
        import re

        sym_match = re.search(r"【标的】.*?\((\d{6})", market_brief)
        if sym_match:
            factor_ctx = fetch_factor_context(sym_match.group(1), stock_name)
    except Exception:
        pass

    user_msg = build_critic_prompt(
        stock_name, market_brief, agent_results, factor_context=factor_ctx
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    primary = (
        vendor or DEFAULT_CRITIC_MODEL[0],
        model or DEFAULT_CRITIC_MODEL[1],
    )
    candidates = [primary]
    fallback = _llm_agents.get_configured_provider()
    if fallback != primary:
        candidates.append(fallback)

    last_err = ""
    for vd, md in candidates:
        try:
            cfg = VENDORS.get(vd) or {}
            is_primary = (vd, md) == primary
            call_api_key = (api_key or None) if is_primary else None
            call_base_url = (base_url or None) if is_primary else None
            if (
                not call_api_key
                and not call_base_url
                and not (cfg.get("api_key") and cfg.get("base_url"))
            ):
                last_err = f"{vd} 未配置完整"
                continue
            text = call_llm(
                vendor=vd,
                model=md,
                messages=messages,
                json_mode=True,
                max_tokens=timeout_max_tokens,
                temperature=0.2,
                api_key=call_api_key,
                base_url=call_base_url,
            )
            parsed = parse_critic_response(text, expected_keys)
            if not parsed["agents"]:
                # 模型返回了 JSON,但 keys 全部对不上;视为失败,尝试兜底
                last_err = f"{vd} 返回的 keys 不匹配"
                continue
            return {
                **parsed,
                "ok": True,
                "vendor": VENDORS.get(vd, {}).get("label", vd),
                "model": md,
                "fallback_used": (vd != primary[0]),
                "error": "",
            }
        except Exception as e:
            last_err = str(e)[:200]
            continue

    return {
        "agents": {},
        "divergence": {"level": "无", "main_axis": "", "summary": ""},
        "ok": False,
        "vendor": "",
        "model": "",
        "fallback_used": True,
        "error": last_err or "未知错误",
    }


if __name__ == "__main__":
    # 离线 self-test:验证序列化 + 解析,不调用 LLM
    fake_brief = "近5日主力净流入2.3亿,MA20 上行,RSI 65"
    fake_agents = {
        "fundamental": {
            "name": "🏛️ 基本面分析师",
            "signal": "买入",
            "confidence": 78,
            "reason": "高 ROE + 行业龙头",
            "evidence": [{"type": "fundamental", "claim": "ROE 30%"}],
        },
        "technical": {
            "name": "📐 技术分析师",
            "signal": "卖出",
            "confidence": 65,
            "reason": "短期超买",
            "evidence": [{"type": "technical", "claim": "RSI > 80"}],
            "risks": ["回踩 MA60"],
        },
    }
    prompt = build_critic_prompt("贵州茅台", fake_brief, fake_agents)
    print("--- prompt sample ---")
    print(prompt[:400])

    fake_resp = json.dumps(
        {
            "agents": [
                {
                    "key": "fundamental",
                    "quality_score": 80,
                    "supported": ["ROE 30%"],
                    "contradictions": [],
                    "missing_evidence": [],
                    "overconfident": False,
                    "comment": "扎实",
                },
                {
                    "key": "technical",
                    "quality_score": 50,
                    "supported": [],
                    "contradictions": ["与简报中 RSI 65 不符"],
                    "missing_evidence": [],
                    "overconfident": True,
                    "comment": "数字引用错误",
                },
                {"key": "ghost", "quality_score": 99, "comment": "应该被过滤"},
            ],
            "divergence": {
                "level": "中",
                "main_axis": "估值 vs 短期超买",
                "summary": "基本面看长期,技术看短期。",
            },
        },
        ensure_ascii=False,
    )
    parsed = parse_critic_response(fake_resp, list(fake_agents.keys()))
    print("\n--- parsed ---")
    print(json.dumps(parsed, ensure_ascii=False, indent=2))
