"""缠论结构标注 — 合并 K → 分型 → 笔 → 中枢 → MACD 面积背驰。

确定性、失败安全、不触网。描述历史走势几何, 不预测、不构成买卖建议。

相对买卖点工具的修正:
- 中枢必须至少 **三段重叠**(离开后连续三笔有公共区间)。两笔有交集不算中枢。
- 一二三类点只作为可选标注字段 ``signals``, 顶层不输出 action=买入。
- 背驰标在笔上, 不把面积比包装成「买入把握」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_MIN_BARS = 10
_STROKE_MIN_GAP = 4  # 分型间合并 K 索引差

OK = "ok"
INSUFFICIENT = "insufficient"

_DISCLAIMER = "描述历史走势结构，不预测、不构成买卖建议。"


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class Fractal:
    index: int
    type: str  # top | bottom
    price: float
    date: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "type": self.type,
            "price": round(self.price, 4),
            "date": self.date,
        }


@dataclass
class Stroke:
    direction: str  # up | down
    start_price: float
    end_price: float
    start_date: str
    end_date: str
    start_idx: int
    end_idx: int
    start_merged: int
    end_merged: int
    macd_area: float = 0.0
    has_divergence: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "start_price": round(self.start_price, 4),
            "end_price": round(self.end_price, 4),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "macd_area": round(self.macd_area, 4),
            "has_divergence": self.has_divergence,
        }


@dataclass
class Zhongshu:
    start_date: str
    end_date: str
    zg: float
    zd: float
    zz: float
    stroke_start_idx: int
    stroke_end_idx: int
    is_broken: bool = False
    break_direction: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "zg": round(self.zg, 4),
            "zd": round(self.zd, 4),
            "zz": round(self.zz, 4),
            "stroke_start_idx": self.stroke_start_idx,
            "stroke_end_idx": self.stroke_end_idx,
            "is_broken": self.is_broken,
            "break_direction": self.break_direction,
        }


@dataclass
class ChanlunSignal:
    type: str  # buy1/buy2/buy3/sell1/sell2/sell3 — 标注, 不是下单指令
    date: str
    price: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "date": self.date,
            "price": round(self.price, 4),
            "note": self.note,
        }


@dataclass
class ChanlunReport:
    status: str  # ok | insufficient
    symbol: str
    bars_used: int
    fractals: list[Fractal] = field(default_factory=list)
    strokes: list[Stroke] = field(default_factory=list)
    zhongshus: list[Zhongshu] = field(default_factory=list)
    divergences: list[dict[str, Any]] = field(default_factory=list)
    signals: list[ChanlunSignal] = field(default_factory=list)
    note: str = ""
    disclaimer: str = _DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "bars_used": self.bars_used,
            "fractals": [f.to_dict() for f in self.fractals],
            "strokes": [s.to_dict() for s in self.strokes],
            "zhongshus": [z.to_dict() for z in self.zhongshus],
            "divergences": list(self.divergences),
            "signals": [s.to_dict() for s in self.signals],
            "note": self.note,
            "disclaimer": self.disclaimer,
        }


@dataclass
class _Merged:
    date_start: str
    date_end: str
    high: float
    low: float
    direction: int
    raw_count: int
    start_raw: int
    end_raw: int


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _f(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if out == out else default
    except (TypeError, ValueError):
        return default


def _date(bar: dict) -> str:
    return str(bar.get("date") or "")


def _clean_bars(bars: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Return sorted valid OHLC bars, or None if dirty / unusable."""
    clean: list[dict[str, Any]] = []
    for b in bars or []:
        if not isinstance(b, dict):
            return None
        o, h, lo, c = _f(b.get("open")), _f(b.get("high")), _f(b.get("low")), _f(b.get("close"))
        if c <= 0 or h <= 0 or lo <= 0:
            return None
        if h < lo or h < max(o, c) or lo > min(o, c):
            return None
        clean.append(b)
    clean.sort(key=lambda b: _date(b))
    return clean


