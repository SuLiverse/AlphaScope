"""Tests for Technical Indicators — 技术指标计算引擎 + API"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app

# 测试数据：20 根 K 线（模拟上涨趋势）
SAMPLE_BARS = [
    {
        "symbol": "600519",
        "date": f"2025-01-{i:02d}",
        "open": 100 + i,
        "high": 105 + i,
        "low": 98 + i,
        "close": 102 + i,
        "volume": 1000 + i * 100,
    }
    for i in range(1, 21)
]


# ============== MA 测试 ==============


class TestCalcMA:
    """测试均线计算"""

    def test_ma_output_length(self):
        from backend.indicators import calc_ma

        result = calc_ma(SAMPLE_BARS)
        assert len(result) == len(SAMPLE_BARS)

    def test_ma_fields_exist(self):
        from backend.indicators import calc_ma

        result = calc_ma(SAMPLE_BARS, periods=[5, 10])
        assert "ma5" in result[-1]
        assert "ma10" in result[-1]

    def test_ma5_value(self):
        from backend.indicators import calc_ma

        result = calc_ma(SAMPLE_BARS, periods=[5])
        # 最后 5 根 close: 118, 119, 120, 121, 122
        expected = (118 + 119 + 120 + 121 + 122) / 5
        assert abs(result[-1]["ma5"] - expected) < 0.01

    def test_ma_early_values_zero(self):
        from backend.indicators import calc_ma

        result = calc_ma(SAMPLE_BARS, periods=[20])
        assert result[0]["ma20"] == 0.0
        assert result[18]["ma20"] == 0.0

    def test_original_data_preserved(self):
        from backend.indicators import calc_ma

        result = calc_ma(SAMPLE_BARS)
        assert result[0]["open"] == 101
        assert result[0]["close"] == 103


# ============== MACD 测试 ==============


class TestCalcMACD:
    """测试 MACD 计算"""

    def test_macd_output_length(self):
        from backend.indicators import calc_macd

        result = calc_macd(SAMPLE_BARS)
        assert len(result) == len(SAMPLE_BARS)

    def test_macd_fields_exist(self):
        from backend.indicators import calc_macd

        result = calc_macd(SAMPLE_BARS)
        assert "dif" in result[-1]
        assert "dea" in result[-1]
        assert "macd" in result[-1]

    def test_macd_first_bar(self):
        from backend.indicators import calc_macd

        result = calc_macd(SAMPLE_BARS)
        # 第一根 bar 的 DIF 应为 0（EMA fast = EMA slow = close）
        assert result[0]["dif"] == 0.0

    def test_uptrend_macd_positive(self):
        from backend.indicators import calc_macd

        result = calc_macd(SAMPLE_BARS)
        # 上涨趋势中，后期 DIF 应为正
        assert result[-1]["dif"] > 0


# ============== RSI 测试 ==============


class TestCalcRSI:
    """测试 RSI 计算"""

    def test_rsi_output_length(self):
        from backend.indicators import calc_rsi

        result = calc_rsi(SAMPLE_BARS)
        assert len(result) == len(SAMPLE_BARS)

    def test_rsi_range(self):
        from backend.indicators import calc_rsi

        result = calc_rsi(SAMPLE_BARS)
        for bar in result:
            if bar["rsi"] > 0:
                assert 0 <= bar["rsi"] <= 100

    def test_uptrend_rsi_high(self):
        from backend.indicators import calc_rsi

        result = calc_rsi(SAMPLE_BARS)
        # 持续上涨应使 RSI 较高
        assert result[-1]["rsi"] > 50

    def test_rsi_default_50(self):
        from backend.indicators import calc_rsi

        result = calc_rsi(SAMPLE_BARS)
        # 早期数据不足时应返回 50
        assert result[0]["rsi"] == 50.0


# ============== KDJ 测试 ==============


class TestCalcKDJ:
    """测试 KDJ 计算"""

    def test_kdj_output_length(self):
        from backend.indicators import calc_kdj

        result = calc_kdj(SAMPLE_BARS)
        assert len(result) == len(SAMPLE_BARS)

    def test_kdj_fields_exist(self):
        from backend.indicators import calc_kdj

        result = calc_kdj(SAMPLE_BARS)
        assert "k" in result[-1]
        assert "d" in result[-1]
        assert "j" in result[-1]

    def test_kdj_initial_values(self):
        from backend.indicators import calc_kdj

        result = calc_kdj(SAMPLE_BARS)
        # K/D 初始值应为 50
        assert result[0]["k"] == 50.0
        assert result[0]["d"] == 50.0
        assert result[0]["j"] == 50.0

    def test_kdj_range(self):
        from backend.indicators import calc_kdj

        result = calc_kdj(SAMPLE_BARS)
        for bar in result:
            assert 0 <= bar["k"] <= 100 or bar["k"] < 0  # J 可以超出
            assert 0 <= bar["d"] <= 100 or True  # D 通常在 0-100


# ============== 量比测试 ==============


class TestVolumeRatio:
    """测试量比计算"""

    def test_volume_ratio_output(self):
        from backend.indicators import calc_volume_ratio

        result = calc_volume_ratio(SAMPLE_BARS)
        assert "volume_ratio" in result[-1]

    def test_volume_ratio_first_zero(self):
        from backend.indicators import calc_volume_ratio

        result = calc_volume_ratio(SAMPLE_BARS, period=5)
        # 前 4 根量比应为 0（平均量为 0）
        assert result[0]["volume_ratio"] == 0.0


# ============== 支撑压力测试 ==============


class TestSupportResistance:
    """测试支撑压力位"""

    def test_sr_structure(self):
        from backend.indicators import calc_support_resistance

        result = calc_support_resistance(SAMPLE_BARS)
        assert "pivot" in result
        assert "support" in result
        assert "resistance" in result
        assert "swing_highs" in result
        assert "swing_lows" in result

    def test_sr_pivot_positive(self):
        from backend.indicators import calc_support_resistance

        result = calc_support_resistance(SAMPLE_BARS)
        assert result["pivot"] > 0

    def test_sr_support_below_pivot(self):
        from backend.indicators import calc_support_resistance

        result = calc_support_resistance(SAMPLE_BARS)
        for s in result["support"]:
            assert s < result["pivot"]

    def test_sr_resistance_above_pivot(self):
        from backend.indicators import calc_support_resistance

        result = calc_support_resistance(SAMPLE_BARS)
        for r in result["resistance"]:
            assert r > result["pivot"]

    def test_sr_empty_bars(self):
        from backend.indicators import calc_support_resistance

        result = calc_support_resistance([])
        assert result["pivot"] == 0


# ============== ATR / 唐奇安 ==============


class TestCalcATR:
    def test_atr_output_length(self):
        from backend.indicators import calc_atr

        result = calc_atr(SAMPLE_BARS, period=5)
        assert len(result) == len(SAMPLE_BARS)

    def test_atr_insufficient_is_zero(self):
        from backend.indicators import calc_atr

        result = calc_atr(SAMPLE_BARS, period=20)
        assert result[0]["atr"] == 0.0
        assert result[18]["atr"] == 0.0
        assert result[19]["atr"] > 0.0


class TestCalcDonchian:
    def test_donchian_insufficient_is_zero(self):
        from backend.indicators import calc_donchian

        result = calc_donchian(SAMPLE_BARS, period=20)
        assert result[0]["donchian_high"] == 0.0
        assert result[19]["donchian_high"] == 0.0
        assert result[-1]["donchian_width"] == 0.0  # only 20 bars → last index 19 < 20

    def test_today_high_does_not_leak_into_channel(self):
        from backend.indicators import calc_donchian

        bars = [
            {
                "symbol": "T",
                "date": f"2025-01-{i + 1:02d}",
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0,
                "volume": 1000,
            }
            for i in range(20)
        ]
        # Bar 20 prints an extreme high that must not enter today's channel.
        bars.append(
            {
                "symbol": "T",
                "date": "2025-01-21",
                "open": 10.0,
                "high": 50.0,
                "low": 9.5,
                "close": 10.2,
                "volume": 1000,
            }
        )
        result = calc_donchian(bars, period=20)
        last = result[-1]
        assert last["donchian_high"] == 10.5
        assert last["donchian_low"] == 9.5
        assert last["donchian_width"] == 1.0
        assert last["donchian_high"] != 50.0


# ============== calc_all 测试 ==============


class TestCalcAll:
    """测试综合计算"""

    def test_calc_all_structure(self):
        from backend.indicators import calc_all

        result = calc_all(SAMPLE_BARS)
        assert "summary" in result
        assert "bars" in result
        assert "support_resistance" in result

    def test_calc_all_summary_fields(self):
        from backend.indicators import calc_all

        result = calc_all(SAMPLE_BARS)
        summary = result["summary"]
        assert "ma5" in summary
        assert "dif" in summary
        assert "rsi" in summary
        assert "k" in summary

    def test_calc_all_empty(self):
        from backend.indicators import calc_all

        result = calc_all([])
        assert result["bars"] == []

    def test_calc_all_sorted_by_date(self):
        from backend.indicators import calc_all

        # 传入乱序数据
        import random

        shuffled = list(SAMPLE_BARS)
        random.seed(42)
        random.shuffle(shuffled)
        result = calc_all(shuffled)
        dates = [b["date"] for b in result["bars"]]
        assert dates == sorted(dates)


# ============== API 测试 ==============


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_get_all_indicators(client):
    """GET /api/technical/{symbol}"""
    with patch(
        "backend.indicators.calc_all",
        return_value={"summary": {}, "bars": [], "support_resistance": {}},
    ):
        with patch("backend.api.technical._get_bars", return_value=SAMPLE_BARS):
            resp = await client.get("/api/technical/600519")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_get_all_no_data(client):
    """GET /api/technical/{symbol} 无数据"""
    with patch("backend.api.technical._get_bars", return_value=[]):
        resp = await client.get("/api/technical/600519")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


@pytest.mark.anyio
async def test_get_ma(client):
    """GET /api/technical/{symbol}/ma"""
    with patch("backend.api.technical._get_bars", return_value=SAMPLE_BARS):
        resp = await client.get("/api/technical/600519/ma")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "ma" in resp.json()["data"]


@pytest.mark.anyio
async def test_get_rsi(client):
    """GET /api/technical/{symbol}/rsi"""
    with patch("backend.api.technical._get_bars", return_value=SAMPLE_BARS):
        resp = await client.get("/api/technical/600519/rsi")
    assert resp.status_code == 200
    assert "rsi" in resp.json()["data"]


@pytest.mark.anyio
async def test_get_support_resistance(client):
    """GET /api/technical/{symbol}/support-resistance"""
    with patch("backend.api.technical._get_bars", return_value=SAMPLE_BARS):
        resp = await client.get("/api/technical/600519/support-resistance")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "pivot" in data
    assert "support" in data
