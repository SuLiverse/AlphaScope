"""因子注册中心测试 — 目录/确定性技术因子纯函数 + 临时 SQLite 缓存 + 研究流水线(注入 loader)。"""

from __future__ import annotations

import sqlite3

import pytest

import backend.quant.factor_registry as fr


# ----------------------------- 目录 -----------------------------


class TestCatalog:
    def test_lists_all(self):
        cat = fr.list_factors()
        assert len(cat) >= 15
        ids = {c["id"] for c in cat}
        assert "mom_20" in ids and "news_sentiment" in ids

    def test_filter_by_source(self):
        price = fr.list_factors(source="price")
        assert all(c["source"] == "price" for c in price)
        assert "mom_20" in {c["id"] for c in price}
        soft = fr.list_factors(source="soft")
        assert "news_sentiment" in {c["id"] for c in soft}

    def test_filter_by_category(self):
        tech = fr.list_factors(category="technical")
        assert all(c["category"] == "technical" for c in tech)

    def test_get_factor(self):
        d = fr.get_factor("rsi_14")
        assert d is not None and d.direction == 0


# ----------------------------- 确定性技术因子(纯函数) -----------------------------


def _bars(closes, vols=None, highs=None, lows=None):
    n = len(closes)
    vols = vols or [1000] * n
    highs = highs or [c * 1.02 for c in closes]
    lows = lows or [c * 0.98 for c in closes]
    return [
        {
            "date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
            "open": closes[i],
            "high": highs[i],
            "low": lows[i],
            "close": closes[i],
            "volume": vols[i],
        }
        for i in range(n)
    ]


class TestTechnicalFactors:
    def test_momentum(self):
        closes = [100.0] * 21
        closes[-1] = 110.0
        f = fr.compute_technical_factors(_bars(closes))
        assert f["mom_20"] == pytest.approx(10.0, abs=0.01)

    def test_insufficient_data_returns_none(self):
        f = fr.compute_technical_factors(_bars([100.0, 101.0, 102.0]))
        assert f["mom_60"] is None
        assert f["vol_20"] is None

    def test_rsi_all_up_is_high(self):
        closes = [100.0 + i for i in range(20)]  # 持续上涨
        f = fr.compute_technical_factors(_bars(closes))
        assert f["rsi_14"] == 100.0

    def test_max_drawdown_negative(self):
        closes = [100.0, 120.0, 90.0] + [95.0] * 60
        f = fr.compute_technical_factors(_bars(closes))
        assert f["max_dd_60"] is not None and f["max_dd_60"] <= 0

    def test_range_pos_at_high(self):
        closes = [10.0 + i for i in range(60)]  # 末根是最高
        f = fr.compute_technical_factors(_bars(closes))
        assert f["range_pos_60"] is not None and f["range_pos_60"] > 0.9

    def test_vol_ratio(self):
        vols = [100] * 20 + [200] * 5  # 近 5 日放量
        closes = [10.0] * 25
        f = fr.compute_technical_factors(_bars(closes, vols=vols))
        assert f["vol_ratio"] is not None and f["vol_ratio"] > 1.0

    def test_failure_safe_on_garbage(self):
        f = fr.compute_technical_factors([{"close": "x"}, {}, None])
        assert all(v is None for v in f.values())

    def test_atr_20_and_donchian_width_registered(self):
        ids = {c["id"] for c in fr.list_factors(source="price")}
        assert "atr_20" in ids
        assert "donchian_width_20" in ids
        assert fr.get_factor("atr_20").direction == 0
        assert fr.get_factor("donchian_width_20").direction == 0

    def test_atr_20_insufficient_is_none(self):
        f = fr.compute_technical_factors(_bars([10.0] * 10))
        assert f["atr_20"] is None

    def test_donchian_width_excludes_today(self):
        closes = [10.0] * 25
        highs = [10.5] * 24 + [50.0]
        lows = [9.5] * 25
        f = fr.compute_technical_factors(_bars(closes, highs=highs, lows=lows))
        assert f["donchian_width_20"] is not None
        # Channel is prior 20 highs/lows (all 10.5 / 9.5), width/close = 1/10.
        assert f["donchian_width_20"] == pytest.approx(0.1, abs=0.001)


