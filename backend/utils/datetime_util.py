"""Datetime parsing and timezone normalization utilities.

Handles the various datetime string formats produced by Chinese financial data
sources (AkShare, Tushare, EastMoney, CLS, etc.) and normalizes them to
timezone-aware datetime objects in Asia/Shanghai.

Usage:
    from backend.utils.datetime_util import parse_dt, normalize_dt_str
    dt = parse_dt("2026-05-19 10:30:00")          # -> datetime(2026,5,19,10,30, tzinfo=Asia/Shanghai)
    s  = normalize_dt_str("2026-05-19 10:30")      # -> "2026-05-19T10:30:00+08:00"
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional

# China Standard Time
_CST = timezone(timedelta(hours=8))

# Common formats from Chinese data sources
_DT_FORMATS = [
    "%Y-%m-%d %H:%M:%S",  # "2026-05-19 10:30:00"
    "%Y-%m-%d %H:%M",  # "2026-05-19 10:30"
    "%Y/%m/%d %H:%M:%S",  # "2026/05/19 10:30:00"
    "%Y/%m/%d %H:%M",  # "2026/05/19 10:30"
    "%Y%m%d%H%M%S",  # "20260519103000"
    "%Y%m%d%H%M",  # "202605191030"
    "%Y-%m-%d",  # "2026-05-19"
    "%Y/%m/%d",  # "2026/05/19"
    "%Y%m%d",  # "20260519"
    "%m-%d %H:%M",  # "05-19 10:30" (year implied)
    "%m/%d %H:%M",  # "05/19 10:30"
]


def parse_dt(value: Optional[str | datetime], assume_tz: timezone = _CST) -> Optional[datetime]:
    """Parse a datetime string or pass-through a datetime to a tz-aware datetime.

    Returns None if *value* is empty / unparseable.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=assume_tz)
        return value
    s = str(value).strip()
    if not s or s.lower() in ("none", "nat", "nan", ""):
        return None

    # Strip trailing timezone abbreviations like "CST", "UTC+8"
    s = _strip_tz_abbr(s)

    for fmt in _DT_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            # If format has no year, use current year
            if fmt.startswith("%m"):
                dt = dt.replace(year=datetime.now().year)
            return dt.replace(tzinfo=assume_tz)
        except ValueError:
            continue

    # Try ISO format (with T separator, possibly with offset)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=assume_tz)
        return dt
    except (ValueError, AttributeError):
        pass

    return None


def normalize_dt_str(value: Optional[str | datetime], assume_tz: timezone = _CST) -> str:
    """Parse then re-emit as ISO-8601 with offset.  Returns '' on failure."""
    dt = parse_dt(value, assume_tz)
    if dt is None:
        return ""
    return dt.isoformat()


def to_utc(value: Optional[str | datetime]) -> Optional[datetime]:
    """Convert to UTC datetime.  Returns None if input is unparseable."""
    dt = parse_dt(value)
    if dt is None:
        return None
    return dt.astimezone(timezone.utc)


def format_display(value: Optional[str | datetime], fmt: str = "%Y-%m-%d %H:%M") -> str:
    """Format for UI display.  Returns '' on failure."""
    dt = parse_dt(value)
    if dt is None:
        return ""
    return dt.strftime(fmt)


def _strip_tz_abbr(s: str) -> str:
    """Remove common timezone abbreviation suffixes."""
    for abbr in (" CST", " UTC", " GMT", "CST", "UTC", "GMT"):
        if s.endswith(abbr):
            s = s[: -len(abbr)].strip()
            break
    # Remove trailing +08:00 / +0800 / +08 style offsets
    # (let fromisoformat handle them)
    return s


if __name__ == "__main__":
    tests = [
        "2026-05-19 10:30:00",
        "2026-05-19 10:30",
        "2026/05/19 10:30:00",
        "20260519103000",
        "2026-05-19",
        "05-19 10:30",
        "",
        None,
        "invalid",
    ]
    for t in tests:
        dt = parse_dt(t)
        iso = normalize_dt_str(t)
        print(f"  {str(t):30s} → {str(dt):40s} → {iso}")
