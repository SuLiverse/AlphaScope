"""事件影响分析 — 分析事件与股价变动的关联"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


def analyze_event_impact(
    events: list[dict[str, Any]],
    prices: list[dict[str, Any]],
    window_days: int = 5,
) -> list[dict[str, Any]]:
    """分析每个事件前后 N 日的股价变动。

    Args:
        events: 事件列表，每条需有 published_at, event_type, sentiment, title
        prices: K 线列表，每条需有 date, close, change_pct
        window_days: 事件前后观察窗口（交易日）

    Returns:
        事件列表，每条附加 impact 字段
    """
    if not events or not prices:
        return events

    # 构建日期→价格映射
    price_map = {p["date"]: p for p in prices}
    sorted_dates = sorted(price_map.keys())

    results = []
    for event in events:
        event_date = _parse_date(event.get("published_at", ""))
        if not event_date:
            results.append({**event, "impact": _empty_impact()})
            continue

        # 找事件日最近的交易日
        closest_date = _find_closest_date(event_date, sorted_dates)
        if not closest_date:
            results.append({**event, "impact": _empty_impact()})
            continue

        idx = sorted_dates.index(closest_date)

        # 事件前 window_days 日
        pre_start = max(0, idx - window_days)
        pre_dates = sorted_dates[pre_start:idx]

        # 事件后 window_days 日
        post_end = min(len(sorted_dates), idx + window_days + 1)
        post_dates = sorted_dates[idx + 1 : post_end]

        # 计算前/后涨跌幅
        pre_change = sum(price_map[d].get("change_pct", 0) for d in pre_dates)
        post_change = sum(price_map[d].get("change_pct", 0) for d in post_dates)

        event_close = price_map[closest_date].get("close", 0)
        pre_close = price_map[pre_dates[0]]["close"] if pre_dates and event_close else 0
        post_close = price_map[post_dates[-1]]["close"] if post_dates and event_close else 0

        impact = {
            "event_date": closest_date,
            "pre_change_pct": round(pre_change, 2),
            "post_change_pct": round(post_change, 2),
            "price_at_event": event_close,
            "price_before": pre_close,
            "price_after": post_close,
            "impact_level": _classify_impact(post_change),
        }

        results.append({**event, "impact": impact})

    return results


def get_sentiment_trend(events: list[dict[str, Any]], days: int = 30) -> list[dict[str, Any]]:
    """按日聚合情绪趋势。"""
    daily: dict[str, list[float]] = defaultdict(list)

    for event in events:
        date = _parse_date(event.get("published_at", ""))
        if not date:
            continue
        date_str = date[:10]
        sentiment = event.get("sentiment", 0)
        if isinstance(sentiment, (int, float)):
            daily[date_str].append(float(sentiment))

    trend = []
    for date_str in sorted(daily.keys())[-days:]:
        values = daily[date_str]
        trend.append(
            {
                "date": date_str,
                "avg_sentiment": round(sum(values) / len(values), 3),
                "count": len(values),
                "positive": sum(1 for v in values if v > 0.1),
                "negative": sum(1 for v in values if v < -0.1),
                "neutral": sum(1 for v in values if -0.1 <= v <= 0.1),
            }
        )

    return trend


def correlate_events_prices(
    events: list[dict[str, Any]],
    prices: list[dict[str, Any]],
) -> dict[str, Any]:
    """事件-价格相关性统计。"""
    if not events or not prices:
        return {"correlation": 0, "event_count": 0, "price_count": 0}

    impacted = analyze_event_impact(events, prices)
    valid = [e for e in impacted if e.get("impact", {}).get("price_at_event", 0) > 0]

    if not valid:
        return {
            "correlation": 0,
            "event_count": len(events),
            "price_count": len(prices),
        }

    # 简单相关性：情绪方向与后续涨跌方向一致的比例
    consistent = 0
    for e in valid:
        sentiment = e.get("sentiment", 0)
        post_change = e["impact"].get("post_change_pct", 0)
        if (sentiment > 0 and post_change > 0) or (sentiment < 0 and post_change < 0):
            consistent += 1
        elif sentiment == 0 and abs(post_change) < 0.5:
            consistent += 1

    correlation = consistent / len(valid) if valid else 0

    return {
        "correlation": round(correlation, 3),
        "event_count": len(events),
        "analyzed_count": len(valid),
        "consistent_direction": consistent,
    }


def _parse_date(date_str: str) -> str:
    """解析日期字符串，返回 YYYY-MM-DD 格式。"""
    if not date_str:
        return ""
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y%m%d"):
        try:
            return datetime.strptime(date_str[: len(fmt)], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str[:10] if len(date_str) >= 10 else ""


def _find_closest_date(target: str, sorted_dates: list[str]) -> str | None:
    """找到最接近目标日期的交易日。"""
    if not sorted_dates:
        return None
    # 二分查找最近的日期
    for d in sorted_dates:
        if d >= target:
            return d
    return sorted_dates[-1]


def _classify_impact(post_change: float) -> str:
    """分类事件影响程度。"""
    if post_change > 3:
        return "强正面"
    elif post_change > 1:
        return "正面"
    elif post_change > -1:
        return "中性"
    elif post_change > -3:
        return "负面"
    else:
        return "强负面"


def _empty_impact() -> dict[str, Any]:
    return {
        "event_date": "",
        "pre_change_pct": 0,
        "post_change_pct": 0,
        "price_at_event": 0,
        "price_before": 0,
        "price_after": 0,
        "impact_level": "未知",
    }
