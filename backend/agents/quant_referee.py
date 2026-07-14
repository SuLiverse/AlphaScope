"""确定性 Quant Referee — 与 LLM 辩论并行的规则信号轨 (P0)。

从 stock_data 中的行情/技术指标按**纯规则**产出多空信号卡,作为 Agent 结论的
grounding 对照,不新增 LLM 调用、不触网、失败安全。

设计对齐:
- ``agents/debate.py`` / ``agents/data_verifier.py`` / ``quant/risk/engine.py``
- 社区 multi-agent-investment 的「数学 Decision Hub」思想:LLM 解释,规则裁判

合规:描述历史量价结构与规则状态,**不预测、不构成买卖指令**。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

OK = "ok"
DEGRADED = "degraded"
INSUFFICIENT = "insufficient"

BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"

_DISCLAIMER = (
    "Quant Referee 仅描述历史量价与技术规则状态,用于研究对照与幻觉抑制,"
    "不预测涨跌、不构成任何买卖指令或收益承诺。"
)

_BULL_LLM = {"买入", "buy", "看多", "增持", "bullish", "偏多"}
_BEAR_LLM = {"卖出", "sell", "看空", "减持", "bearish", "偏空"}


def _num(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace("%", "")
        if s in ("N/A", "n/a", "暂无", "-", "—", "nan", "None"):
            return None
        try:
            return float(s)
        except ValueError:
            return None
    try:
        f = float(value)
        return f if f == f else None  # NaN
    except (TypeError, ValueError):
        return None


@dataclass
class RefereeSignal:
    rule_id: str
    direction: str  # bullish | bearish | neutral
    weight: float
    claim: str
    value: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "direction": self.direction,
            "weight": round(self.weight, 1),
            "claim": self.claim,
            "value": self.value,
        }


@dataclass
class RefereeReport:
    status: str
    symbol: str
    stance: str
    net_score: float
    signals: list[RefereeSignal] = field(default_factory=list)
    llm_alignment: str = "未对比"
    note: str = ""

    @property
    def n_bull(self) -> int:
        return sum(1 for s in self.signals if s.direction == BULLISH)

    @property
    def n_bear(self) -> int:
        return sum(1 for s in self.signals if s.direction == BEARISH)

    @property
    def n_neutral(self) -> int:
        return sum(1 for s in self.signals if s.direction == NEUTRAL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "stance": self.stance,
            "net_score": round(self.net_score, 1),
            "signals": [s.to_dict() for s in self.signals],
            "n_bull": self.n_bull,
            "n_bear": self.n_bear,
            "n_neutral": self.n_neutral,
            "llm_alignment": self.llm_alignment,
            "note": self.note,
            "disclaimer": _DISCLAIMER,
        }


def _stance_from_score(score: float) -> str:
    if score >= 25:
        return "多头占优"
    if score >= 8:
        return "偏多"
    if score <= -25:
        return "空头占优"
    if score <= -8:
        return "偏空"
    return "中性"


def _llm_camp(final: Any) -> Optional[str]:
    if final is None:
        return None
    s = str(final).strip().lower()
    if not s:
        return None
    # also check original case tokens
    raw = str(final).strip()
    if raw in _BULL_LLM or s in _BULL_LLM or any(k in raw for k in ("买入", "看多", "增持")):
        return BULLISH
    if raw in _BEAR_LLM or s in _BEAR_LLM or any(k in raw for k in ("卖出", "看空", "减持", "否决")):
        return BEARISH
    if any(k in raw for k in ("观望", "中性", "hold")):
        return NEUTRAL
    return None


def _align_llm(net_score: float, llm_final: Any) -> str:
    camp = _llm_camp(llm_final)
    if camp is None:
        return "未对比"
    ref = BULLISH if net_score > 5 else BEARISH if net_score < -5 else NEUTRAL
    if camp == NEUTRAL or ref == NEUTRAL:
        if camp == ref:
            return "一致"
        return "同向" if (camp == NEUTRAL or ref == NEUTRAL) and abs(net_score) < 15 else "背离"
    if camp == ref:
        return "一致" if abs(net_score) >= 15 else "同向"
    return "冲突"


def _eval_rules(data: dict[str, Any]) -> list[RefereeSignal]:
    signals: list[RefereeSignal] = []
    close = _num(data.get("close"))
    ma5 = _num(data.get("ma5"))
    ma20 = _num(data.get("ma20"))
    ma60 = _num(data.get("ma60"))
    rsi = _num(data.get("rsi"))
    dif = _num(data.get("dif"))
    dea = _num(data.get("dea"))
    macd = _num(data.get("macd"))
    period_high = _num(data.get("period_high"))
    period_low = _num(data.get("period_low"))
    vol_ratio = _num(data.get("vol_ratio"))

    # 1) 均线排列
    if close is not None and ma5 is not None and ma20 is not None:
        if ma60 is not None and close > ma5 > ma20 > ma60:
            signals.append(
                RefereeSignal(
                    "ma_alignment",
                    BULLISH,
                    30.0,
                    "收盘价位于 MA5>MA20>MA60 多头排列之上",
                    f"close={close:.2f}",
                )
            )
        elif ma60 is not None and close < ma5 < ma20 < ma60:
            signals.append(
                RefereeSignal(
                    "ma_alignment",
                    BEARISH,
                    30.0,
                    "收盘价位于 MA5<MA20<MA60 空头排列之下",
                    f"close={close:.2f}",
                )
            )
        elif close > ma20:
            signals.append(
                RefereeSignal(
                    "ma_alignment",
                    BULLISH,
                    12.0,
                    "收盘价站上 MA20",
                    f"close={close:.2f} ma20={ma20:.2f}",
                )
            )
        elif close < ma20:
            signals.append(
                RefereeSignal(
                    "ma_alignment",
                    BEARISH,
                    12.0,
                    "收盘价跌破 MA20",
                    f"close={close:.2f} ma20={ma20:.2f}",
                )
            )

    # 2) RSI
    if rsi is not None:
        if rsi >= 70:
            signals.append(
                RefereeSignal("rsi", BEARISH, 18.0, f"RSI({rsi:.1f}) 进入超买区(≥70)", f"rsi={rsi:.1f}")
            )
        elif rsi <= 30:
            signals.append(
                RefereeSignal("rsi", BULLISH, 18.0, f"RSI({rsi:.1f}) 进入超卖区(≤30)", f"rsi={rsi:.1f}")
            )
        elif 45 <= rsi <= 55:
            signals.append(
                RefereeSignal("rsi", NEUTRAL, 5.0, f"RSI({rsi:.1f}) 中性区间", f"rsi={rsi:.1f}")
            )
        elif rsi > 55:
            signals.append(
                RefereeSignal("rsi", BULLISH, 8.0, f"RSI({rsi:.1f}) 偏强", f"rsi={rsi:.1f}")
            )
        else:
            signals.append(
                RefereeSignal("rsi", BEARISH, 8.0, f"RSI({rsi:.1f}) 偏弱", f"rsi={rsi:.1f}")
            )

    # 3) MACD / DIF-DEA
    if dif is not None and dea is not None:
        if dif > dea and (macd is None or macd >= 0):
            signals.append(
                RefereeSignal(
                    "macd",
                    BULLISH,
                    16.0,
                    "DIF 位于 DEA 之上(MACD 多头结构)",
                    f"dif={dif:.4f} dea={dea:.4f}",
                )
            )
        elif dif < dea and (macd is None or macd <= 0):
            signals.append(
                RefereeSignal(
                    "macd",
                    BEARISH,
                    16.0,
                    "DIF 位于 DEA 之下(MACD 空头结构)",
                    f"dif={dif:.4f} dea={dea:.4f}",
                )
            )
        else:
            signals.append(
                RefereeSignal(
                    "macd",
                    NEUTRAL,
                    6.0,
                    "MACD 结构混杂",
                    f"dif={dif:.4f} dea={dea:.4f}",
                )
            )

    # 4) 区间位置
    if close is not None and period_high is not None and period_low is not None:
        span = period_high - period_low
        if span > 0:
            pos = (close - period_low) / span
            if pos >= 0.85:
                signals.append(
                    RefereeSignal(
                        "range_position",
                        BEARISH,
                        10.0,
                        f"价格接近区间高位({pos:.0%})",
                        f"pos={pos:.2f}",
                    )
                )
            elif pos <= 0.15:
                signals.append(
                    RefereeSignal(
                        "range_position",
                        BULLISH,
                        10.0,
                        f"价格接近区间低位({pos:.0%})",
                        f"pos={pos:.2f}",
                    )
                )
            else:
                signals.append(
                    RefereeSignal(
                        "range_position",
                        NEUTRAL,
                        4.0,
                        f"价格位于区间中部({pos:.0%})",
                        f"pos={pos:.2f}",
                    )
                )

    # 5) 量比
    if vol_ratio is not None:
        if vol_ratio >= 1.5:
            # 放量本身中性偏确认,方向跟随均线/价
            direction = BULLISH if close is not None and ma20 is not None and close >= ma20 else NEUTRAL
            if close is not None and ma20 is not None and close < ma20:
                direction = BEARISH
            signals.append(
                RefereeSignal(
                    "volume",
                    direction,
                    8.0,
                    f"量比偏高({vol_ratio:.2f}),量能放大",
                    f"vol_ratio={vol_ratio:.2f}",
                )
            )
        elif vol_ratio <= 0.7:
            signals.append(
                RefereeSignal(
                    "volume",
                    NEUTRAL,
                    5.0,
                    f"量比偏低({vol_ratio:.2f}),交投清淡",
                    f"vol_ratio={vol_ratio:.2f}",
                )
            )

    return signals


def _net_score(signals: list[RefereeSignal]) -> float:
    score = 0.0
    for s in signals:
        if s.direction == BULLISH:
            score += s.weight
        elif s.direction == BEARISH:
            score -= s.weight
        # neutral contributes 0 to net
    return score


def referee_stock(
    stock_data: dict[str, Any] | None,
    llm_final: Any = None,
) -> RefereeReport:
    """对单标的运行确定性量化裁判。失败安全,永不抛出。"""
    try:
        data = stock_data if isinstance(stock_data, dict) else {}
        symbol = str(data.get("symbol") or "")
        close = _num(data.get("close"))
        if close is None or close <= 0:
            return RefereeReport(
                status=INSUFFICIENT,
                symbol=symbol,
                stance="未知",
                net_score=0.0,
                signals=[],
                llm_alignment="未对比",
                note="缺少有效收盘价,无法做规则裁判",
            )

        signals = _eval_rules(data)
        if not signals:
            return RefereeReport(
                status=DEGRADED,
                symbol=symbol,
                stance="中性",
                net_score=0.0,
                signals=[],
                llm_alignment=_align_llm(0.0, llm_final) if llm_final is not None else "未对比",
                note="有价格但缺少可评估技术指标",
            )

        score = _net_score(signals)
        # 若仅有 1–2 条规则,标 degraded 但仍给 stance
        status = OK if len(signals) >= 2 else DEGRADED
        return RefereeReport(
            status=status,
            symbol=symbol,
            stance=_stance_from_score(score),
            net_score=score,
            signals=signals,
            llm_alignment=_align_llm(score, llm_final),
            note="",
        )
    except Exception as exc:  # noqa: BLE001
        return RefereeReport(
            status=DEGRADED,
            symbol="",
            stance="未知",
            net_score=0.0,
            signals=[],
            llm_alignment="未对比",
            note=f"裁判降级: {type(exc).__name__}",
        )


def format_referee_section(report: RefereeReport) -> str:
    """渲染可并入研报正文的小节。insufficient 时返回简短说明。"""
    if report is None:
        return ""
    lines = [
        "",
        "### 量化裁判 (Quant Referee)",
        f"- 状态: {report.status} · 立场: **{report.stance}** · 净分: {report.net_score:.1f}",
        f"- 规则信号: 多 {report.n_bull} / 空 {report.n_bear} / 中 {report.n_neutral}",
        f"- 与 LLM 结论对照: {report.llm_alignment}",
    ]
    if report.note:
        lines.append(f"- 备注: {report.note}")
    if report.signals:
        lines.append("- 细则:")
        for s in report.signals[:12]:
            arrow = {"bullish": "↑", "bearish": "↓", "neutral": "·"}.get(s.direction, "·")
            lines.append(f"  - {arrow} [{s.rule_id}] {s.claim}" + (f" ({s.value})" if s.value else ""))
    lines.append(f"- 免责: {_DISCLAIMER}")
    lines.append("")
    return "\n".join(lines)
