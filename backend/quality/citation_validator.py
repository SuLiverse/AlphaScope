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
    "引用核验仅检查文本数字/证据编号是否能与本次研究快照对齐,未核验不等于一定虚假,但高置信结论应优先使用可追溯字段。"
)

# 捕获: -0.5 / +1.25% / 1234.56 / 1,234.56 / 58.3
_NUM_RE = re.compile(
    r"(?<![A-Za-z_\d.,])"  # 不跟在标识符或另一个数字内部
    r"(?P<num>[+-]?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+))"
    r"(?P<pct>\s*%)?"
)
_CITE_RE = re.compile(r"\[(\d{1,3})\]")
_DATE_RE = re.compile(
    r"(?<!\d)(?:19|20)\d{2}(?:[-/]\d{1,2}[-/]\d{1,2}|年\d{1,2}月\d{1,2}日?)"
    r"|(?<!\d)(?:19|20)\d{6}(?!\d)"
)
_DIRECT_METADATA_SUFFIX_RE = re.compile(r"^\s*(?:个|条|日|天|周|月|年|次|票|项|席|位|份|家|种|轮|期)(?![A-Za-z])")
_CURRENCY_SUFFIX_RE = re.compile(r"^\s*(?:人民币|美元|港元|亿元|万元|元|块钱|块)")
_CLAUSE_DELIMITERS = "\n\r。！？!?；;，,"
_NEGATIVE_DIRECTION_RE = re.compile(r"下跌|(?<!涨)跌幅|回撤|下降|减少|(?<!涨)跌(?!涨|到|幅)")
_POSITIVE_DIRECTION_RE = re.compile(r"上涨|涨幅|上升|增长|增加|涨(?!跌|到)")

# Numeric tokens are only assessed when their surrounding clause names a
# supported market field.  Metadata is a competing semantic class rather than
# a bag of values, so e.g. confidence=55 cannot verify close=55.
_METADATA_PATTERNS = (
    re.compile(
        r"股票代码|证券代码|标的|(?:平均)?置信度|研究可信度|可信度|完整度|覆盖率|"
        r"共识度|评分|得分|净分|证据数量|证据数|独立来源|来源数|专家席位|席位|"
        r"规则信号|模型调用|预算|费用|花费|耗费|成本(?!价)|\bscore\b|\btoken(?:s)?\b",
        re.IGNORECASE,
    ),
)
_SEMANTIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rsi", re.compile(r"\bRSI\b|相对强弱(?:指数)?", re.IGNORECASE)),
    ("ma5", re.compile(r"\bMA\s*5\b", re.IGNORECASE)),
    ("ma20", re.compile(r"\bMA\s*20\b", re.IGNORECASE)),
    ("ma60", re.compile(r"\bMA\s*60\b", re.IGNORECASE)),
    ("dif", re.compile(r"\bDIF\b", re.IGNORECASE)),
    ("dea", re.compile(r"\bDEA\b", re.IGNORECASE)),
    ("macd", re.compile(r"\bMACD\b", re.IGNORECASE)),
    ("turnover", re.compile(r"换手率|turnover", re.IGNORECASE)),
    ("volatility", re.compile(r"波动率|volatility", re.IGNORECASE)),
    ("vol_ratio", re.compile(r"量比|volume\s*ratio", re.IGNORECASE)),
    ("volume", re.compile(r"成交量|交易量|\bvolume\b", re.IGNORECASE)),
    ("amount", re.compile(r"成交额|交易额|\bturnover\s*amount\b", re.IGNORECASE)),
    ("period_high", re.compile(r"区间(?:最高|高)点|周期(?:最高|高)点|period[_ ]?high", re.IGNORECASE)),
    ("period_low", re.compile(r"区间(?:最低|低)点|周期(?:最低|低)点|period[_ ]?low", re.IGNORECASE)),
    ("period_price", re.compile(r"区间高低点|区间最高/最低|区间高/低", re.IGNORECASE)),
    (
        "price_level",
        re.compile(r"目标价|支撑(?:位|价)?|压力(?:位|价)?|止损(?:位|价)?|突破|跌破|站上|涨到|跌到"),
    ),
    (
        "close",
        re.compile(r"最新价|现价|当前股价|股价|价格|价位|收盘价?|成交价|\b(?:close|price)\b", re.IGNORECASE),
    ),
    (
        "day_change",
        re.compile(
            r"当日(?:涨跌|涨|跌)幅?|今日(?:涨跌|涨|跌)幅?|"
            r"日内(?:涨跌|涨|跌)幅?|单日(?:涨跌|涨|跌)幅?|day[_ ]?change",
            re.IGNORECASE,
        ),
    ),
    (
        "period_change",
        re.compile(
            r"(?:近|过去)\s*\d+\s*(?:日|天|周|月).*?(?:涨跌|涨幅|跌幅|收益)|"
            r"区间涨跌幅?|周期涨跌幅?|累计涨跌幅?|period[_ ]?change",
            re.IGNORECASE,
        ),
    ),
    ("pct", re.compile(r"涨跌幅?|涨幅|跌幅|收益率|回报率|回撤|(?<!必)上涨|下跌|(?<!必)涨(?!到)|跌(?!到)")),
)

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
    """Return ``(field, value, kind)`` rows for supported market facts."""
    data = stock_data if isinstance(stock_data, dict) else {}
    specs: list[tuple[str, str]] = [
        ("close", "price"),
        ("ma5", "ma5"),
        ("ma20", "ma20"),
        ("ma60", "ma60"),
        ("period_high", "period_high"),
        ("period_low", "period_low"),
        ("day_change", "day_change"),
        ("period_change", "period_change"),
        ("change_pct", "change_pct"),
        ("rsi", "rsi"),
        ("turnover", "turnover"),
        ("vol_ratio", "vol_ratio"),
        ("volatility", "volatility"),
        ("volume", "volume"),
        ("total_amount", "amount"),
        ("dif", "dif"),
        ("dea", "dea"),
        ("macd", "macd"),
    ]
    facts: list[tuple[str, float, str]] = []
    for key, kind in specs:
        v = _to_float(data.get(key))
        if v is None:
            continue
        facts.append((key, v, kind))
    return facts


