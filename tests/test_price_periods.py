from __future__ import annotations

import pandas as pd

from backend.price_periods import (
    _compatible_previous_close,
    _is_cn_trading_minute,
    aggregate_price_bars,
    default_daily_window_days,
    fetch_intraday_prices,
    latest_bar_date,
    normalize_frequency,
)
from backend.price_quality import filter_incompatible_price_bars


def test_normalize_frequency_aliases():
    assert normalize_frequency("分时") == "intraday"
    assert normalize_frequency("1m") == "intraday"
    assert normalize_frequency("1w") == "1w"
    assert normalize_frequency("weekly") == "1w"
    assert normalize_frequency("1mo") == "1mo"
    assert normalize_frequency("1M") == "1mo"
    assert normalize_frequency("monthly") == "1mo"
    assert normalize_frequency("1y") == "1y"
    assert normalize_frequency("yearly") == "1y"
    assert normalize_frequency("年K") == "1y"
    assert normalize_frequency("unknown") == "1d"


def test_default_daily_window_days_extends_weekly_and_monthly_history():
    assert default_daily_window_days(156, "1w") >= 1122
    assert default_daily_window_days(120, "1mo") >= 3930
    assert default_daily_window_days(10, "1y") >= 3650
    assert default_daily_window_days(80, "1d") == 160


def test_aggregate_weekly_bars_uses_true_ohlc_and_sums_volume():
    bars = [
        {
            "symbol": "600519",
            "date": "2026-05-04",
            "open": 10,
            "high": 13,
            "low": 9,
            "close": 12,
            "volume": 100,
            "amount": 1000,
            "source": "test",
        },
        {
            "symbol": "600519",
            "date": "2026-05-05",
            "open": 12,
            "high": 15,
            "low": 11,
            "close": 14,
            "volume": 200,
            "amount": 2000,
            "source": "test",
        },
        {
            "symbol": "600519",
            "date": "2026-05-11",
            "open": 20,
            "high": 21,
            "low": 18,
            "close": 19,
            "volume": 300,
            "amount": 3000,
            "source": "test",
        },
    ]

    result = aggregate_price_bars(bars, "1w")

    assert len(result) == 2
    assert result[0]["period_start"] == "2026-05-04"
    assert result[0]["date"] == "2026-05-05"
    assert result[0]["open"] == 10
    assert result[0]["high"] == 15
    assert result[0]["low"] == 9
    assert result[0]["close"] == 14
    assert result[0]["volume"] == 300
    assert result[0]["amount"] == 3000
    assert result[0]["frequency"] == "1w"


def test_aggregate_monthly_bars_groups_by_calendar_month():
    bars = [
        {
            "symbol": "600519",
            "date": "2026-04-30",
            "open": 9,
            "high": 11,
            "low": 8,
            "close": 10,
            "volume": 50,
        },
        {
            "symbol": "600519",
            "date": "2026-05-04",
            "open": 10,
            "high": 13,
            "low": 9,
            "close": 12,
            "volume": 100,
        },
        {
            "symbol": "600519",
            "date": "2026-05-29",
            "open": 12,
            "high": 15,
            "low": 11,
            "close": 14,
            "volume": 200,
        },
    ]

    result = aggregate_price_bars(bars, "1mo")

    assert [item["period_start"] for item in result] == ["2026-04-30", "2026-05-04"]
    assert result[1]["date"] == "2026-05-29"
    assert result[1]["open"] == 10
    assert result[1]["high"] == 15
    assert result[1]["low"] == 9
    assert result[1]["close"] == 14
    assert result[1]["volume"] == 300


