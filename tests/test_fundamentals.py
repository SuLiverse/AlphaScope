"""Tests for Fundamental Analysis — 估值/盈利质量/现金流/资产负债/综合评分 + API"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


# ============== 估值指标测试 ==============


class TestValuationMetrics:
    """测试 calc_valuation_metrics"""

    def test_basic(self):
        from backend.fundamentals import calc_valuation_metrics

        result = calc_valuation_metrics(pe=20, pb=3, revenue_yi=100, net_profit_yi=20, market_cap_yi=400)
        assert result["pe"] == 20
        assert result["pb"] == 3
        assert result["ps"] == 4.0  # 400/100
        assert result["valuation_level"] == "合理"

    def test_low_valuation(self):
        from backend.fundamentals import calc_valuation_metrics

        result = calc_valuation_metrics(pe=10)
        assert result["valuation_level"] == "低估"

    def test_high_valuation(self):
        from backend.fundamentals import calc_valuation_metrics

        result = calc_valuation_metrics(pe=80)
        assert result["valuation_level"] == "高估"

    def test_ps_calculation(self):
        from backend.fundamentals import calc_valuation_metrics

        result = calc_valuation_metrics(market_cap_yi=500, revenue_yi=100)
        assert result["ps"] == 5.0

    def test_no_data(self):
        from backend.fundamentals import calc_valuation_metrics

        result = calc_valuation_metrics()
        assert result["pe"] == 0
        assert result["valuation_level"] == "unknown"


# ============== 盈利质量测试 ==============


class TestEarningsQuality:
    """测试 assess_earnings_quality"""

    def test_high_quality(self):
        from backend.fundamentals import assess_earnings_quality

        result = assess_earnings_quality(net_profit=100, operating_cf=120, non_recurring=5)
        assert result["ocf_to_profit_ratio"] == 1.2
        assert result["quality_score"] >= 70
        assert result["quality_level"] in ("优秀", "良好")

    def test_low_quality(self):
        from backend.fundamentals import assess_earnings_quality

        result = assess_earnings_quality(net_profit=100, operating_cf=30, non_recurring=50)
        assert result["ocf_to_profit_ratio"] == 0.3
        assert len(result["warnings"]) > 0

    def test_no_data(self):
        from backend.fundamentals import assess_earnings_quality

        result = assess_earnings_quality()
        assert result["quality_score"] == 0
        assert result["quality_level"] in ("unknown", "较差")


# ============== 现金流分析测试 ==============


class TestCashFlow:
    """测试 analyze_cash_flow"""

    def test_growth_pattern(self):
        from backend.fundamentals import analyze_cash_flow

        result = analyze_cash_flow(operating_cf=100, investing_cf=-80, financing_cf=30)
        assert result["cf_pattern"] == "成长型"
        assert result["free_cash_flow"] == 20
        assert result["cf_score"] >= 60

    def test_mature_pattern(self):
        from backend.fundamentals import analyze_cash_flow

        result = analyze_cash_flow(operating_cf=100, investing_cf=-50, financing_cf=-30)
        assert result["cf_pattern"] == "成熟型"

    def test_warning_pattern(self):
        from backend.fundamentals import analyze_cash_flow

        result = analyze_cash_flow(operating_cf=-10, investing_cf=-20, financing_cf=50)
        assert result["cf_pattern"] == "预警型"
        assert result["cf_score"] < 30

    def test_coverage(self):
        from backend.fundamentals import analyze_cash_flow

        result = analyze_cash_flow(operating_cf=120, net_profit=100)
        assert result["cf_coverage"] == 1.2


# ============== 资产负债测试 ==============


class TestBalanceSheet:
    """测试 analyze_balance_sheet"""

    def test_healthy(self):
        from backend.fundamentals import analyze_balance_sheet

        result = analyze_balance_sheet(debt_ratio=30, current_ratio=2.5, roa=12)
        assert result["health_score"] >= 80
        assert result["health_level"] == "优秀"

    def test_risky(self):
        from backend.fundamentals import analyze_balance_sheet

        result = analyze_balance_sheet(debt_ratio=75, current_ratio=0.8, roa=1)
        assert result["health_score"] < 40
        assert len(result["warnings"]) > 0

    def test_no_data(self):
        from backend.fundamentals import analyze_balance_sheet

        result = analyze_balance_sheet()
        assert result["health_score"] == 0


# ============== 综合评分测试 ==============


class TestFundamentalScore:
    """测试 compute_fundamental_score"""

    def test_high_score(self):
        from backend.fundamentals import compute_fundamental_score

        result = compute_fundamental_score(
            valuation={"valuation_level": "低估"},
            earnings={"quality_score": 90},
            cashflow={"cf_score": 80},
            balance={"health_score": 85},
        )
        assert result["total_score"] >= 80
        assert result["grade"] == "A"

    def test_low_score(self):
        from backend.fundamentals import compute_fundamental_score

        result = compute_fundamental_score(
            valuation={"valuation_level": "高估"},
            earnings={"quality_score": 20},
            cashflow={"cf_score": 10},
            balance={"health_score": 15},
        )
        assert result["total_score"] < 50
        assert result["grade"] == "D"

    def test_default(self):
        from backend.fundamentals import compute_fundamental_score

        result = compute_fundamental_score()
        assert 0 <= result["total_score"] <= 100
        assert result["grade"] in ("A", "B", "C", "D")


# ============== API 测试 ==============


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_get_valuation(client):
    """GET /api/fundamentals/{symbol}/valuation"""
    mock_data = MagicMock()
    mock_data.has_error = False
    mock_data.financials = []
    mock_data.peers = []

    with patch("backend.fundamentals.load_fundamentals", return_value=mock_data):
        resp = await client.get("/api/fundamentals/600519/valuation")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "pe" in resp.json()["data"]


@pytest.mark.anyio
async def test_get_shareholders(client):
    """GET /api/fundamentals/{symbol}/shareholders"""
    with (
        patch("backend.fundamentals.fetch_top_holders", return_value=[]),
        patch("backend.fundamentals.fetch_circulate_holders", return_value=[]),
        patch("backend.fundamentals.fetch_inst_changes", return_value=[]),
    ):
        resp = await client.get("/api/fundamentals/600519/shareholders")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "top_holders" in resp.json()["data"]


@pytest.mark.anyio
async def test_get_peers(client):
    """GET /api/fundamentals/{symbol}/peers"""
    with patch("backend.fundamentals.fetch_industry_peers", return_value=("白酒", [])):
        resp = await client.get("/api/fundamentals/600519/peers")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["industry"] == "白酒"