def _matches(value: float, fact: float, kind: str) -> bool:
    if kind in {"day_change", "period_change", "change_pct", "turnover", "volatility"}:
        return abs(value - fact) <= _PCT_ABS or abs(value - fact) / max(abs(fact), 1e-9) <= 0.02
    if kind in {"price", "ma5", "ma20", "ma60", "period_high", "period_low", "amount"}:
        return abs(value - fact) <= max(_PRICE_ABS, abs(fact) * _PRICE_REL)
    # Oscillators, volume and other technical values allow 1% relative error.
    return abs(value - fact) <= max(0.15, abs(fact) * 0.01)


_COMPATIBLE_FACT_KINDS: dict[str, set[str]] = {
    "close": {"price"},
    "price_level": set(),
    "period_price": {"period_high", "period_low"},
    "period_high": {"period_high"},
    "period_low": {"period_low"},
    "ma5": {"ma5"},
    "ma20": {"ma20"},
    "ma60": {"ma60"},
    "day_change": {"day_change", "change_pct"},
    "period_change": {"period_change"},
    "pct": {"day_change", "period_change", "change_pct"},
    "rsi": {"rsi"},
    "turnover": {"turnover"},
    "volatility": {"volatility"},
    "vol_ratio": {"vol_ratio"},
    "volume": {"volume"},
    "amount": {"amount"},
    "dif": {"dif"},
    "dea": {"dea"},
    "macd": {"macd"},
}


@dataclass
class Claim:
    raw: str
    value: float
    is_percent: bool
    status: str  # verified | unverified | skipped
    kind: str = ""
    matched_field: str = ""
    source: str = ""  # report | agent:key

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "value": self.value,
            "is_percent": self.is_percent,
            "status": self.status,
            "kind": self.kind,
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


def _overlaps_match(span: tuple[int, int], matches: list[re.Match[str]]) -> bool:
    start, end = span
    return any(start < match.end() and end > match.start() for match in matches)


def _clause_at(content: str, start: int, end: int) -> tuple[str, int]:
    left = 0
    right = len(content)
    for delimiter in _CLAUSE_DELIMITERS:
        pos = content.rfind(delimiter, 0, start)
        if pos >= 0:
            left = max(left, pos + 1)
        pos = content.find(delimiter, end)
        if pos >= 0:
            right = min(right, pos)
    return content[left:right], left


def _span_distance(left: tuple[int, int], right: tuple[int, int]) -> int:
    if left[1] <= right[0]:
        return right[0] - left[1]
    if right[1] <= left[0]:
        return left[0] - right[1]
    return 0


def _semantic_kind(content: str, match: re.Match[str]) -> str:
    """Infer a supported market field from the nearest label in the clause."""
    start, end = match.span()
    if _DIRECT_METADATA_SUFFIX_RE.match(content[end : end + 10]):
        return ""
    if re.search(r"(?:第|编号|序号)\s*$", content[max(0, start - 8) : start]):
        return ""

    clause, offset = _clause_at(content, start, end)
    number_span = (start - offset, end - offset)
    candidates: list[tuple[int, int, str]] = []
    for pattern in _METADATA_PATTERNS:
        for label in pattern.finditer(clause):
            candidates.append((_span_distance(number_span, label.span()), 0, ""))
    for priority, (kind, pattern) in enumerate(_SEMANTIC_PATTERNS, start=1):
        for label in pattern.finditer(clause):
            candidates.append((_span_distance(number_span, label.span()), priority, kind))
    if not candidates:
        return ""

    distance, _priority, kind = min(candidates)
    # Labels farther than this generally belong to another assertion in a long
    # free-form clause.  Treating the number as metadata is safer than cross-matching.
    return kind if distance <= 24 else ""


