"""Price series quality helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _as_float(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y%m%d",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _ratio_too_large(a: float, b: float, max_ratio: float) -> bool:
    if a <= 0 or b <= 0:
        return False
    ratio = max(a, b) / min(a, b)
    return ratio >= max_ratio


def filter_incompatible_price_bars(
    bars: list[dict[str, Any]],
    *,
    max_adjacent_ratio: float = 3.0,
) -> list[dict[str, Any]]:
    """Drop isolated bars that are incompatible with adjacent prices.

    This catches mixed adjustment series, for example one 后复权 daily bar
    inserted into an otherwise unadjusted recent series.
    """

    if len(bars) < 2:
        return bars

    indexed = [(index, dt, bar) for index, bar in enumerate(bars) if (dt := _parse_date(bar.get("date"))) is not None]
    if len(indexed) < 2:
        return bars

    indexed.sort(key=lambda item: item[1])
    drop_indexes: set[int] = set()

    for pos, (original_index, _, bar) in enumerate(indexed):
        close = _as_float(bar.get("close"))
        if close <= 0:
            continue

        prev_close = _as_float(indexed[pos - 1][2].get("close")) if pos > 0 else 0.0
        next_close = _as_float(indexed[pos + 1][2].get("close")) if pos < len(indexed) - 1 else 0.0
        prev_bad = prev_close > 0 and _ratio_too_large(close, prev_close, max_adjacent_ratio)
        next_bad = next_close > 0 and _ratio_too_large(close, next_close, max_adjacent_ratio)

        if (prev_bad and next_bad) or (pos == 0 and next_bad) or (pos == len(indexed) - 1 and prev_bad):
            drop_indexes.add(original_index)

    if not drop_indexes:
        return bars
    return [bar for index, bar in enumerate(bars) if index not in drop_indexes]
