"""筹码分布(成本分布)测试 — 换手率扩散模型。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

import pytest


def _make_bars(n: int, start: float = 100.0, drift: float = 0.2, with_turnover: bool = True):
    """确定性 OHLCV(+可选换手率)。固定基准日期,完全可复现。"""
    base = datetime(2024, 1, 1)
    bars = []
    for i in range(n):
        close = max(1.0, start + drift * i + 3.0 * math.sin(i / 6.0))
        low = close - 1.5
        high = close + 1.5
        bar = {
            "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
            "open": round(close - 0.3, 2),
            "high": round(high, 2),
            "low": round(max(0.5, low), 2),
            "close": round(close, 2),
            "volume": 10000 + (i % 7) * 1500,
        }
        if with_turnover:
            bar["turnover"] = 2.0 + (i % 5) * 0.5  # 换手率 %(2.0~4.0)
        bars.append(bar)
    return bars


class TestInsufficient:
    def test_too_few_bars_is_failsafe(self):
        from backend.quant.chip_distribution import (
            compute_chip_distribution,
            INSUFFICIENT,
        )

        r = compute_chip_distribution(_make_bars(10), symbol="T")
        assert r.status == INSUFFICIENT
        assert r.levels == []
        # 不抛异常,字段齐全
        assert "需≥" in r.note

    def test_empty_bars(self):
        from backend.quant.chip_distribution import (
            compute_chip_distribution,
            INSUFFICIENT,
        )

        r = compute_chip_distribution([], symbol="T")
        assert r.status == INSUFFICIENT


class TestDistributionContract:
    def test_basic_shape(self):
        from backend.quant.chip_distribution import compute_chip_distribution, OK

        r = compute_chip_distribution(_make_bars(120), symbol="600519")
        assert r.status == OK
        assert r.symbol == "600519"
        assert r.levels
        assert r.avg_cost > 0
        assert 0.0 <= r.profit_ratio <= 100.0

    def test_levels_sum_to_about_100(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        r = compute_chip_distribution(_make_bars(150), symbol="T")
        total_pct = sum(lvl["pct"] for lvl in r.levels)
        # 截断 1e-6 以下的极小桶后,总和应非常接近 100
        assert 98.0 <= total_pct <= 100.5

    def test_avg_cost_within_price_range(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        bars = _make_bars(120)
        r = compute_chip_distribution(bars, symbol="T")
        p_min = min(b["low"] for b in bars)
        p_max = max(b["high"] for b in bars)
        assert p_min <= r.avg_cost <= p_max

    def test_bands_nested_and_ordered(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        r = compute_chip_distribution(_make_bars(150), symbol="T")
        assert r.range_70_low <= r.range_70_high
        assert r.range_90_low <= r.range_90_high
        # 90% 带应包住 70% 带(更宽)
        assert r.range_90_low <= r.range_70_low + 1e-6
        assert r.range_90_high >= r.range_70_high - 1e-6
        # 集中度:90% 带宽 >= 70% 带宽
        assert r.concentration_90 >= r.concentration_70 - 1e-6


class TestProfitRatioSemantics:
    def test_price_above_all_chips_is_high_profit(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        bars = _make_bars(120, start=100.0, drift=0.0)  # 大致围绕 100 波动
        r = compute_chip_distribution(bars, symbol="T", current_price=300.0)
        assert r.profit_ratio > 95.0  # 现价远高于全部成本 → 几乎全部获利

    def test_price_below_all_chips_is_low_profit(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        bars = _make_bars(120, start=100.0, drift=0.0)
        r = compute_chip_distribution(bars, symbol="T", current_price=10.0)
        assert r.profit_ratio < 5.0  # 现价远低于全部成本 → 几乎全部套牢


class TestModelSelection:
    def test_real_turnover_model(self):
        from backend.quant.chip_distribution import (
            compute_chip_distribution,
            MODEL_TURNOVER,
        )

        r = compute_chip_distribution(_make_bars(120, with_turnover=True), symbol="T")
        assert r.model == MODEL_TURNOVER

    def test_volume_proxy_model(self):
        from backend.quant.chip_distribution import (
            compute_chip_distribution,
            MODEL_VOLUME_PROXY,
        )

        r = compute_chip_distribution(_make_bars(120, with_turnover=False), symbol="T")
        assert r.model == MODEL_VOLUME_PROXY
        assert "代理" in r.note


class TestDenseLevels:
    def test_support_below_resistance_above(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        bars = _make_bars(150, start=100.0, drift=0.1)
        cur = bars[-1]["close"]
        r = compute_chip_distribution(bars, symbol="T", current_price=cur)
        if r.support_price > 0:
            assert r.support_price < cur
        if r.resistance_price > 0:
            assert r.resistance_price > cur


class TestRobustness:
    def test_determinism(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        bars = _make_bars(150)
        a = compute_chip_distribution(bars, symbol="T").to_dict()
        b = compute_chip_distribution(bars, symbol="T").to_dict()
        assert a == b

    def test_to_dict_has_disclaimer(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        d = compute_chip_distribution(_make_bars(120), symbol="T").to_dict()
        assert "不预测价格" in d["disclaimer"]
        assert "levels" in d and isinstance(d["levels"], list)

    def test_skips_bad_close_rows(self):
        from backend.quant.chip_distribution import compute_chip_distribution, OK

        bars = _make_bars(120)
        bars.insert(5, {"date": "2024-01-05x", "close": 0, "high": 0, "low": 0, "volume": 0})
        bars.insert(9, {"date": "2024-01-09x", "close": "nan", "high": 1, "low": 1, "volume": 1})
        r = compute_chip_distribution(bars, symbol="T")
        assert r.status == OK
        assert r.bars_used == 120  # 两条坏行被跳过

    def test_flat_price_concentrates(self):
        from backend.quant.chip_distribution import compute_chip_distribution

        # 完全平盘 → 筹码高度集中,集中度数值很小
        base = __import__("datetime").datetime(2024, 1, 1)
        from datetime import timedelta

        bars = [
            {
                "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": 50.0,
                "high": 50.2,
                "low": 49.8,
                "close": 50.0,
                "volume": 10000,
                "turnover": 2.0,
            }
            for i in range(60)
        ]
        r = compute_chip_distribution(bars, symbol="T")
        assert r.concentration_90 < 5.0  # 平盘 → 90% 带宽相对均价很窄


class TestApiPayload:
    def test_local_chip_payload_uses_raw_turnover_bars(self):
        pytest.importorskip("fastapi")
        from unittest.mock import patch

        from backend.api.quant import (
            ChipDistributionRequestBody,
            _run_chip_distribution_local,
        )

        bars = _make_bars(160, with_turnover=True)
        body = ChipDistributionRequestBody(
            symbol="600519",
            start_date="2024-01-01",
            end_date="2024-12-31",
            price_levels=100,
        )
        with (
            patch("backend.price_store.get_prices", return_value=bars),
            patch("backend.price_store.normalize_symbol", return_value="600519"),
        ):
            payload = _run_chip_distribution_local(body)

        assert payload["mode"] == "chip_distribution"
        assert payload["run_id"].startswith("chip-")
        assert payload["status"] == "ok"
        assert payload["model"] == "turnover"  # 原始 bar 含换手率
        assert payload["data_source"] == "local_price_store"
        assert payload["bar_count"] == 160
        assert 0.0 <= payload["profit_ratio"] <= 100.0
        assert payload["levels"]
        assert "不预测价格" in payload["disclaimer"]

    def test_local_chip_falls_back_when_raw_too_short(self):
        pytest.importorskip("fastapi")
        from unittest.mock import patch

        from backend.api.quant import (
            ChipDistributionRequestBody,
            _run_chip_distribution_local,
        )

        body = ChipDistributionRequestBody(symbol="600519", start_date="2024-01-01", end_date="2024-12-31")
        cleaned = [
            {
                "date": f"2024-02-{i + 1:02d}",
                "open": 50,
                "high": 51,
                "low": 49,
                "close": 50,
                "volume": 1000,
            }
            for i in range(60)
        ]
        with (
            patch("backend.price_store.get_prices", return_value=[]),  # 原始取数为空
            patch("backend.price_store.normalize_symbol", return_value="600519"),
            patch("backend.api.quant_core._load_local_bars", return_value=(cleaned, "provider")) as mock_load,
        ):
            payload = _run_chip_distribution_local(body)

        mock_load.assert_called_once()
        assert payload["data_source"] == "provider"
        # 清洗后的 bar 无换手率 → 量能代理
        assert payload["model"] == "volume_proxy"