def _same_symbol(raw_num: str, stock_symbol: str) -> bool:
    unsigned_num = raw_num.lstrip("+-")
    if "." in unsigned_num or "," in unsigned_num:
        return False
    raw_digits = unsigned_num.lstrip("0") or "0"
    symbol_digits = re.sub(r"\D", "", str(stock_symbol or ""))
    if not symbol_digits:
        return False
    return raw_digits == (symbol_digits.lstrip("0") or "0")


def _direction_for_claim(content: str, match: re.Match[str]) -> int:
    """Return the nearest explicit percentage direction: ``-1``, ``1`` or ``0``."""
    start, end = match.span()
    clause, offset = _clause_at(content, start, end)
    number_span = (start - offset, end - offset)
    candidates: list[tuple[int, int]] = []
    for direction, pattern in ((-1, _NEGATIVE_DIRECTION_RE), (1, _POSITIVE_DIRECTION_RE)):
        for label in pattern.finditer(clause):
            candidates.append((_span_distance(number_span, label.span()), direction))
    if not candidates:
        return 0
    distance, direction = min(candidates, key=lambda item: item[0])
    return direction if distance <= 16 else 0


def _extract_numeric_claims(source: str, content: str, stock_symbol: str = "") -> list[Claim]:
    claims: list[Claim] = []
    seen: set[tuple[float, bool, str, str]] = set()
    date_matches = list(_DATE_RE.finditer(content))
    citation_matches = list(_CITE_RE.finditer(content))
    for m in _NUM_RE.finditer(content):
        raw_num = m.group("num").replace(",", "")
        is_pct = bool(m.group("pct"))
        try:
            value = float(raw_num)
        except ValueError:
            continue
        if _overlaps_match(m.span(), date_matches) or _overlaps_match(m.span(), citation_matches):
            continue
        if _same_symbol(raw_num, stock_symbol):
            continue
        # 跳过明显的大纯整数年份
        if not is_pct and "." not in raw_num and 1900 <= abs(value) <= 2100:
            continue
        kind = _semantic_kind(content, m)
        if not kind:
            continue

        direction = _direction_for_claim(content, m) if kind in {"day_change", "period_change", "pct"} else 0
        has_explicit_sign = raw_num.startswith(("+", "-"))
        if direction and has_explicit_sign and (value > 0) != (direction > 0):
            kind = f"invalid_direction_{kind}"
        elif direction and not has_explicit_sign:
            value = abs(value) * direction

        has_currency_unit = bool(_CURRENCY_SUFFIX_RE.match(content[m.end() : m.end() + 12]))
        if has_currency_unit and kind in {"day_change", "period_change", "pct", "turnover", "volatility"}:
            kind = f"invalid_currency_{kind}"
        # A percent-marked price cannot verify a price field even if the value
        # happens to be identical.  Preserve it as an assessable bad claim.
        if is_pct and kind in {
            "close",
            "price_level",
            "period_price",
            "period_high",
            "period_low",
            "ma5",
            "ma20",
            "ma60",
            "volume",
            "amount",
            "vol_ratio",
            "rsi",
            "dif",
            "dea",
            "macd",
        }:
            kind = f"invalid_percent_{kind}"
        key = (round(value, 6), is_pct, source, kind)
        if key in seen:
            continue
        seen.add(key)
        raw = m.group(0).strip()
        claims.append(
            Claim(
                raw=raw,
                value=value,
                is_percent=is_pct,
                status="unverified",
                kind=kind,
                source=source,
            )
        )
    return claims


def _ground_claims(claims: list[Claim], facts: list[tuple[str, float, str]]) -> None:
    for claim in claims:
        best_field = ""
        matched = False
        compatible_kinds = _COMPATIBLE_FACT_KINDS.get(claim.kind, set())
        for field_name, fact_val, kind in facts:
            if kind not in compatible_kinds:
                continue
            if _matches(claim.value, fact_val, kind):
                matched = True
                best_field = field_name
                break
        if matched:
            claim.status = "verified"
            claim.matched_field = best_field
        else:
            claim.status = "unverified"


def _check_citations(
    chunks: list[tuple[str, str]],
    evidence_pool: list[Any] | None,
) -> tuple[int, int, list[str]]:
    n_ok = 0
    n_bad = 0
    issues: list[str] = []
    max_n = len(evidence_pool or [])
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
                    if max_n == 0:
                        issues.append(f"证据引用 [{num}] 无可用证据池")
                    else:
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
        stock_symbol = str((stock_data or {}).get("symbol") or "")

        claims: list[Claim] = []
        for source, content in chunks:
            claims.extend(_extract_numeric_claims(source, content, stock_symbol=stock_symbol))

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