class TestAtrAlignmentPlan032:
    """Plan 032: _atr_pct 三序列必须同源对齐。

    旧实现用「过滤掉无效 close 之后的 closes」与「未过滤的 highs/lows」
    按下标配对: 历史中只要有一根 close 缺失, 其后所有 TR 的前收盘(PDC)
    错位一根, ATR 数值大幅失真。
    """

    def test_atr_20_matches_manual_per_bar_calc_with_bad_close(self):
        # 25 根: 第 12 根 close=None(坏数据), 第 20 根 close=200(向上跳空), 其余平稳 10 元。
        bars = []
        for i in range(25):
            close = None if i == 12 else (200.0 if i == 20 else 10.0)
            bars.append(
                {
                    "date": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}",
                    "open": 200.0 if i == 20 else 10.0,
                    "high": 204.0 if i == 20 else 10.2,
                    "low": 196.0 if i == 20 else 9.8,
                    "close": close,
                    "volume": 1000,
                }
            )
        # 手工逐 bar 探针(与 027 无未来函数口径一致): 先按 close 有效性过滤,
        # closes/highs/lows 取自同一批 valid bars, 再按下标配对算 TR。
        valid = [b for b in bars if b["close"] is not None]
        assert len(valid) == 24
        closes = [float(b["close"]) for b in valid]
        highs = [float(b["high"]) for b in valid]
        lows = [float(b["low"]) for b in valid]
        trs = []
        for i in range(len(closes) - 20, len(closes)):
            hl = highs[i] - lows[i]
            if i == 0:
                trs.append(max(hl, 0.0))
                continue
            pdc = closes[i - 1]
            trs.append(max(hl, abs(highs[i] - pdc), abs(lows[i] - pdc)))
        expected = round(sum(trs[-20:]) / 20 / closes[-1] * 100.0, 3)
        # 手算锚点: 15×0.4 + 跳空 bar TR 194 + 次日 TR 190.2 + 3×0.4 = 391.4
        # → ATR 19.57 / 收盘 10 × 100 = 195.7(旧错位算法只会给出 7.8)。
        assert expected == 195.7

        f = fr.compute_technical_factors(bars)
        assert f["atr_20"] == expected

    def test_atr_20_unchanged_for_clean_series(self):
        # 防过度修复: 全干净序列(无坏 close)的数值必须与修复前算法完全一致。
        closes = [10.0 + i * 0.1 for i in range(30)]
        bars = _bars(closes)
        highs = [c * 1.02 for c in closes]
        lows = [c * 0.98 for c in closes]
        trs = []
        for i in range(len(closes) - 20, len(closes)):
            hl = highs[i] - lows[i]
            pdc = closes[i - 1]
            trs.append(max(hl, abs(highs[i] - pdc), abs(lows[i] - pdc)))
        expected = round(sum(trs[-20:]) / 20 / closes[-1] * 100.0, 3)
        f = fr.compute_technical_factors(bars)
        assert f["atr_20"] == expected


# ----------------------------- 缓存 + 流水线 -----------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    conn = sqlite3.connect(str(tmp_path / "fr.db"), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    class _FakeDB:
        @property
        def conn(self):
            return conn

    fr._ensured = False
    monkeypatch.setattr(fr, "_db", lambda: _FakeDB())
    yield fr
    fr._ensured = False
    conn.close()


class TestPipelineAndCache:
    def test_compute_for_symbol_with_injected_bars(self, store):
        closes = [100.0 + i * 0.5 for i in range(70)]
        bars = _bars(closes)
        r = store.compute_for_symbol("600519", bars=bars)
        assert r["symbol"] == "600519"
        assert r["bar_count"] == 70
        assert r["factors"]["mom_20"] is not None
        # 缓存写入后可读回
        cached = store.get_cached_vector("600519")
        assert cached is not None and "mom_20" in cached

    def test_compute_for_symbol_via_loader(self, store):
        closes = [50.0 + i for i in range(65)]
        loader = lambda sym: _bars(closes)  # noqa: E731 - 注入不触网
        r = store.compute_for_symbol("000001", loader=loader)
        assert r["bar_count"] == 65

    def test_matrix(self, store):
        closes_a = [100.0 + i for i in range(70)]
        closes_b = [20.0 + i * 0.1 for i in range(70)]
        loader = lambda sym: _bars(closes_a if sym == "AAA" else closes_b)  # noqa: E731
        m = store.compute_matrix(["AAA", "BBB"], loader=loader)
        assert m["count"] == 2
        by = {row["symbol"]: row for row in m["rows"]}
        assert "mom_20" in by["AAA"]
        assert by["AAA"]["bar_count"] == 70

    def test_matrix_failure_safe_row(self, store):
        def loader(sym):
            if sym == "BAD":
                raise RuntimeError("boom")
            return _bars([10.0] * 70)

        m = store.compute_matrix(["GOOD", "BAD"], loader=loader)
        assert m["count"] == 2
        by = {row["symbol"]: row for row in m["rows"]}
        assert by["BAD"]["bar_count"] == 0  # 失败标的降级为空行, 不影响其余

    def test_cache_missing_returns_none(self, store):
        assert store.get_cached_vector("NOPE") is None
