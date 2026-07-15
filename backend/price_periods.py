"""行情周期转换和分时数据获取。"""

from __future__ import annotations

import logging
from datetime import date, datetime, time
from typing import Any

from backend.price_store import get_market, normalize_symbol

logger = logging.getLogger(__name__)

INTRADAY_FREQUENCIES = {"intraday", "1m", "minute", "minutes", "分时"}
WEEKLY_FREQUENCIES = {"1w", "w", "week", "weekly", "周k", "周K"}
MONTHLY_FREQUENCIES = {"1mo", "1mth", "1M", "month", "monthly", "月k", "月K"}
YEARLY_FREQUENCIES = {"1y", "y", "year", "yearly", "年k", "年K"}


def normalize_frequency(frequency: str | None) -> str:
    """把前端/调用方的周期别名收敛成内部频率。"""
    raw = (frequency or "1d").strip()
    lowered = raw.lower()
    if raw == "1M":
        return "1mo"
    if raw in INTRADAY_FREQUENCIES or lowered in INTRADAY_FREQUENCIES:
        return "intraday"
    if raw in WEEKLY_FREQUENCIES or lowered in {item.lower() for item in WEEKLY_FREQUENCIES}:
        return "1w"
    if raw in MONTHLY_FREQUENCIES or lowered in {item.lower() for item in MONTHLY_FREQUENCIES}:
        return "1mo"
    if raw in YEARLY_FREQUENCIES or lowered in {item.lower() for item in YEARLY_FREQUENCIES}:
        return "1y"
    return "1d"


def _parse_bar_datetime(value: Any) -> datetime | None:
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


def _period_key(dt: datetime, frequency: str) -> tuple[int, int] | tuple[int, int, int]:
    if frequency == "1w":
        iso = dt.isocalendar()
        return (iso.year, iso.week)
    if frequency == "1y":
        return (dt.year, 1, 1)
    return (dt.year, dt.month, 1)


