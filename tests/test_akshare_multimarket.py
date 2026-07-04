"""AkShare Provider 多市场行情分支测试(三市场工作台)。

覆盖:
1. 符号辅助: _normalize_us_symbol / _looks_like_us_symbol
2. 美股日线: _get_us_prices(mock stock_us_daily, date 在列/在索引两种形态)
3. 港股日线: _get_hk_prices(mock stock_hk_daily, 补上此前缺失的锁定)
4. get_prices 按 market 分流(CN 路径不受影响)

全部离线: akshare 调用一律 monkeypatch, 不触网。
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.providers import akshare_provider as ap


@pytest.fixture()
def provider():
    return ap.AkShareProvider()


def _us_df(with_date_column: bool = True) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "date": ["2026-06-29", "2026-06-30", "2026-07-01"],
            "open": [100.0, 102.0, 104.0],
            "high": [103.0, 105.0, 106.0],
            "low": [99.0, 101.0, 103.0],
            "close": [102.0, 104.0, 105.0],
            "volume": [1_000_000, 1_100_000, 900_000],
        }
    )
    if not with_date_column:
        df = df.set_index("date")
    return df


def _hk_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2026-06-30", "2026-07-01"],
            "open": [300.0, 305.0],
            "high": [310.0, 312.0],
            "low": [298.0, 303.0],
            "close": [305.0, 310.0],
            "volume": [5_000_000, 4_500_000],
        }
    )


# ============================================================
# 1. 符号辅助
# ============================================================


def test_normalize_us_symbol():
    assert ap._normalize_us_symbol("AAPL") == "AAPL"
    assert ap._normalize_us_symbol("aapl") == "AAPL"
    assert ap._normalize_us_symbol("MSFT.US") == "MSFT"
    assert ap._normalize_us_symbol("105.AAPL") == "AAPL"  # 东财市场号前缀
    assert ap._normalize_us_symbol("BRK.B") == "BRK.B"
    assert ap._normalize_us_symbol("") == ""


def test_akshare_capability_declares_all_supported_markets(provider):
    cap = provider.capability()
    assert {"CN", "HK", "US", "ALL"}.issubset(set(cap["markets"]))
    assert "prices" in cap["data_types"]


def test_looks_like_us_symbol():
    assert ap._looks_like_us_symbol("AAPL") is True
    assert ap._looks_like_us_symbol("BRK.B") is True
    assert ap._looks_like_us_symbol("TSLA.US") is True
    # A 股各种写法不得误判
    assert ap._looks_like_us_symbol("600519") is False
    assert ap._looks_like_us_symbol("SH600519") is False
    assert ap._looks_like_us_symbol("00700") is False
    assert ap._looks_like_us_symbol("") is False


# ============================================================
# 2. 美股日线
# ============================================================


def test_us_prices_basic(provider, monkeypatch):
    monkeypatch.setattr(ap.ak, "stock_us_daily", lambda **kw: _us_df(), raising=False)
    bars = provider._get_us_prices({"symbol": "AAPL", "limit": 10})
    assert len(bars) == 3
    assert bars[-1]["market"] == "US"
    assert bars[-1]["close"] == 105.0
    assert bars[-1]["source"] == "akshare:stock_us_daily"
    # change_pct 基于前收
    assert bars[1]["change_pct"] == pytest.approx((104.0 - 102.0) / 102.0 * 100, rel=1e-4)


def test_us_prices_date_in_index(provider, monkeypatch):
    monkeypatch.setattr(ap.ak, "stock_us_daily", lambda **kw: _us_df(with_date_column=False), raising=False)
    bars = provider._get_us_prices({"symbol": "MSFT", "limit": 10})
    assert len(bars) == 3
    assert bars[0]["date"] == "2026-06-29"


def test_us_prices_date_filter(provider, monkeypatch):
    monkeypatch.setattr(ap.ak, "stock_us_daily", lambda **kw: _us_df(), raising=False)
    bars = provider._get_us_prices({"symbol": "AAPL", "start_date": "20260630", "end_date": "20260630"})
    assert len(bars) == 1
    assert bars[0]["date"] == "2026-06-30"


def test_us_prices_empty_safe(provider, monkeypatch):
    monkeypatch.setattr(ap.ak, "stock_us_daily", lambda **kw: None, raising=False)
    assert provider._get_us_prices({"symbol": "AAPL"}) == []


# ============================================================
# 3. 港股日线(锁定既有行为)
# ============================================================


def test_hk_prices_basic(provider, monkeypatch):
    monkeypatch.setattr(ap.ak, "stock_hk_daily", lambda **kw: _hk_df(), raising=False)
    bars = provider._get_hk_prices({"symbol": "00700", "limit": 10})
    assert len(bars) == 2
    assert bars[-1]["market"] == "HK"
    assert bars[-1]["close"] == 310.0
    assert bars[-1]["source"] == "akshare:stock_hk_daily"


def test_hk_prices_pads_symbol(provider, monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return _hk_df()

    monkeypatch.setattr(ap.ak, "stock_hk_daily", fake, raising=False)
    provider._get_hk_prices({"symbol": "700"})
    assert seen.get("symbol") == "00700"


# ============================================================
# 4. get_prices 市场分流
# ============================================================


def test_get_prices_routes_us_by_market(provider, monkeypatch):
    monkeypatch.setattr(ap.ak, "stock_us_daily", lambda **kw: _us_df(), raising=False)
    bars = provider.get_prices({"symbol": "AAPL", "market": "US", "limit": 5})
    assert bars and bars[0]["market"] == "US"


def test_get_prices_routes_us_by_symbol_shape(provider, monkeypatch):
    monkeypatch.setattr(ap.ak, "stock_us_daily", lambda **kw: _us_df(), raising=False)
    bars = provider.get_prices({"symbol": "NVDA", "limit": 5})
    assert bars and bars[0]["market"] == "US"


def test_get_prices_routes_hk_by_market(provider, monkeypatch):
    monkeypatch.setattr(ap.ak, "stock_hk_daily", lambda **kw: _hk_df(), raising=False)
    bars = provider.get_prices({"symbol": "00700", "market": "HK", "limit": 5})
    assert bars and bars[0]["market"] == "HK"


def test_get_prices_cn_path_untouched(provider, monkeypatch):
    """A 股符号不落入港/美分支(走 stock_zh_a_hist 主路)。"""
    called = {"us": 0, "hk": 0}
    monkeypatch.setattr(ap.ak, "stock_us_daily", lambda **kw: called.__setitem__("us", 1), raising=False)
    monkeypatch.setattr(ap.ak, "stock_hk_daily", lambda **kw: called.__setitem__("hk", 1), raising=False)
    monkeypatch.setattr(
        ap.ak,
        "stock_zh_a_hist",
        lambda **kw: pd.DataFrame(
            {
                "日期": ["2026-07-01"],
                "开盘": [10.0],
                "最高": [10.5],
                "最低": [9.8],
                "收盘": [10.2],
                "成交量": [123456],
                "成交额": [1259251.2],
                "换手率": [1.2],
                "振幅": [7.0],
                "涨跌幅": [2.0],
            }
        ),
        raising=False,
    )
    bars = provider.get_prices({"symbol": "600519", "market": "CN", "limit": 5})
    assert bars and bars[0]["market"] == "CN"
    assert called == {"us": 0, "hk": 0}