def test_aggregate_yearly_bars_groups_by_calendar_year():
    bars = [
        {
            "symbol": "600519",
            "date": "2025-01-02",
            "open": 10,
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 100,
            "amount": 1000,
            "source": "test",
        },
        {
            "symbol": "600519",
            "date": "2025-12-31",
            "open": 11,
            "high": 15,
            "low": 10,
            "close": 14,
            "volume": 200,
            "amount": 2000,
            "source": "test",
        },
        {
            "symbol": "600519",
            "date": "2026-01-05",
            "open": 20,
            "high": 22,
            "low": 19,
            "close": 21,
            "volume": 300,
            "amount": 3000,
            "source": "test",
        },
    ]

    result = aggregate_price_bars(bars, "1y")

    assert [item["period_start"] for item in result] == ["2025-01-02", "2026-01-05"]
    assert result[0]["date"] == "2025-12-31"
    assert result[0]["open"] == 10
    assert result[0]["high"] == 15
    assert result[0]["low"] == 9
    assert result[0]["close"] == 14
    assert result[0]["volume"] == 300
    assert result[0]["amount"] == 3000
    assert result[0]["frequency"] == "1y"


def test_cn_trading_minute_filter():
    from datetime import datetime

    assert _is_cn_trading_minute(datetime(2026, 5, 25, 9, 30))
    assert _is_cn_trading_minute(datetime(2026, 5, 25, 11, 30))
    assert _is_cn_trading_minute(datetime(2026, 5, 25, 13, 0))
    assert _is_cn_trading_minute(datetime(2026, 5, 25, 15, 0))
    assert not _is_cn_trading_minute(datetime(2026, 5, 25, 9, 29))
    assert not _is_cn_trading_minute(datetime(2026, 5, 25, 11, 45))
    assert not _is_cn_trading_minute(datetime(2026, 5, 25, 15, 1))


def test_incompatible_intraday_previous_close_is_discarded():
    assert _compatible_previous_close(7926.11, 1270.69) == 0.0
    assert _compatible_previous_close(1268.0, 1270.69) == 1268.0


def test_filter_incompatible_price_bars_drops_mixed_adjustment_spike():
    bars = [
        {"date": "2026-05-26", "close": 7846.51},
        {"date": "2026-05-25", "close": 1285.88},
        {"date": "2026-05-22", "close": 1290.20},
    ]

    result = filter_incompatible_price_bars(bars)

    assert [item["date"] for item in result] == ["2026-05-25", "2026-05-22"]


def test_latest_bar_date_uses_calendar_date():
    bars = [
        {"date": "2026-05-25 09:31"},
        {"date": "2026-05-26"},
    ]

    assert latest_bar_date(bars).isoformat() == "2026-05-26"


def test_fetch_intraday_prices_keeps_latest_trade_day_and_previous_close(monkeypatch):
    rows = pd.DataFrame(
        [
            {
                "day": "2026-05-24 15:00:00",
                "open": 9.8,
                "high": 10.0,
                "low": 9.7,
                "close": 9.9,
                "volume": 10,
            },
            {
                "day": "2026-05-25 09:29:00",
                "open": 10.0,
                "high": 10.0,
                "low": 10.0,
                "close": 10.0,
                "volume": 20,
            },
            {
                "day": "2026-05-25 09:30:00",
                "open": 10.0,
                "high": 10.4,
                "low": 9.9,
                "close": 10.2,
                "volume": 100,
            },
            {
                "day": "2026-05-25 11:45:00",
                "open": 10.2,
                "high": 10.3,
                "low": 10.1,
                "close": 10.2,
                "volume": 50,
            },
            {
                "day": "2026-05-25 13:00:00",
                "open": 10.2,
                "high": 10.6,
                "low": 10.1,
                "close": 10.5,
                "volume": 120,
            },
        ]
    )

    class FakeAkshare:
        @staticmethod
        def stock_zh_a_minute(**kwargs):
            return rows

    monkeypatch.setattr("backend.price_periods.get_market", lambda symbol: "CN")
    monkeypatch.setattr("backend.price_periods._previous_daily_close", lambda symbol, before=None: 10.0)
    monkeypatch.setitem(__import__("sys").modules, "akshare", FakeAkshare)

    result = fetch_intraday_prices("600519", limit=240)

    assert [item["date"] for item in result] == [
        "2026-05-25 09:30",
        "2026-05-25 13:00",
    ]
    assert all(item["previous_close"] == 10.0 for item in result)
    assert result[0]["change_pct"] == 2.0
    assert result[1]["change_pct"] == 5.0
