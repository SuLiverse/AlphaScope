"""筹码分布(成本分布)— 换手率扩散模型,纯确定性、不触网。

A 股「筹码分布」描述的是:当前持仓者的**持仓成本**在各价位上的分布。它由历史
逐日成交「扩散」而来——每天有一部分筹码按当日换手率换手(老筹码按 1−t 衰减、新
筹码 t 按当日价格区间的三角分布铺开),累积到今天即得到成本分布。

由此可读出:
* **获利盘比例**:成本低于现价的筹码占比(这些持有者账面浮盈)。
* **平均成本**:全部筹码的加权平均持仓价。
* **筹码集中度**:包住 70% / 90% 筹码的最窄价格带宽度(越窄越集中)。
* **上/下方筹码密集价**:现价上方/下方筹码最密的价位(成本聚集处)。

诚实说明:
* 优先用每根 K 线自带的真实**换手率**;缺失时退回「量能代理」(按相对成交量估算
  换手),并在结果里标 `model=volume_proxy`,不冒充真实换手。
* 失败安全:数据不足时返回 `status=insufficient` 的中性结果而非抛错。

合规:筹码分布是对**历史成交分布的描述性建模**,不是价格预测、不构成投资建议。
「密集价」只表示成本聚集,不等于价格目标(不预测 / 不荐股 / 不承诺收益)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_PRICE_LEVELS = 100  # 价位离散桶数
_MIN_BARS = 20  # 少于此根 K 线则样本不足
# 量能代理:在平均成交量处假设的典型 A 股换手率(无真实换手时使用)
_PROXY_BASE_TURNOVER = 0.08
_PROXY_MIN, _PROXY_MAX = 0.01, 0.5
_TURNOVER_MIN, _TURNOVER_MAX = 0.001, 1.0

OK = "ok"
INSUFFICIENT = "insufficient"

MODEL_TURNOVER = "turnover"
MODEL_VOLUME_PROXY = "volume_proxy"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------


@dataclass
class ChipDistribution:
    """成本分布结果。"""

    symbol: str
    status: str  # ok | insufficient
    model: str  # turnover | volume_proxy
    current_price: float
    avg_cost: float
    profit_ratio: float  # 获利盘 0-100 %
    concentration_70: float  # 70% 筹码带宽 / 平均成本,0-100 %(越小越集中)
    concentration_90: float
    range_70_low: float
    range_70_high: float
    range_90_low: float
    range_90_high: float
    support_price: float  # 现价下方筹码密集价(成本聚集,非价格目标)
    resistance_price: float  # 现价上方筹码密集价
    bars_used: int
    levels: list[dict[str, float]] = field(default_factory=list)  # [{price, pct}]
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "status": self.status,
            "model": self.model,
            "current_price": self.current_price,
            "avg_cost": self.avg_cost,
            "profit_ratio": self.profit_ratio,
            "concentration_70": self.concentration_70,
            "concentration_90": self.concentration_90,
            "range_70_low": self.range_70_low,
            "range_70_high": self.range_70_high,
            "range_90_low": self.range_90_low,
            "range_90_high": self.range_90_high,
            "support_price": self.support_price,
            "resistance_price": self.resistance_price,
            "bars_used": self.bars_used,
            "levels": self.levels,
            "note": self.note,
            "disclaimer": (
                "筹码分布基于历史成交的扩散建模,描述持仓成本结构,"
                "不预测价格、不构成投资建议;「密集价」表示成本聚集而非价格目标。"
            ),
        }


# ---------------------------------------------------------------------------
# Internals (pure)
# ---------------------------------------------------------------------------


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if out == out else default  # NaN guard
    except (TypeError, ValueError):
        return default


def _normalize_turnover(raw: float) -> float:
    """把换手率归一到 [0,1] 分数。akshare 换手率以百分数计(如 2.35 = 2.35%)。"""
    if raw <= 0:
        return 0.0
    t = raw / 100.0 if raw > 1.5 else raw  # >1.5 视为百分数
    return max(_TURNOVER_MIN, min(_TURNOVER_MAX, t))


def _day_turnover(bar: dict[str, Any], avg_volume: float) -> tuple[float, bool]:
    """返回 (当日换手分数, 是否来自真实换手率)。"""
    real = _normalize_turnover(_to_float(bar.get("turnover")))
    if real > 0:
        return real, True
    # 量能代理:相对平均成交量缩放到典型换手
    vol = _to_float(bar.get("volume"))
    if avg_volume > 0 and vol > 0:
        proxy = _PROXY_BASE_TURNOVER * vol / avg_volume
        return max(_PROXY_MIN, min(_PROXY_MAX, proxy)), False
    return _PROXY_MIN, False


def _triangular_day_weights(low: float, high: float, close: float, edges: list[float], n: int) -> list[float]:
    """把当日一份筹码按三角分布(峰在均价)铺到价位桶,返回长度 n、和为 1 的权重。"""
    weights = [0.0] * n
    if high <= low:
        idx = _bucket_index(close, edges, n)
        weights[idx] = 1.0
        return weights
    peak = max(low, min(high, (high + low + 2.0 * close) / 4.0))
    total = 0.0
    for i in range(n):
        center = (edges[i] + edges[i + 1]) / 2.0
        if center < low or center > high:
            continue
        # 三角:low→peak 线性升,peak→high 线性降
        if center <= peak:
            w = (center - low) / (peak - low) if peak > low else 1.0
        else:
            w = (high - center) / (high - peak) if high > peak else 1.0
        w = max(0.0, w)
        weights[i] = w
        total += w
    if total <= 0:
        idx = _bucket_index(close, edges, n)
        weights[idx] = 1.0
        return weights
    return [w / total for w in weights]


def _bucket_index(price: float, edges: list[float], n: int) -> int:
    lo, hi = edges[0], edges[-1]
    if price <= lo:
        return 0
    if price >= hi:
        return n - 1
    span = hi - lo
    idx = int((price - lo) / span * n)
    return max(0, min(n - 1, idx))


def _band_for_mass(chips: list[float], centers: list[float], target: float) -> tuple[float, float]:
    """找包住 target(如 0.9)质量的最窄连续价格带,返回 (low, high)。"""
    n = len(chips)
    total = sum(chips)
    if total <= 0:
        return centers[0], centers[-1]
    target_mass = target * total
    best_lo, best_hi, best_width = 0, n - 1, float("inf")
    left = 0
    running = 0.0
    for right in range(n):
        running += chips[right]
        while running - chips[left] >= target_mass and left < right:
            running -= chips[left]
            left += 1
        if running >= target_mass:
            width = centers[right] - centers[left]
            if width < best_width:
                best_width = width
                best_lo, best_hi = left, right
    return centers[best_lo], centers[best_hi]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def compute_chip_distribution(
    bars: list[dict[str, Any]],
    symbol: str = "",
    price_levels: int = _PRICE_LEVELS,
    current_price: float | None = None,
) -> ChipDistribution:
    """计算筹码(成本)分布。

    Args:
        bars: OHLCV(+可选 turnover/volume)历史,按日期升序最佳(内部会排序)。
        symbol: 标的标签。
        price_levels: 价位离散桶数(默认 100)。
        current_price: 现价;缺省用最后一根 close。

    Returns:
        ChipDistribution。数据不足时 status=insufficient,绝不抛错。
    """
    n = max(20, min(400, int(price_levels) if price_levels else _PRICE_LEVELS))

    rows = sorted(
        (b for b in (bars or []) if _to_float(b.get("close")) > 0),
        key=lambda b: str(b.get("date", "")),
    )
    if len(rows) < _MIN_BARS:
        return ChipDistribution(
            symbol=symbol,
            status=INSUFFICIENT,
            model=MODEL_VOLUME_PROXY,
            current_price=current_price or (_to_float(rows[-1].get("close")) if rows else 0.0),
            avg_cost=0.0,
            profit_ratio=0.0,
            concentration_70=0.0,
            concentration_90=0.0,
            range_70_low=0.0,
            range_70_high=0.0,
            range_90_low=0.0,
            range_90_high=0.0,
            support_price=0.0,
            resistance_price=0.0,
            bars_used=len(rows),
            levels=[],
            note=f"历史不足以建模筹码分布:需≥{_MIN_BARS} 根 K 线,当前 {len(rows)} 根。",
        )

    lows = [_to_float(b.get("low") or b.get("close")) for b in rows]
    highs = [_to_float(b.get("high") or b.get("close")) for b in rows]
    p_min = min(lows)
    p_max = max(highs)
    if p_max <= p_min:
        p_max = p_min * 1.01 + 0.01  # 退化保护

    edges = [p_min + (p_max - p_min) * i / n for i in range(n + 1)]
    centers = [(edges[i] + edges[i + 1]) / 2.0 for i in range(n)]

    volumes = [_to_float(b.get("volume")) for b in rows]
    nonzero_vol = [v for v in volumes if v > 0]
    avg_volume = sum(nonzero_vol) / len(nonzero_vol) if nonzero_vol else 0.0

    chips = [0.0] * n
    any_real_turnover = False
    for b in rows:
        low = _to_float(b.get("low") or b.get("close"))
        high = _to_float(b.get("high") or b.get("close"))
        close = _to_float(b.get("close"))
        t, is_real = _day_turnover(b, avg_volume)
        any_real_turnover = any_real_turnover or is_real
        day_w = _triangular_day_weights(low, high, close, edges, n)
        # 扩散:老筹码衰减 (1−t),新筹码 t 份按当日三角分布加入 → 总量守恒于 1
        for i in range(n):
            chips[i] = chips[i] * (1.0 - t) + t * day_w[i]

    total = sum(chips)
    if total <= 0:
        # 理论上不会发生(每天都会加入 t>0 的筹码),兜底返回不足
        return ChipDistribution(
            symbol=symbol,
            status=INSUFFICIENT,
            model=MODEL_VOLUME_PROXY,
            current_price=current_price or _to_float(rows[-1].get("close")),
            avg_cost=0.0,
            profit_ratio=0.0,
            concentration_70=0.0,
            concentration_90=0.0,
            range_70_low=0.0,
            range_70_high=0.0,
            range_90_low=0.0,
            range_90_high=0.0,
            support_price=0.0,
            resistance_price=0.0,
            bars_used=len(rows),
            levels=[],
            note="筹码质量为空,无法分布。",
        )
    chips = [c / total for c in chips]

    cur = current_price if (current_price and current_price > 0) else _to_float(rows[-1].get("close"))
    avg_cost = sum(centers[i] * chips[i] for i in range(n))
    profit_ratio = sum(chips[i] for i in range(n) if centers[i] <= cur) * 100.0

    r70_lo, r70_hi = _band_for_mass(chips, centers, 0.70)
    r90_lo, r90_hi = _band_for_mass(chips, centers, 0.90)
    conc_70 = (r70_hi - r70_lo) / avg_cost * 100.0 if avg_cost > 0 else 0.0
    conc_90 = (r90_hi - r90_lo) / avg_cost * 100.0 if avg_cost > 0 else 0.0

    # 上/下方筹码密集价:现价两侧筹码最密的桶(成本聚集,非价格目标)
    below = [(chips[i], centers[i]) for i in range(n) if centers[i] < cur]
    above = [(chips[i], centers[i]) for i in range(n) if centers[i] > cur]
    support_price = max(below, key=lambda x: x[0])[1] if below else 0.0
    resistance_price = max(above, key=lambda x: x[0])[1] if above else 0.0

    # 输出非零价位(压缩载荷),百分比保留两位
    levels = [{"price": round(centers[i], 3), "pct": round(chips[i] * 100.0, 4)} for i in range(n) if chips[i] > 1e-6]

    return ChipDistribution(
        symbol=symbol,
        status=OK,
        model=MODEL_TURNOVER if any_real_turnover else MODEL_VOLUME_PROXY,
        current_price=round(cur, 3),
        avg_cost=round(avg_cost, 3),
        profit_ratio=round(profit_ratio, 2),
        concentration_70=round(conc_70, 2),
        concentration_90=round(conc_90, 2),
        range_70_low=round(r70_lo, 3),
        range_70_high=round(r70_hi, 3),
        range_90_low=round(r90_lo, 3),
        range_90_high=round(r90_hi, 3),
        support_price=round(support_price, 3),
        resistance_price=round(resistance_price, 3),
        bars_used=len(rows),
        levels=levels,
        note=(
            "使用真实换手率建模。" if any_real_turnover else "无真实换手率,使用量能代理估算换手(model=volume_proxy)。"
        ),
    )