def _as_number(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def aggregate_price_bars(bars: list[dict[str, Any]], frequency: str) -> list[dict[str, Any]]:
    """从日线聚合周线/月线。输入可乱序，输出按日期升序。"""
    normalized_frequency = normalize_frequency(frequency)
    if normalized_frequency not in {"1w", "1mo", "1y"}:
        return bars

    dated_bars = [(dt, bar) for bar in bars if (dt := _parse_bar_datetime(bar.get("date"))) is not None]
    dated_bars.sort(key=lambda item: item[0])
    if not dated_bars:
        return []

    groups: list[list[tuple[datetime, dict[str, Any]]]] = []
    current_key: tuple[int, int] | tuple[int, int, int] | None = None
    for item in dated_bars:
        key = _period_key(item[0], normalized_frequency)
        if key != current_key:
            groups.append([])
            current_key = key
        groups[-1].append(item)

    out: list[dict[str, Any]] = []
    previous_close = 0.0
    for group in groups:
        first_dt, first_bar = group[0]
        last_dt, last_bar = group[-1]
        open_price = _as_number(first_bar.get("open"))
        close = _as_number(last_bar.get("close"))
        high = max(_as_number(bar.get("high")) for _, bar in group)
        low = min(_as_number(bar.get("low")) for _, bar in group)
        volume = sum(_as_number(bar.get("volume")) for _, bar in group)
        amount = sum(_as_number(bar.get("amount")) for _, bar in group)
        base = previous_close or open_price or close
        change_pct = ((close - base) / base * 100) if base else 0.0
        amplitude = ((high - low) / base * 100) if base else 0.0
        previous_close = close

        out.append(
            {
                "symbol": last_bar.get("symbol") or first_bar.get("symbol") or "",
                "date": last_dt.strftime("%Y-%m-%d"),
                "period_start": first_dt.strftime("%Y-%m-%d"),
                "market": last_bar.get("market") or first_bar.get("market") or "CN",
                "frequency": normalized_frequency,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "amount": amount,
                "turnover": 0.0,
                "amplitude": round(amplitude, 4),
                "change_pct": round(change_pct, 4),
                "adjust": last_bar.get("adjust") or first_bar.get("adjust") or "",
                "source": f"aggregate:{last_bar.get('source') or first_bar.get('source') or '1d'}",
                "fetched_at": last_bar.get("fetched_at") or first_bar.get("fetched_at") or 0,
            }
        )
    return out


def _to_market_symbol(symbol: str) -> str:
    code = normalize_symbol(symbol)
    if code.startswith(("60", "68", "90")):
        return f"sh{code}"
    if code.startswith(("00", "30", "20")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return code


def _clean_intraday_datetime(value: Any) -> str:
    dt = _parse_bar_datetime(value)
    if dt:
        return dt.strftime("%Y-%m-%d %H:%M")
    return str(value or "").strip()


def _is_cn_trading_minute(dt: datetime) -> bool:
    current = dt.time()
    return time(9, 30) <= current <= time(11, 30) or time(13, 0) <= current <= time(15, 0)


def _previous_daily_close(symbol: str, before: datetime | None = None) -> float:
    try:
        from backend.price_store import get_prices

        end_date = before.strftime("%Y-%m-%d") if before else None
        daily = get_prices(
            symbol=symbol,
            frequency="1d",
            end_date=end_date,
            limit=2,
        )
        dated = [
            (dt, bar)
            for bar in daily
            if (dt := _parse_bar_datetime(bar.get("date"))) is not None
            and (before is None or dt.date() < before.date())
        ]
        dated.sort(key=lambda item: item[0], reverse=True)
        if dated:
            return _as_number(dated[0][1].get("close"))
    except Exception as exc:
        logger.debug("previous close lookup failed for %s: %s", symbol, exc)
    return 0.0


def _compatible_previous_close(previous_close: float, current_price: float) -> float:
    if previous_close <= 0 or current_price <= 0:
        return 0.0
    ratio = previous_close / current_price
    if 0.5 <= ratio <= 1.5:
        return previous_close
    logger.debug(
        "discard incompatible intraday previous close: previous=%s current=%s ratio=%s",
        previous_close,
        current_price,
        ratio,
    )
    return 0.0


def fetch_intraday_prices(symbol: str, limit: int = 240, period: str = "1") -> list[dict[str, Any]]:
    """实时拉取分钟级分时数据。失败返回空列表，不用日线冒充。

    短 TTL 内存缓存(默认 45s)降低盘中重复打上游; 空结果不缓存以便重试。
    """
    code = normalize_symbol(symbol)
    if not code or get_market(code) != "CN":
        return []

    cache_key = f"intraday:{code}:{period}:{int(limit)}"
    try:
        from backend.cache import get_cache

        cached = get_cache().get(cache_key)
        if isinstance(cached, list) and cached:
            return cached
    except Exception:
        pass

    try:
        import akshare as ak

        df = ak.stock_zh_a_minute(symbol=_to_market_symbol(code), period=period, adjust="")
    except Exception as exc:
        logger.warning("intraday prices failed for %s: %s", code, exc)
        return []

    if df is None or len(df) == 0:
        return []

    df = df.tail(max(1, min(max(limit * 3, limit + 60), 1500))).copy()
    columns = {str(col).strip().lower(): col for col in df.columns}

    def col(*names: str):
        for name in names:
            key = name.strip().lower()
            if key in columns:
                return columns[key]
        for existing_key, original in columns.items():
            if any(name.strip().lower() in existing_key for name in names):
                return original
        return None

    date_col = col("day", "datetime", "时间", "日期")
    open_col = col("open", "开盘")
    high_col = col("high", "最高")
    low_col = col("low", "最低")
    close_col = col("close", "收盘", "price", "价格")
    volume_col = col("volume", "成交量")
    amount_col = col("amount", "成交额")

    rows: list[tuple[datetime, Any]] = []
    for _, row in df.iterrows():
        raw_date = row.get(date_col) if date_col else datetime.now().strftime("%Y-%m-%d %H:%M")
        dt = _parse_bar_datetime(raw_date)
        if not dt or not _is_cn_trading_minute(dt):
            continue
        rows.append((dt, row))

    if not rows:
        return []

    latest_trade_date = max(dt.date() for dt, _ in rows)
    rows = [(dt, row) for dt, row in rows if dt.date() == latest_trade_date]
    rows.sort(key=lambda item: item[0])
    rows = rows[-max(1, min(limit, 1500)) :]

    first_row = rows[0][1]
    first_open = _as_number(first_row.get(open_col)) if open_col else 0.0
    first_close = _as_number(first_row.get(close_col)) if close_col else 0.0
    first_price = first_open or first_close
    previous_close = _compatible_previous_close(
        _previous_daily_close(code, rows[0][0]),
        first_price,
    )
    if previous_close <= 0:
        previous_close = first_price

    results: list[dict[str, Any]] = []
    last_close = previous_close
    for dt, row in rows:
        open_price = _as_number(row.get(open_col)) if open_col else 0.0
        close = _as_number(row.get(close_col)) if close_col else open_price
        high = _as_number(row.get(high_col)) if high_col else max(open_price, close)
        low = _as_number(row.get(low_col)) if low_col else min(open_price, close)
        base = previous_close or last_close or open_price or close
        change_pct = ((close - base) / base * 100) if base else 0.0
        amplitude = ((high - low) / base * 100) if base else 0.0
        last_close = close
        results.append(
            {
                "symbol": code,
                "date": dt.strftime("%Y-%m-%d %H:%M"),
                "market": "CN",
                "frequency": "intraday",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": _as_number(row.get(volume_col)) if volume_col else 0.0,
                "amount": _as_number(row.get(amount_col)) if amount_col else 0.0,
                "turnover": 0.0,
                "amplitude": round(amplitude, 4),
                "change_pct": round(change_pct, 4),
                "previous_close": previous_close,
                "adjust": "",
                "source": "akshare_intraday",
                "fetched_at": datetime.now().timestamp(),
            }
        )
    if results:
        try:
            from backend.cache import get_cache

            get_cache().set(cache_key, results, ttl_seconds=45)
        except Exception:
            pass
    return results


def default_daily_window_days(limit: int, frequency: str) -> int:
    """为聚合周期准备足够的日线数据。"""
    normalized = normalize_frequency(frequency)
    if normalized == "1y":
        return max(limit * 366 + 730, 3650)
    if normalized == "1mo":
        return max(limit * 32 + 90, 730)
    if normalized == "1w":
        return max(limit * 7 + 30, 365)
    return max(limit * 2, 30)


def latest_bar_date(bars: list[dict[str, Any]]) -> date | None:
    """Return the latest calendar date found in a bar list."""

    dates = [dt.date() for bar in bars if (dt := _parse_bar_datetime(bar.get("date"))) is not None]
    return max(dates) if dates else None
