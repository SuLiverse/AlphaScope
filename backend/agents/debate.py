"""多空辩论裁决 (Bull/Bear Debate Synthesizer) — v1.9.14

确定性后处理:**不新增任何 LLM Agent、不触网、不增成本**,而是把一次分析里
**已经算出来**的 Agent 信号 + Critic 评审分歧 + 风控 gate + 数据核验,综合成
结构化的「看多方 / 看空方(反方质询) / 主席裁决」,把单一结论升级为可审计的
多空对峙。

为什么是确定性模块而非新 Agent:三份战略报告(compass / deep-research / 1.txt)
都把「反方质询 + 裁决理由入报」列为差异化核心,但**同样都警告**「在证据链 /
结构化输出 / 数据治理稳定前不要堆复杂 Agent」。这些前置条件(evidence_store /
结构化 Agent 输出 / data_verifier / 风控 gate)均已就位,因此以一个纯函数、
失败安全的合成器落地(对标 ``quant/risk/engine.py`` 与 ``agents/data_verifier.py``
的风格),复用既有 skeptic 信号(看空 Agent / Critic 分歧 / 风控否决 / 数据缺失)
组成反方,零额外模型调用。

合规红线:看多/看空描述的是**研究分歧与证据强弱**,裁决是对**结论置信度 /
共识度**的判断,**绝不构成买卖指令或收益承诺**,一律附免责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OK = "ok"
DEGRADED = "degraded"

# 信号 → 阵营(兼容中文/英文/口语)
_BULL_SIGNALS = {"买入", "buy", "看多", "增持", "bullish"}
_BEAR_SIGNALS = {"卖出", "sell", "看空", "减持", "bearish"}

# 反方质询各来源的权重(纯启发式, 仅用于排序/强弱对比, 不是概率)
_W_RISK_VETO = 40.0
_W_DATA_MISSING = 15.0
_W_DATA_ANOMALY = 10.0
_W_DATA_STALE = 8.0
_W_CRITIC_DIVERGENCE = 20.0

_DISCLAIMER = "多空对峙描述的是研究分歧与证据强弱,裁决是对结论置信度/共识度的判断,不构成任何买卖指令或收益承诺。"


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class DebatePoint:
    """辩论中的一条论点 / 质询。"""

    side: str  # bull | bear
    source: str  # agent key 或 risk/data/critic
    kind: str  # agent | low_conviction | risk_veto | data_gap | critic_divergence
    claim: str
    weight: float = 0.0
    confidence: float = 0.0
    evidence_ids: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "source": self.source,
            "kind": self.kind,
            "claim": self.claim,
            "weight": round(self.weight, 1),
            "confidence": round(self.confidence, 1),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass
class DebateReport:
    status: str
    consensus: str  # 看多共识|偏看多|多空分歧|高度分歧|偏看空|看空共识|中性观望|风控否决|未知
    consensus_score: float  # 0-100, 越大越一边倒
    divergence_level: str  # 借 Critic: 无/低/中/高
    bull_strength: float
    bear_strength: float
    n_bull: int
    n_bear: int
    n_neutral: int
    bull_points: list[DebatePoint]
    bear_points: list[DebatePoint]
    ruling: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "consensus": self.consensus,
            "consensus_score": self.consensus_score,
            "divergence_level": self.divergence_level,
            "bull_strength": round(self.bull_strength, 1),
            "bear_strength": round(self.bear_strength, 1),
            "n_bull": self.n_bull,
            "n_bear": self.n_bear,
            "n_neutral": self.n_neutral,
            "bull_points": [p.to_dict() for p in self.bull_points],
            "bear_points": [p.to_dict() for p in self.bear_points],
            "ruling": self.ruling,
            "disclaimer": _DISCLAIMER,
        }


def _degraded(reason: str) -> DebateReport:
    return DebateReport(
        status=DEGRADED,
        consensus="未知",
        consensus_score=0.0,
        divergence_level="无",
        bull_strength=0.0,
        bear_strength=0.0,
        n_bull=0,
        n_bear=0,
        n_neutral=0,
        bull_points=[],
        bear_points=[],
        ruling=reason,
    )


def synthesize_debate(
    agents: dict[str, Any] | None,
    summary: dict[str, Any] | None = None,
    critic: dict[str, Any] | None = None,
    risk_gate: dict[str, Any] | None = None,
    data_verification: dict[str, Any] | None = None,
    *,
    second_round: bool = False,
) -> DebateReport:
    """把已算出的 Agent 信号 + 评审 + 风控 + 数据核验合成多空辩论裁决。

    ``second_round``: 可选「第二轮」强化反方质询(仍**不调用 LLM**),
    仅在默认辩论上追加交叉质询要点; 默认 False 保持零成本。

    永不抛出:任一输入异常 → 返回 ``DEGRADED`` 报告。
    """
    try:
        report = _synthesize(agents or {}, summary, critic, risk_gate, data_verification)
        if second_round and report.status == OK:
            report = _apply_second_round(report, agents or {}, summary)
        return report
    except Exception as exc:  # noqa: BLE001 - 失败安全
        return _degraded(f"多空辩论合成失败,已降级: {exc}")


def _apply_second_round(
    report: DebateReport,
    agents: dict[str, Any],
    summary: dict[str, Any] | None,
) -> DebateReport:
    """确定性第二轮: 用对立面交叉质询强化弱侧, 不触网。"""
    extra_bull: list[DebatePoint] = []
    extra_bear: list[DebatePoint] = []
    final = str((summary or {}).get("final") or "")
    # 对强势一侧追加「反方必须回应」的质询点
    if report.bull_strength >= report.bear_strength:
        extra_bear.append(
            DebatePoint(
                side="bear",
                source="second_round",
                kind="cross_examine",
                claim=(
                    f"第二轮质询: 多头净优势 {report.bull_strength - report.bear_strength:.0f},"
                    f"请核对是否过度依赖单一维度; 主席结论「{final or '—'}」需有证据编号支撑。"
                ),
                weight=12.0,
                confidence=50.0,
            )
        )
    else:
        extra_bull.append(
            DebatePoint(
                side="bull",
                source="second_round",
                kind="cross_examine",
                claim=(
                    f"第二轮质询: 空头净优势 {report.bear_strength - report.bull_strength:.0f},"
                    "请核对是否遗漏修复信号或超跌结构; 避免单边叙事。"
                ),
                weight=12.0,
                confidence=50.0,
            )
        )
    # 低置信 Agent 再点名
    for key, raw in agents.items():
        if not isinstance(raw, dict):
            continue
        conf = _num(raw.get("confidence"))
        if 0 < conf < 45:
            name = str(raw.get("name") or key)
            extra_bear.append(
                DebatePoint(
                    side="bear",
                    source=key,
                    kind="cross_examine",
                    claim=f"第二轮: {name} 置信仅 {conf:.0f}, 其结论权重应下调。",
                    weight=8.0,
                    confidence=conf,
                    evidence_ids=list(raw.get("evidence_ids") or []),
                )
            )
    new_bull = list(report.bull_points) + extra_bull
    new_bear = list(report.bear_points) + extra_bear
    bull_s = report.bull_strength + sum(p.weight for p in extra_bull)
    bear_s = report.bear_strength + sum(p.weight for p in extra_bear)
    ruling = report.ruling
    if extra_bull or extra_bear:
        ruling = (ruling or "") + " | 已启用确定性第二轮交叉质询(无额外 LLM)。"
    return DebateReport(
        status=report.status,
        consensus=report.consensus,
        consensus_score=report.consensus_score,
        divergence_level=report.divergence_level,
        bull_strength=bull_s,
        bear_strength=bear_s,
        n_bull=report.n_bull,
        n_bear=report.n_bear,
        n_neutral=report.n_neutral,
        bull_points=new_bull,
        bear_points=new_bear,
        ruling=ruling,
    )


def _synthesize(
    agents: dict[str, Any],
    summary: dict[str, Any] | None,
    critic: dict[str, Any] | None,
    risk_gate: dict[str, Any] | None,
    data_verification: dict[str, Any] | None,
) -> DebateReport:
    bull_points: list[DebatePoint] = []
    bear_points: list[DebatePoint] = []
    n_bull = n_bear = n_neutral = 0
    bull_strength = 0.0
    bear_strength = 0.0

    for key, raw in agents.items():
        if not isinstance(raw, dict):
            continue
        signal = str(raw.get("signal", "")).strip()
        conf = _num(raw.get("confidence"))
        reason = str(raw.get("reason", "")).strip() or "(未给出理由)"
        name = str(raw.get("name") or key)
        eids = raw.get("evidence_ids") or []

        if signal in _BULL_SIGNALS:
            n_bull += 1
            bull_strength += conf
            bull_points.append(DebatePoint("bull", key, "agent", f"{name}:{reason}", conf, conf, eids))
            # 反方质询:看多但信心不足(过度自信的反面 — 信心薄弱)
            if 0 < conf < 50:
                bear_points.append(
                    DebatePoint(
                        "bear",
                        key,
                        "low_conviction",
                        f"{name} 看多但信心仅 {conf:.0f}%,确定性不足",
                        50.0 - conf,
                    )
                )
        elif signal in _BEAR_SIGNALS:
            n_bear += 1
            bear_strength += conf
            bear_points.append(DebatePoint("bear", key, "agent", f"{name}:{reason}", conf, conf, eids))
        else:
            n_neutral += 1

    # 反方来源 2:风控 gate 否决理由(最重)
    rg = risk_gate or {}
    vetoed = bool(rg.get("vetoed"))
    for vr in rg.get("veto_reasons", []) or []:
        bear_points.append(DebatePoint("bear", "risk", "risk_veto", f"风控否决:{vr}", _W_RISK_VETO))
        bear_strength += _W_RISK_VETO

    # 反方来源 3:数据缺失 / 过期 / 异常(data_verifier)
    dv = data_verification or {}
    for lbl in dv.get("missing", []) or []:
        bear_points.append(
            DebatePoint(
                "bear",
                "data",
                "data_gap",
                f"数据缺失:{lbl}(下游严禁编造)",
                _W_DATA_MISSING,
            )
        )
    for lbl in dv.get("anomalies", []) or []:
        bear_points.append(DebatePoint("bear", "data", "data_gap", f"数值异常:{lbl}", _W_DATA_ANOMALY))
    for lbl in dv.get("stale", []) or []:
        bear_points.append(DebatePoint("bear", "data", "data_gap", f"数据过期:{lbl}", _W_DATA_STALE))

    # 反方来源 4:Critic 评审分歧
    div = (critic or {}).get("divergence") or {}
    divergence_level = str(div.get("level") or "无")
    div_summary = str(div.get("summary") or "").strip()
    if div_summary and divergence_level in ("中", "高"):
        bear_points.append(
            DebatePoint(
                "bear",
                "critic",
                "critic_divergence",
                f"评审分歧({divergence_level}):{div_summary}",
                _W_CRITIC_DIVERGENCE,
            )
        )

    # 强论点排前(便于 UI 与裁决取最强)
    bull_points.sort(key=lambda p: p.weight, reverse=True)
    bear_points.sort(key=lambda p: p.weight, reverse=True)

    has_bull_agent = any(p.kind == "agent" for p in bull_points)
    has_bear_agent = any(p.kind == "agent" for p in bear_points)

    if vetoed:
        return DebateReport(
            status=OK,
            consensus="风控否决",
            consensus_score=0.0,
            divergence_level=divergence_level,
            bull_strength=bull_strength,
            bear_strength=bear_strength,
            n_bull=n_bull,
            n_bear=n_bear,
            n_neutral=n_neutral,
            bull_points=bull_points,
            bear_points=bear_points,
            ruling=_ruling_vetoed(rg),
        )

    total = bull_strength + bear_strength
    consensus_score = round(abs(bull_strength - bear_strength) / total * 100, 1) if total else 0.0
    consensus = _label(has_bull_agent, has_bear_agent, n_neutral, consensus_score, divergence_level)
    ruling = _ruling(consensus, bull_points, bear_points, n_bull, n_bear)

    return DebateReport(
        status=OK,
        consensus=consensus,
        consensus_score=consensus_score,
        divergence_level=divergence_level,
        bull_strength=bull_strength,
        bear_strength=bear_strength,
        n_bull=n_bull,
        n_bear=n_bear,
        n_neutral=n_neutral,
        bull_points=bull_points,
        bear_points=bear_points,
        ruling=ruling,
    )


def _label(has_bull: bool, has_bear: bool, n_neutral: int, score: float, divergence: str) -> str:
    if not has_bull and not has_bear:
        return "中性观望" if n_neutral else "未知"
    if has_bull and not has_bear:
        return "看多共识" if score >= 50 else "偏看多"
    if has_bear and not has_bull:
        return "看空共识" if score >= 50 else "偏看空"
    # 双方都有 Agent
    if divergence == "高" or score < 25:
        return "高度分歧"
    return "多空分歧"


def _ruling_vetoed(rg: dict[str, Any]) -> str:
    reasons = ";".join(str(r) for r in (rg.get("veto_reasons") or [])) or "触发 critical 风控规则"
    return f"风控一票否决({reasons})。方向性结论一律不作为投资依据,建议先消除风控触发项再重新评估。"


def _ruling(
    consensus: str,
    bull_points: list[DebatePoint],
    bear_points: list[DebatePoint],
    n_bull: int,
    n_bear: int,
) -> str:
    top_bull = bull_points[0].claim if bull_points else "—"
    bear_agent_pts = [p for p in bear_points if p.kind == "agent"]
    top_bear = bear_agent_pts[0].claim if bear_agent_pts else (bear_points[0].claim if bear_points else "—")
    n_challenges = len(bear_points)

    if consensus == "中性观望":
        return "各方信号偏中性,缺乏明确方向共识,确定性低;建议补充缺失维度数据后再评估。"
    if consensus in ("看多共识", "偏看多"):
        base = f"看多方以 {n_bull} 票占据主导(最强论据:{top_bull}),但仍存在 {n_challenges} 条反方质询(如:{top_bear})。"
        if consensus == "看多共识":
            base += "一致性偏高反而需警惕群体共识/拥挤风险,建议交叉验证关键证据、并以样本外走查检验稳健性后再判断。"
        else:
            base += "看多略占优但分歧仍在,结论确定性中等,不宜单边定论。"
        return base
    if consensus in ("看空共识", "偏看空"):
        return (
            f"看空/质询方占据主导({n_challenges} 条反方质询,如:{top_bear})"
            f",看多论据偏弱(最强:{top_bull});风险信号需优先排查后再评估。"
        )
    # 多空分歧 / 高度分歧
    return (
        f"看多 {n_bull} 票 vs 看空 {n_bear} 票,双方均有证据支撑("
        f"多:{top_bull};空:{top_bear})。结论确定性中等偏低,不宜单边定论,"
        f"建议聚焦核心分歧点补证、并结合风控与样本外验证。"
    )


def format_debate_section(report: DebateReport) -> str:
    """把辩论裁决渲染成可嵌入研报的纯文本小节(可审计、带免责)。"""
    if report is None or report.status != OK:
        return ""
    lines = [
        "",
        "## 多空辩论与裁决",
        "",
        f"**裁决：{report.consensus}**（共识度 {report.consensus_score:.0f}/100）",
        "",
        report.ruling,
        "",
    ]
    if report.bull_points:
        lines.append("**看多方：**")
        for p in report.bull_points[:5]:
            lines.append(f"- {p.claim}")
        lines.append("")
    if report.bear_points:
        lines.append("**看空方 / 反方质询：**")
        for p in report.bear_points[:6]:
            lines.append(f"- {p.claim}")
        lines.append("")
    lines.append(f"> {_DISCLAIMER}")
    return "\n".join(lines)
