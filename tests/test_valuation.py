"""M2 · 估值建模 (DCF / Comps / LBO / 三表) 测试(纯计算，不联网)。"""

from __future__ import annotations

import types

from backend.valuation import (
    build_comps_table,
    compute_dcf,
    compute_wacc,
    features_from_fundamentals,
    project_three_stmt,
    quick_lbo,
    value_stock,
    value_symbol,
)

BASE = {
    "price": 18.5,
    "market_cap_yi": 260,
    "shares_outstanding_yi": 14.0,
    "revenue_latest_yi": 52,
    "net_margin": 12.5,
    "pe": 35,
    "pb": 2.8,
    "total_debt_yi": 10,
    "cash_yi": 40,
    "fcf_latest_yi": 6.5,
    "ebitda_yi": 10,
    "equity_yi": 92,
    "name": "测试公司",
}


class TestWaccDcf:
    def test_wacc_components(self):
        w = compute_wacc(beta=1.0)
        # k_e = rf + beta*erp = 0.025 + 0.06 = 0.085
        assert abs(w["cost_of_equity"] - 0.085) < 1e-9
        assert 0 < w["wacc"] < 0.15

    def test_dcf_basic(self):
        dcf = compute_dcf(BASE)
        assert dcf["intrinsic_per_share"] > 0
        assert dcf["base_fcf_yi"] == 6.5
        assert len(dcf["projected_fcf_yi"]) == 10  # 5 + 5 年
        assert len(dcf["sensitivity_table"]["values_per_share"]) == 5
        assert len(dcf["sensitivity_table"]["values_per_share"][0]) == 5
        assert dcf["verdict"]  # 非空结论

    def test_dcf_fallback_when_no_fcf(self):
        # 无 fcf / 无营收 → 用 market_cap * 5% 兜底，不崩
        dcf = compute_dcf({"market_cap_yi": 100, "shares_outstanding_yi": 10})
        assert dcf["base_fcf_yi"] == 5.0
        assert dcf["intrinsic_per_share"] >= 0

    def test_dcf_higher_growth_lifts_value(self):
        low = compute_dcf(BASE, {"stage1_growth": 0.05})
        high = compute_dcf(BASE, {"stage1_growth": 0.20})
        assert high["intrinsic_per_share"] > low["intrinsic_per_share"]


class TestComps:
    def test_empty_peers(self):
        assert "error" in build_comps_table({"pe": 10}, [])

    def test_cheap_when_below_peers(self):
        peers = [
            {"name": "A", "pe": 30},
            {"name": "B", "pe": 40},
            {"name": "C", "pe": 50},
        ]
        out = build_comps_table({"pe": 10, "price": 5}, peers)
        assert out["target_percentile"]["pe"] == 0  # 低于所有同行
        assert "便宜" in out["valuation_verdict"]

    def test_implied_price_from_pe(self):
        peers = [{"name": "A", "pe": 20}, {"name": "B", "pe": 20}]
        out = build_comps_table({"pe": 25, "eps": 2.0}, peers)
        assert out["implied_price"]["via_median_pe"] == 40.0  # 20 * 2.0


class TestLboAndThreeStmt:
    def test_lbo_returns_irr_and_schedule(self):
        lbo = quick_lbo(BASE)
        assert "irr_pct" in lbo
        assert lbo["debt_schedule"][0] >= lbo["debt_schedule"][-1]  # 债务下降
        assert lbo["verdict"]

    def test_three_stmt_five_years(self):
        stmt = project_three_stmt(BASE)
        assert stmt["years"] == ["Y1", "Y2", "Y3", "Y4", "Y5"]
        assert len(stmt["income_statement"]["net_income"]) == 5

    def test_three_stmt_needs_revenue(self):
        assert "error" in project_three_stmt({"revenue_latest_yi": 0})


class TestValueStock:
    def test_value_stock_shape(self):
        out = value_stock(BASE, peers=[{"name": "A", "pe": 30}])
        assert set(out) >= {"dcf", "comps", "lbo", "three_statement", "summary"}
        assert out["summary"]["dcf_intrinsic_per_share"] == out["dcf"]["intrinsic_per_share"]

    def test_value_stock_no_peers(self):
        out = value_stock(BASE)
        assert "note" in out["comps"]


class TestAdapter:
    def test_features_from_fundamentals(self, monkeypatch):
        import backend.fundamentals as F

        period = types.SimpleNamespace(
            revenue_yi=52.0,
            net_profit_yi=6.5,
            roe_pct=11.8,
            yoy_revenue=18.0,
            gross_margin_pct=35.0,
            debt_ratio_pct=30.0,
        )
        self_row = types.SimpleNamespace(
            name="测试公司",
            symbol="600519",
            total_mcap_yi=260.0,
            pe=35.0,
            pb=2.8,
            roe_pct=12.0,
            yoy_revenue_pct=18.0,
            is_self=True,
        )
        peer_row = types.SimpleNamespace(
            name="同行A",
            symbol="600520",
            total_mcap_yi=300.0,
            pe=30.0,
            pb=2.5,
            roe_pct=14.0,
            yoy_revenue_pct=20.0,
            is_self=False,
        )
        monkeypatch.setattr(F, "fetch_financial_summary", lambda s, periods=4: [period])
        monkeypatch.setattr(F, "fetch_industry_peers", lambda s, top_k=8: ("白酒", [self_row, peer_row]))

        feats, peers = features_from_fundamentals("600519")
        assert feats["revenue_latest_yi"] == 52.0
        assert feats["net_margin"] == 12.5  # 6.5/52*100
        assert feats["market_cap_yi"] == 260.0  # 来自 is_self 行
        assert feats["pe"] == 35.0
        assert len(peers) == 1 and peers[0]["name"] == "同行A"

    def test_value_symbol_end_to_end(self, monkeypatch):
        import backend.fundamentals as F

        period = types.SimpleNamespace(
            revenue_yi=52.0,
            net_profit_yi=6.5,
            roe_pct=11.8,
            yoy_revenue=18.0,
            gross_margin_pct=35.0,
            debt_ratio_pct=30.0,
        )
        monkeypatch.setattr(F, "fetch_financial_summary", lambda s, periods=4: [period])
        monkeypatch.setattr(F, "fetch_industry_peers", lambda s, top_k=8: ("行业", []))

        out = value_symbol("600519")
        assert out["symbol"] == "600519"
        assert out["degraded"] is False
        assert out["summary"]["dcf_verdict"]

    def test_features_graceful_on_failure(self, monkeypatch):
        import backend.fundamentals as F

        def boom(*a, **k):
            raise RuntimeError("network down")

        monkeypatch.setattr(F, "fetch_financial_summary", boom)
        monkeypatch.setattr(F, "fetch_industry_peers", boom)
        feats, peers = features_from_fundamentals("600519")
        assert feats["ticker"] == "600519"  # 不崩，返回最小 features
        assert peers == []