def merge_klines(bars: list[dict[str, Any]]) -> list[_Merged]:
    """Inclusion merge. Direction is inherited; extrema follow the current direction."""
    if not bars:
        return []
    highs = [_f(b.get("high")) for b in bars]
    lows = [_f(b.get("low")) for b in bars]
    dates = [_date(b) for b in bars]
    cur = _Merged(dates[0], dates[0], highs[0], lows[0], 0, 1, 0, 0)
    merged: list[_Merged] = []
    for i in range(1, len(bars)):
        h, lo = highs[i], lows[i]
        contained = (h <= cur.high and lo >= cur.low) or (h >= cur.high and lo <= cur.low)
        if not contained:
            merged.append(cur)
            direction = 1 if h > cur.high else -1
            cur = _Merged(dates[i], dates[i], h, lo, direction, 1, i, i)
        else:
            if cur.direction == 1:
                new_high, new_low = max(h, cur.high), max(lo, cur.low)
            elif cur.direction == -1:
                new_high, new_low = min(h, cur.high), min(lo, cur.low)
            else:
                new_high, new_low = max(h, cur.high), min(lo, cur.low)
            cur = _Merged(
                cur.date_start,
                dates[i],
                new_high,
                new_low,
                cur.direction,
                cur.raw_count + 1,
                cur.start_raw,
                i,
            )
    merged.append(cur)
    return merged


def find_fractals(merged: list[_Merged]) -> list[Fractal]:
    fractals: list[Fractal] = []
    n = len(merged)
    for i in range(1, n - 1):
        left, cur, right = merged[i - 1], merged[i], merged[i + 1]
        if cur.high > left.high and cur.high > right.high:
            fractals.append(Fractal(i, "top", cur.high, cur.date_end))
        elif cur.low < left.low and cur.low < right.low:
            fractals.append(Fractal(i, "bottom", cur.low, cur.date_end))
    return fractals


def find_strokes(fractals: list[Fractal], merged: list[_Merged]) -> list[Stroke]:
    """Build strokes. Opposite-type fractals close a stroke only if merged-index gap ≥ 4."""
    strokes: list[Stroke] = []
    n = len(fractals)
    if n == 0:
        return strokes

    start = fractals[0]
    start_pos = 0
    direction = "down" if start.type == "top" else "up"
    end: Fractal | None = None
    end_pos = 0
    j = 1
    while j < n:
        f = fractals[j]
        if f.type == start.type:
            if end is not None:
                strokes.append(_make_stroke(direction, start, end, start_pos, end_pos, merged))
                start = end
                start_pos = end_pos
                direction = "up" if direction == "down" else "down"
                end = None
            else:
                more_extreme = (direction == "down" and f.price > start.price) or (
                    direction == "up" and f.price < start.price
                )
                if more_extreme:
                    start = f
                    start_pos = j
                j += 1
        else:
            if f.index - start.index >= _STROKE_MIN_GAP:
                end = f
                end_pos = j
            j += 1

    if end is not None:
        strokes.append(_make_stroke(direction, start, end, start_pos, end_pos, merged))
    return strokes


def _make_stroke(
    direction: str,
    start: Fractal,
    end: Fractal,
    start_pos: int,
    end_pos: int,
    merged: list[_Merged],
) -> Stroke:
    return Stroke(
        direction=direction,
        start_price=start.price,
        end_price=end.price,
        start_date=start.date,
        end_date=end.date,
        start_idx=start_pos,
        end_idx=end_pos,
        start_merged=start.index,
        end_merged=end.index,
    )


def _stroke_range(s: Stroke) -> tuple[float, float]:
    return min(s.start_price, s.end_price), max(s.start_price, s.end_price)


