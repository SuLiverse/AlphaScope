"""证据链引擎 — 按 claim 分组、来源可信度、时间衰减、多源一致性、反方证据、缺失提醒"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

from backend.quality.source_rank import SourceRanker
from backend.quality.research_trust import assess_research_trust, evidence_freshness

# 信号关键词（用于反方证据检测）
_BUY_KEYWORDS = {"买入", "看多", "增持", "buy", "long", "bull"}
_SELL_KEYWORDS = {"卖出", "看空", "减持", "sell", "short", "bear"}

# 置信度参数
BASE_CONFIDENCE = 0.6
BOOST_PER_SOURCE = 0.1
MAX_CONFIDENCE = 0.95
MIN_CONFIDENCE = 0.1


def build_evidence_chain(
    evidence_items: list[dict[str, Any]],
    agent_signals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """构建证据链。

    Args:
        evidence_items: Agent 产出的 evidence list，每条包含 type/claim/data_date/source
        agent_signals: Agent 信号列表，每条包含 agent/signal/has_evidence，用于缺失检测

    Returns:
        {
            "bundles": [...],         # 按 claim 分组的证据束
            "contradictions": [...],  # 矛盾证据
            "missing_evidence": [...], # 缺少证据的关键结论
            "coverage": float,        # 有证据的结论占比
            "overall_confidence": float, # 综合置信度
        }
    """
    if not evidence_items:
        return _empty_result(agent_signals)

    ranker = SourceRanker()
    now = time.time()

    # 按 claim 分组
    bundles = _group_by_claim(evidence_items, ranker, now)

    # 检测矛盾
    contradictions = _detect_contradictions(bundles)

    # 检测证据缺失
    missing = _detect_missing_evidence(agent_signals, evidence_items)

    # 计算覆盖率
    coverage = _calculate_coverage(agent_signals, evidence_items)

    # 综合置信度
    overall = _calculate_overall_confidence(bundles)
    trust = assess_research_trust(
        evidence_items,
        agent_signals=agent_signals,
        contradictions=contradictions,
        missing_evidence=missing,
        now=now,
    )

    return {
        "bundles": bundles,
        "contradictions": contradictions,
        "missing_evidence": missing,
        "coverage": round(coverage, 2),
        "overall_confidence": round(overall, 2),
        "trust": trust,
    }


def _group_by_claim(items: list[dict], ranker: SourceRanker, now: float) -> list[dict[str, Any]]:
    """按 claim 关键词分组，计算每组置信度"""
    groups: dict[str, list[dict]] = defaultdict(list)

    for item in items:
        claim = item.get("claim", "").strip()
        if not claim:
            continue
        key = _claim_key(claim)
        groups[key].append(item)

    bundles = []
    for key, group_items in groups.items():
        sources = set()
        trust_scores = []
        decay_factors = []
        confidences = []

        for item in group_items:
            source = item.get("source", "unknown")
            sources.add(source)
            trust_scores.append(ranker.get_trust_score(str(source).casefold()))
            decay_factors.append(_time_decay(item.get("data_date", ""), now, item.get("type", "other")))
            confidences.append(_normalize_confidence(item.get("confidence", 0.7)))

        source_count = len(sources)
        avg_trust = sum(trust_scores) / len(trust_scores) if trust_scores else 0.3
        avg_decay = sum(decay_factors) / len(decay_factors) if decay_factors else 1.0
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.5

        # 多源确认提升
        boosted = min(
            BASE_CONFIDENCE + (source_count - 1) * BOOST_PER_SOURCE,
            MAX_CONFIDENCE,
        )
        # 综合置信度 = 加权平均
        final_confidence = min(
            boosted * 0.4 + avg_trust * 0.3 + avg_decay * 0.2 + avg_conf * 0.1,
            MAX_CONFIDENCE,
        )

        # 代表性 claim（取最长的）
        best_claim = max(group_items, key=lambda x: len(x.get("claim", ""))).get("claim", key)

        bundles.append(
            {
                "claim": best_claim,
                "evidence": group_items,
                "confidence": round(final_confidence, 2),
                "source_count": source_count,
                "trust_score": round(avg_trust, 2),
                "decay_factor": round(avg_decay, 2),
                "contradictions": [],
            }
        )

    # 按置信度降序
    bundles.sort(key=lambda b: b["confidence"], reverse=True)
    return bundles


def _claim_key(claim: str) -> str:
    """提取 claim 的核心关键词作为分组 key"""
    # 去标点、取前 20 字符作为 key
    cleaned = re.sub(r"[^\w一-鿿]", "", claim)
    return cleaned[:20].lower() if cleaned else claim[:20].lower()


def _time_decay(data_date: str, now: float, evidence_type: str = "other") -> float:
    """计算按证据类型区分的时间衰减因子。"""
    if not data_date:
        return 0.0
    return max(evidence_freshness(data_date, evidence_type, now=now), MIN_CONFIDENCE)


def _normalize_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.7
    if confidence > 1:
        confidence /= 100
    return max(0.0, min(1.0, confidence))


def _detect_contradictions(bundles: list[dict]) -> list[str]:
    """检测同 claim 组内的信号矛盾"""
    contradictions = []

    for bundle in bundles:
        signals = set()
        for item in bundle.get("evidence", []):
            claim = item.get("claim", "").lower()
            if any(k in claim for k in _BUY_KEYWORDS):
                signals.add("buy")
            elif any(k in claim for k in _SELL_KEYWORDS):
                signals.add("sell")

        if "buy" in signals and "sell" in signals:
            contradictions.append(f"信号矛盾: {bundle['claim']} — 同时存在买入和卖出信号")
            bundle["contradictions"].append("买入/卖出信号冲突")

    return contradictions


def _detect_missing_evidence(
    agent_signals: list[dict[str, Any]] | None,
    evidence_items: list[dict],
) -> list[str]:
    """检测关键结论缺少证据"""
    if not agent_signals:
        return []

    missing = []

    for agent in agent_signals:
        signal = agent.get("signal", "")
        if signal not in ("买入", "卖出"):
            continue
        has_evidence = agent.get("has_evidence", True)
        agent_name = agent.get("agent", "未知")

        if not has_evidence:
            missing.append(f"{agent_name}: 信号={signal}, 无证据支撑")

    return missing


def _calculate_coverage(
    agent_signals: list[dict[str, Any]] | None,
    evidence_items: list[dict],
) -> float:
    """计算有证据的结论占比"""
    if not agent_signals:
        return 1.0

    key_signals = [a for a in agent_signals if a.get("signal") in ("买入", "卖出")]
    if not key_signals:
        return 1.0

    with_evidence = sum(1 for a in key_signals if a.get("has_evidence", True))
    return with_evidence / len(key_signals)


def _calculate_overall_confidence(bundles: list[dict]) -> float:
    """计算综合置信度"""
    if not bundles:
        return 0.0
    return sum(b["confidence"] for b in bundles) / len(bundles)


def _empty_result(agent_signals: list[dict] | None = None) -> dict[str, Any]:
    missing = _detect_missing_evidence(agent_signals, [])
    return {
        "bundles": [],
        "contradictions": [],
        "missing_evidence": missing,
        "coverage": _calculate_coverage(agent_signals, []),
        "overall_confidence": 0.0,
        "trust": assess_research_trust([], agent_signals=agent_signals, missing_evidence=missing),
    }
