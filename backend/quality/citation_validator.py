"""数值与引用 Citation Validator — 证据可追溯核验 (P0)。

扫描 Agent 理由 / 研报正文中的:
1. 关键数字(价格、涨跌幅、RSI 等)是否能与 stock_data 字段对齐
2. ``[n]`` 证据编号是否落在 evidence_pool 内

失败安全、纯函数、不触网。未核验数字会拉低 grounding_score,并给出
置信度上限建议,避免「编造数字却显示干净成功」。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

OK = "ok"
DEGRADED = "degraded"

_DISCLAIMER = (
    "引用核验仅检查文本数字/证据编号是否能与本次研究快照对齐,"
    "未核验不等于一定虚假,但高置信结论应优先使用可追溯字段。"
)

# 捕获: 1234.56 / 1,234.56 / 5.6% / 58.3
_NUM_RE = re.compile(
    r"(?<![A-Za-z_])"  # 不跟在标识符后
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)"
    r"(?P<pct>\s*%)?"
)
_CITE_RE = re.compile(r"\[(\d{1,3})\]")

# 相对容差:价格类 0.5% 或绝对 0.05;百分比类绝对差 0.15
_PRICE_REL = 0.005
_PRICE_ABS = 0.05
_PCT_ABS = 0.15


def _to_float(value: Any) -> Optional[float]:
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
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _build_fact_table(stock_data: dict[str, Any] | None) -> list[tuple[str, float, str]]:
    """Return list of (field, value, kind) where kind is price|pct|other."""
    data = stock_data if isinstance(stock_data, dict) else {}
    specs: list[tuple[str, str]] = [
        ("close", "price"),
        ("ma5", "price"),
        ("ma20", "price"),
        ("ma60", "price"),
        ("period_high", "price"),
        ("period_low", "price"),
        ("day_change", "pct"),
        ("period_change", "pct"),
        ("change_pct", "pct"),
        ("rsi", "other"),
        ("turnover", "pct"),
        ("vol_ratio", "other"),
        ("volatility", "pct"),
        ("volume", "other"),
        ("dif", "other"),
        ("dea", "other"),
        ("macd", "other"),
    ]
    facts: list[tuple[str, float, str]] = []
    for key, kind in specs:
        v = _to_float(data.get(key))
        if v is None:
            continue
        facts.append((key, v, kind))
    return facts


def _matches(value: float, fact: float, kind: str, is_pct_token: bool) -> bool:
    if kind == "pct" or is_pct_token:
        return abs(value - fact) <= _PCT_ABS or abs(value - fact) / max(abs(fact), 1e-9) <= 0.02
    if kind == "price":
        return abs(value - fact) <= max(_PRICE_ABS, abs(fact) * _PRICE_REL)
    # other: rsi, volume etc — allow 1% rel or small abs
    return abs(value - fact) <= max(0.15, abs(fact) * 0.01)


@dataclass
class Claim:
    raw: str
    value: float
    is_percent: bool
    status: str  # verified | unverified | skipped
    matched_field: str = ""
    source: str = ""  # report | agent:key

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "value": self.value,
            "is_percent": self.is_percent,
            "status": self.status,
            "matched_field": self.matched_field,
            "source": self.source,
        }


@dataclass
class CitationReport:
    status: str
    n_claims: int = 0
    n_verified: int = 0
    n_unverified: int = 0
    n_citation_ok: int = 0
    n_citation_bad: int = 0
    grounding_score: float = 1.0
    suggest_confidence_cap: Optional[float] = None
    claims: list[Claim] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "n_claims": self.n_claims,
            "n_verified": self.n_verified,
            "n_unverified": self.n_unverified,
            "n_citation_ok": self.n_citation_ok,
            "n_citation_bad": self.n_citation_bad,
            "grounding_score": round(self.grounding_score, 3),
            "suggest_confidence_cap": self.suggest_confidence_cap,
            "claims": [c.to_dict() for c in self.claims[:50]],
            "issues": self.issues[:20],
            "note": self.note,
            "disclaimer": _DISCLAIMER,
        }


def _collect_texts(
    text: Any,
    agents: dict[str, Any] | None,
    research_report: Any,
) -> list[tuple[str, str]]:
    """List of (source, content)."""
    chunks: list[tuple[str, str]] = []
    if text is not None and str(text).strip():
        chunks.append(("text", str(text)))
    if research_report is not None and str(research_report).strip():
        chunks.append(("report", str(research_report)))
    if isinstance(agents, dict):
        for key, agent in agents.items():
            if not isinstance(agent, dict):
                continue
            for field_name in ("reason", "summary", "evidence"):
                val = agent.get(field_name)
                if val is None:
                    continue
                if isinstance(val, (list, tuple)):
                    joined = " ".join(str(x) for x in val if x is not None)
                    if joined.strip():
                        chunks.append((f"agent:{key}", joined))
                elif str(val).strip():
                    chunks.append((f"agent:{key}", str(val)))
    return chunks


def _extract_numeric_claims(source: str, content: str) -> list[Claim]:
    claims: list[Claim] = []
    seen: set[tuple[float, bool, str]] = set()
    for m in _NUM_RE.finditer(content):
        raw_num = m.group("num").replace(",", "")
        is_pct = bool(m.group("pct"))
        try:
            value = float(raw_num)
        except ValueError:
            continue
        # 跳过无信息数字:纯年份、序号式小整数(无小数且无%)且 < 10 且不是 0
        if not is_pct and "." not in raw_num and value < 10:
            continue
        # 跳过明显的大纯整数年份
        if not is_pct and "." not in raw_num and 1900 <= value <= 2100:
            continue
        # 跳过过大的成交量级以外的离谱整数可在匹配阶段处理
        key = (round(value, 6), is_pct, source)
        if key in seen:
            continue
        seen.add(key)
        raw = m.group(0).strip()
        claims.append(
            Claim(raw=raw, value=value, is_percent=is_pct, status="unverified", source=source)
        )
    return claims


def _ground_claims(claims: list[Claim], facts: list[tuple[str, float, str]]) -> None:
    for claim in claims:
        best_field = ""
        matched = False
        for field_name, fact_val, kind in facts:
            # percent tokens prefer pct facts; bare numbers prefer price then other
            if claim.is_percent and kind not in ("pct", "other"):
                # still allow rsi-like
                pass
            if _matches(claim.value, fact_val, kind, claim.is_percent):
                matched = True
                best_field = field_name
                break
        if matched:
            claim.status = "verified"
            claim.matched_field = best_field
        else:
            # 极大离谱价格(相对事实 close)更应标 unverified;小噪声整数可 skipped
            claim.status = "unverified"


def _check_citations(
    chunks: list[tuple[str, str]],
    evidence_pool: list[Any] | None,
) -> tuple[int, int, list[str]]:
    if not evidence_pool:
        return 0, 0, []
    n_ok = 0
    n_bad = 0
    issues: list[str] = []
    max_n = len(evidence_pool)
    seen_bad: set[int] = set()
    for _src, content in chunks:
        for m in _CITE_RE.finditer(content):
            num = int(m.group(1))
            if 1 <= num <= max_n:
                n_ok += 1
            else:
                n_bad += 1
                if num not in seen_bad:
                    seen_bad.add(num)
                    issues.append(f"证据引用 [{num}] 超出池大小 {max_n}")
    return n_ok, n_bad, issues


def _confidence_cap(n_unverified: int, n_claims: int, n_citation_bad: int) -> Optional[float]:
    if n_claims == 0 and n_citation_bad == 0:
        return None
    if n_unverified == 0 and n_citation_bad == 0:
        return None
    # 未核验越多,上限越低
    ratio = (n_unverified + n_citation_bad * 2) / max(n_claims + n_citation_bad, 1)
    if ratio >= 0.5:
        return 55.0
    if ratio >= 0.25:
        return 70.0
    return 85.0


def validate_citations(
    text: Any = None,
    *,
    stock_data: dict[str, Any] | None = None,
    evidence_pool: list[Any] | None = None,
    agents: dict[str, Any] | None = None,
    research_report: Any = None,
) -> CitationReport:
    """核验文本中的数字与 [n] 引用。永不抛出。"""
    try:
        chunks = _collect_texts(text, agents, research_report)
        facts = _build_fact_table(stock_data)

        claims: list[Claim] = []
        for source, content in chunks:
            claims.extend(_extract_numeric_claims(source, content))

        if facts:
            _ground_claims(claims, facts)
        else:
            for c in claims:
                c.status = "skipped"

        n_verified = sum(1 for c in claims if c.status == "verified")
        n_unverified = sum(1 for c in claims if c.status == "unverified")
        n_claims = len(claims)

        n_cite_ok, n_cite_bad, cite_issues = _check_citations(chunks, evidence_pool)

        if n_claims == 0:
            grounding = 1.0 if n_cite_bad == 0 else max(0.0, 1.0 - 0.15 * n_cite_bad)
        else:
            grounding = n_verified / n_claims
            if n_cite_bad:
                grounding = max(0.0, grounding - 0.1 * min(n_cite_bad, 5))

        issues = list(cite_issues)
        for c in claims:
            if c.status == "unverified":
                issues.append(f"未核验数字 {c.raw} (来源 {c.source})")

        cap = _confidence_cap(n_unverified, n_claims, n_cite_bad)
        status = OK
        if n_unverified > 0 or n_cite_bad > 0 or (n_claims > 0 and grounding < 0.5):
            status = DEGRADED

        return CitationReport(
            status=status,
            n_claims=n_claims,
            n_verified=n_verified,
            n_unverified=n_unverified,
            n_citation_ok=n_cite_ok,
            n_citation_bad=n_cite_bad,
            grounding_score=grounding,
            suggest_confidence_cap=cap,
            claims=claims,
            issues=issues,
            note="" if facts else "无 stock_data 事实表,数字未做字段对齐",
        )
    except Exception as exc:  # noqa: BLE001
        return CitationReport(
            status=DEGRADED,
            note=f"核验降级: {type(exc).__name__}",
            grounding_score=0.0,
            suggest_confidence_cap=50.0,
            issues=[str(exc)],
        )


def format_citation_section(report: CitationReport) -> str:
    if report is None:
        return ""
    lines = [
        "",
        "### 引用与数值核验 (Citation Validator)",
        (
            f"- 状态: {report.status} · 数字 {report.n_verified}/{report.n_claims} 已对齐"
            f" · 证据引用 OK {report.n_citation_ok} / 异常 {report.n_citation_bad}"
        ),
        f"- 可追溯分 grounding_score: {report.grounding_score:.2f}",
    ]
    if report.suggest_confidence_cap is not None:
        lines.append(f"- 建议置信度上限: {report.suggest_confidence_cap:.0f}(存在未核验数字/虚引)")
    if report.n_unverified:
        samples = [c.raw for c in report.claims if c.status == "unverified"][:5]
        lines.append(f"- 未核验样例: {', '.join(samples)}")
    if report.note:
        lines.append(f"- 备注: {report.note}")
    lines.append(f"- 说明: {_DISCLAIMER}")
    lines.append("")
    return "\n".join(lines)