def find_zhongshus(strokes: list[Stroke]) -> list[Zhongshu]:
    """Zhongshu = overlap of **at least three** consecutive strokes.

    Two-stroke overlap is deliberately rejected (the trend-tool shortcut).
    After a 3-stroke core forms, later strokes may extend it while they still
    overlap the current [zd, zg].
    """
    zhongshus: list[Zhongshu] = []
    n = len(strokes)
    i = 0
    while i + 2 < n:
        ranges = [_stroke_range(strokes[j]) for j in range(i, i + 3)]
        zd = max(r[0] for r in ranges)
        zg = min(r[1] for r in ranges)
        if zd < zg:
            end = i + 2
            while end + 1 < n:
                lo, hi = _stroke_range(strokes[end + 1])
                nzd, nzg = max(zd, lo), min(zg, hi)
                if nzd < nzg:
                    zd, zg = nzd, nzg
                    end += 1
                else:
                    break
            zhongshus.append(
                Zhongshu(
                    start_date=strokes[i].start_date,
                    end_date=strokes[end].end_date,
                    zg=zg,
                    zd=zd,
                    zz=(zg + zd) / 2.0,
                    stroke_start_idx=i,
                    stroke_end_idx=end,
                )
            )
            i = end + 1
        else:
            i += 1

    for z in zhongshus:
        for s in strokes[z.stroke_end_idx + 1 :]:
            if s.direction == "up" and s.end_price > z.zg:
                z.is_broken = True
                z.break_direction = "up"
                z.end_date = s.start_date
                break
            if s.direction == "down" and s.end_price < z.zd:
                z.is_broken = True
                z.break_direction = "down"
                z.end_date = s.start_date
                break
    return zhongshus


