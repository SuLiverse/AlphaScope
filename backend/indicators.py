"""技术指标计算引擎 — 纯函数，输入 price_bars，输出带指标的数据"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ============== 工具函数 ==============


def _closes(bars: list[dict]) -> list[float]:
    return [b.get("close", 0) for b in bars]


def _highs(bars: list[dict]) -> list[float]:
    return [b.get("high", 0) for b in bars]


def _lows(bars: list[dict]) -> list[float]:
    return [b.get("low", 0) for b in bars]


def _volumes(bars: list[dict]) -> list[float]:
    return [b.get("volume", 0) for b in bars]


def _sma(values: list[float], period: int) -> list[float]:
    """简单移动平均"""
    result = []
    for i in range(len(values)):
        if i < period - 1:
            result.append(0.0)
        else:
            window = values[i - period + 1 : i + 1]
            result.append(sum(window) / period)
    return result


def _ema(values: list[float], period: int) -> list[float]:
    """指数移动平均"""
    if not values:
        return []
    result = [0.0] * len(values)
    multiplier = 2.0 / (period + 1)
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = values[i] * multiplier + result[i - 1] * (1 - multiplier)
    return result


# ============== 均线 ==============


def calc_ma(bars: list[dict], periods: list[int] | None = None) -> list[dict]:
    """计算简单移动均线。"""
    if periods is None:
        periods = [5, 10, 20, 60]
    closes = _closes(bars)
    ma_data = {}
    for p in periods:
        ma_data[f"ma{p}"] = _sma(closes, p)

    result = []
    for i, bar in enumerate(bars):
        row = dict(bar)
        for p in periods:
            row[f"ma{p}"] = round(ma_data[f"ma{p}"][i], 2)
        result.append(row)
    return result


# ============== MACD ==============


def calc_macd(bars: list[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict]:
    """计算 MACD（DIF/DEA/MACD柱）。"""
    closes = _closes(bars)
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)

    dif = [f - s for f, s in zip(ema_fast, ema_slow)]
    dea = _ema(dif, signal)
    macd_hist = [(d - e) * 2 for d, e in zip(dif, dea)]

    result = []
    for i, bar in enumerate(bars):
        row = dict(bar)
        row["dif"] = round(dif[i], 4)
        row["dea"] = round(dea[i], 4)
        row["macd"] = round(macd_hist[i], 4)
        result.append(row)
    return result


# ============== RSI ==============


def calc_rsi(bars: list[dict], period: int = 14) -> list[dict]:
    """计算 RSI（相对强弱指标）。"""
    closes = _closes(bars)
    if len(closes) < 2:
        return [dict(b, rsi=50.0) for b in bars]

    gains = [0.0]
    losses = [0.0]
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    result = []
    for i, bar in enumerate(bars):
        row = dict(bar)
        if i < period:
            row["rsi"] = 50.0
        else:
            window_gain = sum(gains[i - period + 1 : i + 1]) / period
            window_loss = sum(losses[i - period + 1 : i + 1]) / period
            if window_loss == 0:
                row["rsi"] = 100.0
            else:
                rs = window_gain / window_loss
                row["rsi"] = round(100 - 100 / (1 + rs), 2)
        result.append(row)
    return result


# ============== KDJ ==============


def calc_kdj(bars: list[dict], n: int = 9, m1: int = 3, m2: int = 3) -> list[dict]:
    """计算 KDJ 随机指标。"""
    highs = _highs(bars)
    lows = _lows(bars)
    closes = _closes(bars)

    k_values = [50.0]
    d_values = [50.0]

    for i in range(1, len(bars)):
        start = max(0, i - n + 1)
        hn = max(highs[start : i + 1])
        ln = min(lows[start : i + 1])

        if hn == ln:
            rsv = 50.0
        else:
            rsv = (closes[i] - ln) / (hn - ln) * 100

        k = (m1 - 1) / m1 * k_values[-1] + 1 / m1 * rsv
        d = (m2 - 1) / m2 * d_values[-1] + 1 / m2 * k
        k_values.append(k)
        d_values.append(d)

    result = []
    for i, bar in enumerate(bars):
        row = dict(bar)
        row["k"] = round(k_values[i], 2)
        row["d"] = round(d_values[i], 2)
        row["j"] = round(3 * k_values[i] - 2 * d_values[i], 2)
        result.append(row)
    return result


# ============== 量比 ==============


def calc_volume_ratio(bars: list[dict], period: int = 5) -> list[dict]:
    """计算量比（当日成交量 / 近 N 日平均成交量）。"""
    volumes = _volumes(bars)
    avg_vol = _sma(volumes, period)

    result = []
    for i, bar in enumerate(bars):
        row = dict(bar)
        if avg_vol[i] > 0:
            row["volume_ratio"] = round(volumes[i] / avg_vol[i], 2)
        else:
            row["volume_ratio"] = 0.0
        result.append(row)
    return result


# ============== 支撑/压力位 ==============


def calc_support_resistance(bars: list[dict], lookback: int = 20) -> dict[str, Any]:
    """计算支撑/压力位（枢轴点 + 摆动高低点）。"""
    if not bars:
        return {
            "pivot": 0,
            "support": [],
            "resistance": [],
            "swing_highs": [],
            "swing_lows": [],
        }

    # 取最近 lookback 根 K 线
    recent = bars[-lookback:] if len(bars) >= lookback else bars
    highs = _highs(recent)
    lows = _lows(recent)
    closes = _closes(recent)

    # 枢轴点（经典公式）
    last_h = highs[-1]
    last_l = lows[-1]
    last_c = closes[-1]
    pivot = round((last_h + last_l + last_c) / 3, 2)
    s1 = round(2 * pivot - last_h, 2)
    r1 = round(2 * pivot - last_l, 2)
    s2 = round(pivot - (last_h - last_l), 2)
    r2 = round(pivot + (last_h - last_l), 2)

    # 摆动高低点（局部极值）
    swing_highs = []
    swing_lows = []
    for i in range(2, len(highs) - 2):
        if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[i + 2]:
            swing_highs.append(round(highs[i], 2))
        if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
            swing_lows.append(round(lows[i], 2))

    return {
        "pivot": pivot,
        "support": [s1, s2],
        "resistance": [r1, r2],
        "swing_highs": swing_highs[-5:],  # 最近 5 个
        "swing_lows": swing_lows[-5:],
    }


# ============== 综合计算 ==============


def calc_all(bars: list[dict]) -> dict[str, Any]:
    """一次性计算所有技术指标。"""
    if not bars:
        return {"bars": [], "support_resistance": {}}

    # 按日期升序
    sorted_bars = sorted(bars, key=lambda b: b.get("date", ""))

    # 依次计算各指标（每步在前一步基础上叠加字段）
    result = calc_ma(sorted_bars)
    result = calc_macd(result)
    result = calc_rsi(result)
    result = calc_kdj(result)
    result = calc_volume_ratio(result)
    sr = calc_support_resistance(sorted_bars)

    # 取最新一条的指标摘要
    latest = result[-1] if result else {}
    summary = {
        "symbol": latest.get("symbol", ""),
        "date": latest.get("date", ""),
        "close": latest.get("close", 0),
        "ma5": latest.get("ma5", 0),
        "ma10": latest.get("ma10", 0),
        "ma20": latest.get("ma20", 0),
        "ma60": latest.get("ma60", 0),
        "dif": latest.get("dif", 0),
        "dea": latest.get("dea", 0),
        "macd": latest.get("macd", 0),
        "rsi": latest.get("rsi", 0),
        "k": latest.get("k", 0),
        "d": latest.get("d", 0),
        "j": latest.get("j", 0),
        "volume_ratio": latest.get("volume_ratio", 0),
    }

    return {
        "summary": summary,
        "bars": result,
        "support_resistance": sr,
    }
