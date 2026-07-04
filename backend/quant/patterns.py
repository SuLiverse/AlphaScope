"""K 线形态识别 (Candlestick & Chart Pattern Recognition) — v1.9.16

确定性技术形态识别:从 OHLCV 序列里**按规则**检出经典 K 线形态(单/双/三根
蜡烛)与结构信号(跳空 / N 日突破 / 均线金叉死叉 / 双顶双底),把"看图说话"
变成可复核的确定性标注。

设计:
- **纯函数、失败安全、不触网**:坏数据/不足 → 降级返回空形态,绝不抛出
  (对标 ``chip_distribution.py`` / ``walk_forward.py`` 的风格)。
- **可单测**:每个形态是明确的几何/比例规则,给定 bars 必得确定结果。
- **方向只描述形态属性**(看涨/看跌/中性形态),**不预测涨跌**。

合规红线:形态识别**描述历史 K 线结构**,A 股市场中其后续表现并不必然,
**不预测未来、不构成任何投资建议**;报告附免责。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_MIN_BARS = 5
_BREAKOUT_WINDOW = 20  # N 日突破/跌破窗口
_MA_SHORT = 5
_MA_LONG = 20

BULLISH = "bullish"
BEARISH = "bearish"
NEUTRAL = "neutral"

# 形态分类
CANDLE = "candlestick"  # 蜡烛形态
STRUCTURE = "structure"  # 结构/趋势信号

_DISCLAIMER = "形态识别仅描述历史 K 线结构,其后续表现并不必然,不预测未来涨跌、不构成任何投资建议。"


@dataclass
class Pattern:
    name: str
    category: str  # candlestick | structure
    direction: str  # bullish | bearish | neutral
    date: str
    index: int
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "direction": self.direction,
            "date": self.date,
            "index": self.index,
            "detail": self.detail,
        }


@dataclass
class PatternReport:
    status: str  # ok | insufficient
    symbol: str
    bars_used: int
    patterns: list[Pattern]
    counts: dict[str, int] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "symbol": self.symbol,
            "bars_used": self.bars_used,
            "patterns": [p.to_dict() for p in self.patterns],
            "counts": self.counts,
            "note": self.note,
            "disclaimer": _DISCLAIMER,
        }


# ============== 蜡烛几何辅助 ==============


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _o(b: dict) -> float:
    return _f(b.get("open"))


def _c(b: dict) -> float:
    return _f(b.get("close"))


def _h(b: dict) -> float:
    return _f(b.get("high"))


def _l(b: dict) -> float:
    return _f(b.get("low"))


def _body(b: dict) -> float:
    return abs(_c(b) - _o(b))


def _rng(b: dict) -> float:
    return _h(b) - _l(b)


def _upper(b: dict) -> float:
    return _h(b) - max(_o(b), _c(b))


def _lower(b: dict) -> float:
    return min(_o(b), _c(b)) - _l(b)


def _is_bull(b: dict) -> bool:
    return _c(b) > _o(b)


def _is_bear(b: dict) -> bool:
    return _c(b) < _o(b)


def _date(b: dict) -> str:
    return str(b.get("date") or "")


def _sma(values: list[float], period: int) -> list[float]:
    out: list[float] = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(float("nan"))
        else:
            out.append(sum(values[i - period + 1 : i + 1]) / period)
    return out


def _trend(closes: list[float], i: int, window: int = 5) -> str:
    """i 之前 window 根的粗趋势(用于区分锤子线/上吊线等同形异义)。"""
    start = max(0, i - window)
    if i - start < 2:
        return NEUTRAL
    prior = closes[start:i]
    if not prior:
        return NEUTRAL
    first, last = prior[0], prior[-1]
    if last < first * 0.985:
        return BEARISH  # 下跌途中
    if last > first * 1.015:
        return BULLISH  # 上涨途中
    return NEUTRAL


# ============== 单根蜡烛形态 ==============


def _single_bar_patterns(bars: list[dict], closes: list[float], i: int) -> list[Pattern]:
    b = bars[i]
    rng = _rng(b)
    if rng <= 0:
        return []
    body, upper, lower = _body(b), _upper(b), _lower(b)
    out: list[Pattern] = []
    trend = _trend(closes, i)

    # 十字星: 实体极小
    if body <= 0.1 * rng:
        out.append(Pattern("十字星", CANDLE, NEUTRAL, _date(b), i, "开收盘几乎相等,多空僵持"))
        return out  # 十字星与锤子/星互斥

    # 锤子线 / 上吊线: 长下影、短上影、小实体
    if lower >= 2 * body and upper <= body and body <= 0.4 * rng:
        if trend == BEARISH:
            out.append(
                Pattern(
                    "锤子线",
                    CANDLE,
                    BULLISH,
                    _date(b),
                    i,
                    "下跌途中长下影,买盘承接(看涨形态)",
                )
            )
        elif trend == BULLISH:
            out.append(
                Pattern(
                    "上吊线",
                    CANDLE,
                    BEARISH,
                    _date(b),
                    i,
                    "上涨途中长下影,获利抛压(看跌形态)",
                )
            )
        else:
            out.append(Pattern("纺锤/长下影", CANDLE, NEUTRAL, _date(b), i, "长下影线,盘中下探回升"))

    # 流星线 / 倒锤子: 长上影、短下影、小实体
    elif upper >= 2 * body and lower <= body and body <= 0.4 * rng:
        if trend == BULLISH:
            out.append(
                Pattern(
                    "流星线",
                    CANDLE,
                    BEARISH,
                    _date(b),
                    i,
                    "上涨途中长上影,上方抛压(看跌形态)",
                )
            )
        elif trend == BEARISH:
            out.append(
                Pattern(
                    "倒锤子",
                    CANDLE,
                    BULLISH,
                    _date(b),
                    i,
                    "下跌途中长上影,试探反弹(看涨形态)",
                )
            )
        else:
            out.append(Pattern("长上影", CANDLE, NEUTRAL, _date(b), i, "长上影线,盘中冲高回落"))

    return out


# ============== 双根蜡烛形态 ==============


def _two_bar_patterns(bars: list[dict], i: int) -> list[Pattern]:
    if i < 1:
        return []
    prev, cur = bars[i - 1], bars[i]
    out: list[Pattern] = []
    po, pc = _o(prev), _c(prev)
    co, cc = _o(cur), _c(cur)

    # 看涨吞没: 前阴后阳, 后实体吞没前实体
    if _is_bear(prev) and _is_bull(cur) and co <= pc and cc >= po and _body(cur) > _body(prev):
        out.append(
            Pattern(
                "看涨吞没",
                CANDLE,
                BULLISH,
                _date(cur),
                i,
                "阳线实体吞没前阴线,多方反击",
            )
        )
    # 看跌吞没: 前阳后阴
    elif _is_bull(prev) and _is_bear(cur) and co >= pc and cc <= po and _body(cur) > _body(prev):
        out.append(
            Pattern(
                "看跌吞没",
                CANDLE,
                BEARISH,
                _date(cur),
                i,
                "阴线实体吞没前阳线,空方反击",
            )
        )
    # 刺透线: 前阴后阳, 后开盘低于前低、收盘越过前实体中点但低于前开盘
    elif _is_bear(prev) and _is_bull(cur):
        mid = (po + pc) / 2
        if co < _l(prev) and cc > mid and cc < po:
            out.append(
                Pattern(
                    "刺透线",
                    CANDLE,
                    BULLISH,
                    _date(cur),
                    i,
                    "低开高走收复过半失地(看涨)",
                )
            )
    # 乌云盖顶: 前阳后阴, 后高开越过前高、收盘跌破前实体中点但高于前开盘
    if _is_bull(prev) and _is_bear(cur):
        mid = (po + pc) / 2
        if co > _h(prev) and cc < mid and cc > po:
            out.append(
                Pattern(
                    "乌云盖顶",
                    CANDLE,
                    BEARISH,
                    _date(cur),
                    i,
                    "高开低走吞掉过半涨幅(看跌)",
                )
            )

    return out


# ============== 三根蜡烛形态 ==============


def _three_bar_patterns(bars: list[dict], i: int) -> list[Pattern]:
    if i < 2:
        return []
    a, b, c = bars[i - 2], bars[i - 1], bars[i]
    out: list[Pattern] = []
    rng_a = _rng(a)
    rng_c = _rng(c)
    if rng_a <= 0 or rng_c <= 0:
        return out

    star_small = _body(b) <= 0.4 * _body(a) if _body(a) > 0 else False
    mid_a = (_o(a) + _c(a)) / 2

    # 启明星: 大阴 + 小星(跳空低) + 大阳收过首根中点
    if _is_bear(a) and star_small and _is_bull(c) and _c(c) > mid_a and _body(c) >= 0.5 * rng_c:
        out.append(
            Pattern(
                "启明星",
                CANDLE,
                BULLISH,
                _date(c),
                i,
                "底部三根:大阴—小星—大阳,反转看涨",
            )
        )
    # 黄昏星: 大阳 + 小星(跳空高) + 大阴收破首根中点
    if _is_bull(a) and star_small and _is_bear(c) and _c(c) < mid_a and _body(c) >= 0.5 * rng_c:
        out.append(
            Pattern(
                "黄昏星",
                CANDLE,
                BEARISH,
                _date(c),
                i,
                "顶部三根:大阳—小星—大阴,反转看跌",
            )
        )
    # 红三兵: 三连阳, 收盘逐根抬高
    if _is_bull(a) and _is_bull(b) and _is_bull(c) and _c(a) < _c(b) < _c(c):
        out.append(Pattern("红三兵", CANDLE, BULLISH, _date(c), i, "三连阳收盘抬高,多头强势"))
    # 三只乌鸦: 三连阴, 收盘逐根走低
    if _is_bear(a) and _is_bear(b) and _is_bear(c) and _c(a) > _c(b) > _c(c):
        out.append(Pattern("三只乌鸦", CANDLE, BEARISH, _date(c), i, "三连阴收盘走低,空头强势"))

    return out


# ============== 结构 / 趋势信号 ==============


def _structure_patterns(bars: list[dict], closes: list[float], i: int) -> list[Pattern]:
    out: list[Pattern] = []
    cur = bars[i]

    # 跳空缺口
    if i >= 1:
        if _l(cur) > _h(bars[i - 1]):
            out.append(
                Pattern(
                    "向上跳空",
                    STRUCTURE,
                    BULLISH,
                    _date(cur),
                    i,
                    "今日最低高于昨日最高,向上跳空缺口",
                )
            )
        elif _h(cur) < _l(bars[i - 1]):
            out.append(
                Pattern(
                    "向下跳空",
                    STRUCTURE,
                    BEARISH,
                    _date(cur),
                    i,
                    "今日最高低于昨日最低,向下跳空缺口",
                )
            )

    # N 日突破 / 跌破
    if i >= _BREAKOUT_WINDOW:
        window_high = max(_h(bars[j]) for j in range(i - _BREAKOUT_WINDOW, i))
        window_low = min(_l(bars[j]) for j in range(i - _BREAKOUT_WINDOW, i))
        if _c(cur) > window_high:
            out.append(
                Pattern(
                    f"{_BREAKOUT_WINDOW}日新高突破",
                    STRUCTURE,
                    BULLISH,
                    _date(cur),
                    i,
                    f"收盘创近 {_BREAKOUT_WINDOW} 日新高",
                )
            )
        elif _c(cur) < window_low:
            out.append(
                Pattern(
                    f"{_BREAKOUT_WINDOW}日新低跌破",
                    STRUCTURE,
                    BEARISH,
                    _date(cur),
                    i,
                    f"收盘创近 {_BREAKOUT_WINDOW} 日新低",
                )
            )

    return out


def _ma_cross_patterns(bars: list[dict], closes: list[float]) -> list[Pattern]:
    out: list[Pattern] = []
    ma_s = _sma(closes, _MA_SHORT)
    ma_l = _sma(closes, _MA_LONG)
    for i in range(1, len(closes)):
        s0, s1 = ma_s[i - 1], ma_s[i]
        l0, l1 = ma_l[i - 1], ma_l[i]
        if any(v != v for v in (s0, s1, l0, l1)):  # NaN 预热
            continue
        if s0 <= l0 and s1 > l1:
            out.append(
                Pattern(
                    f"MA{_MA_SHORT}/{_MA_LONG}金叉",
                    STRUCTURE,
                    BULLISH,
                    _date(bars[i]),
                    i,
                    "短均线上穿长均线",
                )
            )
        elif s0 >= l0 and s1 < l1:
            out.append(
                Pattern(
                    f"MA{_MA_SHORT}/{_MA_LONG}死叉",
                    STRUCTURE,
                    BEARISH,
                    _date(bars[i]),
                    i,
                    "短均线下穿长均线",
                )
            )
    return out


def _double_top_bottom(bars: list[dict], closes: list[float]) -> list[Pattern]:
    """用局部极值近似双顶/双底(简化, 仅在最近一段内找两个相近峰/谷)。"""
    out: list[Pattern] = []
    n = len(closes)
    if n < 15:
        return out
    # 找局部极大/极小(窗口 3)
    highs = [_h(b) for b in bars]
    lows = [_l(b) for b in bars]
    peaks = [
        i
        for i in range(2, n - 2)
        if highs[i] >= highs[i - 1]
        and highs[i] >= highs[i - 2]
        and highs[i] >= highs[i + 1]
        and highs[i] >= highs[i + 2]
    ]
    troughs = [
        i
        for i in range(2, n - 2)
        if lows[i] <= lows[i - 1] and lows[i] <= lows[i - 2] and lows[i] <= lows[i + 1] and lows[i] <= lows[i + 2]
    ]

    def _last_pair(idxs: list[int], vals: list[float], near: float = 0.03, min_gap: int = 4):
        for a in range(len(idxs) - 1, 0, -1):
            for b in range(a - 1, -1, -1):
                i1, i2 = idxs[b], idxs[a]
                if i2 - i1 < min_gap:
                    continue
                v1, v2 = vals[i1], vals[i2]
                if v1 > 0 and abs(v1 - v2) / v1 <= near:
                    return i1, i2
        return None

    tp = _last_pair(peaks, highs)
    if tp:
        i2 = tp[1]
        out.append(
            Pattern(
                "双顶(M头)",
                STRUCTURE,
                BEARISH,
                _date(bars[i2]),
                i2,
                "近期两个相近高点,顶部承压形态",
            )
        )
    tb = _last_pair(troughs, lows)
    if tb:
        i2 = tb[1]
        out.append(
            Pattern(
                "双底(W底)",
                STRUCTURE,
                BULLISH,
                _date(bars[i2]),
                i2,
                "近期两个相近低点,底部支撑形态",
            )
        )
    return out


# ============== 主入口 ==============


def detect_patterns(bars: list[dict[str, Any]], symbol: str = "", lookback: int = 60) -> PatternReport:
    """从 OHLCV 序列检出蜡烛 + 结构形态。永不抛出。

    Args:
        bars: OHLCV 列表(需含 open/high/low/close, 可含 date/volume)。
        symbol: 标的(透传)。
        lookback: 蜡烛形态只在最近 ``lookback`` 根里逐根扫描(结构形态用全序列)。
    """
    try:
        return _detect(bars or [], symbol, lookback)
    except Exception as exc:  # noqa: BLE001 - 失败安全
        return PatternReport(
            status="insufficient",
            symbol=symbol,
            bars_used=0,
            patterns=[],
            counts={},
            note=f"形态识别降级: {exc}",
        )


def _detect(bars: list[dict], symbol: str, lookback: int) -> PatternReport:
    clean = [b for b in bars if _c(b) > 0]
    clean.sort(key=lambda b: str(b.get("date") or ""))
    n = len(clean)
    if n < _MIN_BARS:
        return PatternReport(
            status="insufficient",
            symbol=symbol,
            bars_used=n,
            patterns=[],
            counts={},
            note=f"样本不足({n} < {_MIN_BARS})",
        )

    closes = [_c(b) for b in clean]
    patterns: list[Pattern] = []

    # 蜡烛形态:最近 lookback 根逐根
    scan_start = max(0, n - max(5, lookback))
    for i in range(scan_start, n):
        patterns.extend(_single_bar_patterns(clean, closes, i))
        patterns.extend(_two_bar_patterns(clean, i))
        patterns.extend(_three_bar_patterns(clean, i))
        patterns.extend(_structure_patterns(clean, closes, i))

    # 全序列结构信号(均线交叉只保留落在扫描窗内的)
    patterns.extend([p for p in _ma_cross_patterns(clean, closes) if p.index >= scan_start])
    patterns.extend(_double_top_bottom(clean, closes))

    # 去重(同日同名)+ 倒序(最近在前)
    seen: set[tuple[str, str]] = set()
    deduped: list[Pattern] = []
    for p in sorted(patterns, key=lambda x: x.index, reverse=True):
        key = (p.date, p.name)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)

    counts = {
        BULLISH: sum(1 for p in deduped if p.direction == BULLISH),
        BEARISH: sum(1 for p in deduped if p.direction == BEARISH),
        NEUTRAL: sum(1 for p in deduped if p.direction == NEUTRAL),
        "total": len(deduped),
    }
    return PatternReport(
        status="ok",
        symbol=symbol,
        bars_used=n,
        patterns=deduped,
        counts=counts,
        note="",
    )