def _macd_hist(closes: list[float]) -> list[float]:
    """MACD histogram using the project EMA (same as indicators.calc_macd)."""
    if not closes:
        return []

    def _ema(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        out = [values[0]]
        mult = 2.0 / (period + 1)
        for i in range(1, len(values)):
            out.append(values[i] * mult + out[-1] * (1 - mult))
        return out

    dif = [a - b for a, b in zip(_ema(closes, 12), _ema(closes, 26))]
    dea = _ema(dif, 9)
    return [(d - e) * 2.0 for d, e in zip(dif, dea)]


def annotate_divergence(strokes: list[Stroke], bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """MACD-area decay + new price extreme, marked on the stroke. No conviction score."""
    dates = [_date(b) for b in bars]
    date_to_idx = {d: i for i, d in enumerate(dates)}
    hist = _macd_hist([_f(b.get("close")) for b in bars])
    divergences: list[dict[str, Any]] = []

    for st in strokes:
        si, ei = date_to_idx.get(st.start_date), date_to_idx.get(st.end_date)
        if si is None or ei is None or si > ei:
            st.macd_area = 0.0
            st.has_divergence = False
            continue
        st.macd_area = sum(abs(x) for x in hist[si : ei + 1])

    for i, st in enumerate(strokes):
        prev = None
        for j in range(i - 1, -1, -1):
            if strokes[j].direction == st.direction:
                prev = strokes[j]
                break
        if prev is None:
            st.has_divergence = False
            continue
        area_less = st.macd_area < prev.macd_area
        new_extreme = (st.end_price < prev.end_price) if st.direction == "down" else (st.end_price > prev.end_price)
        st.has_divergence = bool(area_less and new_extreme)
        if st.has_divergence:
            divergences.append(
                {
                    "stroke_idx": i,
                    "direction": st.direction,
                    "date": st.end_date,
                    "price": round(st.end_price, 4),
                    "macd_area": round(st.macd_area, 4),
                    "prev_macd_area": round(prev.macd_area, 4),
                }
            )
    return divergences


def annotate_structure_points(strokes: list[Stroke], zhongshus: list[Zhongshu]) -> list[ChanlunSignal]:
    """Optional type-1/2/3 annotations. These are labels, not orders."""
    out: list[ChanlunSignal] = []
    for i, st in enumerate(strokes):
        if not st.has_divergence:
            continue
        if st.direction == "down":
            out.append(
                ChanlunSignal(
                    "buy1",
                    st.end_date,
                    st.end_price,
                    "底背驰标注: 本笔 MACD 面积小于同向前笔且价格创新低",
                )
            )
        else:
            out.append(
                ChanlunSignal(
                    "sell1",
                    st.end_date,
                    st.end_price,
                    "顶背驰标注: 本笔 MACD 面积小于同向前笔且价格创新高",
                )
            )
        nxt_i = i + 2
        if nxt_i < len(strokes):
            nxt = strokes[nxt_i]
            if st.direction == "down" and nxt.direction == "down" and nxt.end_price > st.end_price:
                out.append(
                    ChanlunSignal(
                        "buy2",
                        nxt.end_date,
                        nxt.end_price,
                        f"一类标注后回落未破前低 {st.end_price:.2f}",
                    )
                )
            elif st.direction == "up" and nxt.direction == "up" and nxt.end_price < st.end_price:
                out.append(
                    ChanlunSignal(
                        "sell2",
                        nxt.end_date,
                        nxt.end_price,
                        f"一类标注后反弹未破前高 {st.end_price:.2f}",
                    )
                )

    for z in zhongshus:
        if not z.is_broken:
            continue
        recess_idx = z.stroke_end_idx + 2
        if recess_idx >= len(strokes):
            continue
        retro = strokes[recess_idx]
        if z.break_direction == "up" and retro.direction == "down" and retro.end_price > z.zg:
            out.append(
                ChanlunSignal(
                    "buy3",
                    retro.end_date,
                    retro.end_price,
                    f"中枢[{z.zd:.2f}-{z.zg:.2f}]向上离开后回抽仍在上沿之上",
                )
            )
        elif z.break_direction == "down" and retro.direction == "up" and retro.end_price < z.zd:
            out.append(
                ChanlunSignal(
                    "sell3",
                    retro.end_date,
                    retro.end_price,
                    f"中枢[{z.zd:.2f}-{z.zg:.2f}]向下离开后回抽仍在下沿之下",
                )
            )
    return out


def format_chanlun_section(report: ChanlunReport) -> str:
    """Plain-text geometry block for the Chanlun expert brief. Fail-closed."""
    if report.status != OK:
        return ""
    lines = ["【缠论结构标注】"]
    if report.zhongshus:
        for z in report.zhongshus[-3:]:
            brk = "未突破"
            if z.is_broken:
                brk = "已向上离开" if z.break_direction == "up" else "已向下离开"
            lines.append(f"- 中枢 {z.start_date}..{z.end_date} [{z.zd:.2f}-{z.zg:.2f}]（{brk}）")
    else:
        lines.append("- 中枢: 无(三段重叠未形成)")
    if report.strokes:
        last = report.strokes[-1]
        cn = "向上" if last.direction == "up" else "向下"
        lines.append(f"- 最近笔: {cn} {last.start_price:.2f} → {last.end_price:.2f}（{last.end_date}）")
    else:
        lines.append("- 最近笔: 无")
    if report.divergences:
        last_d = report.divergences[-1]
        kind = "顶背驰" if last_d.get("direction") == "up" else "底背驰"
        lines.append(f"- 背驰: 有（最近 {kind} @ {last_d.get('date', '')}）")
    else:
        lines.append("- 背驰: 无")
    lines.append("- 说明: 以上为历史走势几何标注，不预测、不构成买卖建议。无几何结构时不得编造。")
    return "\n".join(lines)


def _insufficient(symbol: str, bars_used: int, note: str) -> ChanlunReport:
    return ChanlunReport(
        status=INSUFFICIENT,
        symbol=symbol,
        bars_used=bars_used,
        note=note,
        disclaimer=_DISCLAIMER,
    )


def analyze_chanlun(bars: list[dict], symbol: str = "") -> ChanlunReport:
    """Annotate Chanlun geometry. Never raises."""
    try:
        return _analyze(bars or [], symbol)
    except Exception as exc:  # noqa: BLE001 - fail-safe
        return _insufficient(symbol, 0, f"缠论结构降级: {exc}")


def _analyze(bars: list[dict], symbol: str) -> ChanlunReport:
    clean = _clean_bars(bars)
    if clean is None:
        return _insufficient(symbol, 0, "脏 OHLC")
    n = len(clean)
    if n < _MIN_BARS:
        return _insufficient(symbol, n, f"样本不足({n} < {_MIN_BARS})")

    merged = merge_klines(clean)
    fractals = find_fractals(merged)
    strokes = find_strokes(fractals, merged)
    zhongshus = find_zhongshus(strokes)
    divergences = annotate_divergence(strokes, clean)
    signals = annotate_structure_points(strokes, zhongshus)
    return ChanlunReport(
        status=OK,
        symbol=symbol,
        bars_used=n,
        fractals=fractals,
        strokes=strokes,
        zhongshus=zhongshus,
        divergences=divergences,
        signals=signals,
        note="",
        disclaimer=_DISCLAIMER,
    )
