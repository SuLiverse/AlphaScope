"""基金 API 端点测试"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app
from backend.funds.portfolio import PortfolioManager


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ========== 基金搜索 ==========


class TestFundSearch:
    """基金搜索端点"""

    @pytest.mark.anyio
    async def test_search_empty_keyword(self, client):
        resp = await client.get("/api/funds/search?keyword=")
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["total"] == 0

    @pytest.mark.anyio
    async def test_search_with_results(self, client):
        mock_provider = AsyncMock()
        mock_provider.search.return_value = [
            {"code": "000001", "name": "华夏成长"},
        ]
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.get("/api/funds/search?keyword=华夏")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["total"] == 1

    @pytest.mark.anyio
    async def test_search_code_keeps_info_result_when_keyword_search_fails(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_info.return_value = {
            "code": "000001",
            "name": "华夏成长混合",
            "fund_type": "混合型",
            "company": "华夏基金",
        }
        mock_provider.search.side_effect = RuntimeError("search upstream down")
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.get("/api/funds/search?keyword=000001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["error_code"] == "FUND_SEARCH_DEGRADED"
        assert data["data"]["total"] == 1
        assert data["data"]["funds"][0]["code"] == "000001"
        assert data["data"]["funds"][0]["name"] == "华夏成长混合"
        assert data["data"]["degraded"] is True
        assert data["data"]["source_status"] == "code_lookup_search_unavailable"


# ========== 基金信息 ==========


class TestFundInfo:
    """基金信息端点"""

    @pytest.mark.anyio
    async def test_get_fund_info(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_info.return_value = {
            "code": "000001",
            "name": "华夏成长",
            "fund_type": "stock",
        }
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.get("/api/funds/000001")
        assert resp.status_code == 200
        assert resp.json()["data"]["code"] == "000001"

    @pytest.mark.anyio
    async def test_get_fund_not_found(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_info.return_value = None
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.get("/api/funds/999999")
        assert resp.json()["success"] is False
        assert resp.json()["error_code"] == "FUND_NOT_FOUND"


# ========== 基金净值 ==========


class TestFundNav:
    """基金净值端点"""

    @pytest.mark.anyio
    async def test_get_nav(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_nav_history.return_value = [
            {"date": "2024-01-01", "nav": 1.0},
            {"date": "2024-01-02", "nav": 1.01},
        ]
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.get("/api/funds/000001/nav")
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 2


# ========== 基金指标 ==========


class TestFundMetrics:
    """基金指标端点"""

    @pytest.mark.anyio
    async def test_get_metrics(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_nav_history.return_value = [
            {"date": f"2024-01-{i:02d}", "nav": 1.0 + i * 0.01} for i in range(1, 31)
        ]
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.get("/api/funds/000001/metrics")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "total_return" in data
        assert "sharpe_ratio" in data

    @pytest.mark.anyio
    async def test_get_metrics_no_data(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_nav_history.return_value = []
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.get("/api/funds/000001/metrics")
        assert resp.json()["success"] is False
        assert resp.json()["error_code"] == "FUND_NO_DATA"


# ========== 定投模拟 ==========


class TestDCASimulation:
    """定投模拟端点"""

    @pytest.mark.anyio
    async def test_simulate_dca(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_nav_history.return_value = [
            {"date": f"2024-{m:02d}-01", "nav": 1.0 + m * 0.01} for m in range(1, 13)
        ]
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.post(
                "/api/fund-dca/simulate",
                json={
                    "fund_code": "000001",
                    "amount": 1000,
                    "frequency": "monthly",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["total_invested"] > 0

    @pytest.mark.anyio
    async def test_simulate_dca_no_data(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_nav_history.return_value = []
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.post(
                "/api/fund-dca/simulate",
                json={
                    "fund_code": "000001",
                    "amount": 1000,
                    "frequency": "monthly",
                    "start_date": "2024-01-01",
                    "end_date": "2024-12-31",
                },
            )
        assert resp.json()["success"] is False
        assert resp.json()["error_code"] == "FUND_NO_DATA"


# ========== 组合管理 ==========


class TestPortfolioCRUD:
    """组合 CRUD 端点"""

    @pytest.mark.anyio
    async def test_portfolio_crud(self, client):
        # 创建
        with patch(
            "backend.api.funds._get_portfolio_mgr",
            return_value=PortfolioManager(db=None),
        ):
            resp = await client.post(
                "/api/fund-portfolio",
                json={"name": "测试组合", "description": "desc"},
            )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        # 列出（空 db，返回空）
        with patch(
            "backend.api.funds._get_portfolio_mgr",
            return_value=PortfolioManager(db=None),
        ):
            resp = await client.get("/api/fund-portfolio")
        assert resp.status_code == 200
        assert resp.json()["success"] is True


# ========== 定投计划 ==========


class TestDCAPlans:
    """定投计划端点"""

    @pytest.mark.anyio
    async def test_create_and_list_plans(self, client):
        # 先清空
        import backend.api.funds as funds_mod

        funds_mod._dca_plans.clear()

        resp = await client.post(
            "/api/fund-dca/plans",
            json={
                "fund_code": "000001",
                "fund_name": "华夏成长",
                "amount": 1000,
                "frequency": "monthly",
                "start_date": "2024-01-01",
            },
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True
        assert resp.json()["data"]["fund_code"] == "000001"

        resp = await client.get("/api/fund-dca/plans")
        assert resp.json()["data"]["total"] == 1


# ========== 组合再平衡 ==========


class TestRebalance:
    """组合再平衡端点"""

    @pytest.mark.anyio
    async def test_rebalance_not_found(self, client):
        mock_mgr = PortfolioManager(db=None)
        with patch("backend.api.funds._get_portfolio_mgr", return_value=mock_mgr):
            resp = await client.post(
                "/api/fund-portfolio/rebalance",
                json={
                    "portfolio_id": "nonexistent",
                    "target_weights": {"000001": 0.6, "000002": 0.4},
                },
            )
        assert resp.json()["success"] is False
        assert resp.json()["error_code"] == "PORTFOLIO_NOT_FOUND"


# ========== 基金报告 ==========


class TestFundReport:
    """基金报告生成端点"""

    @pytest.mark.anyio
    async def test_generate_report(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_info.return_value = {
            "code": "000001",
            "name": "华夏成长",
            "fund_type": "stock",
            "manager": "张三",
            "company": "华夏基金",
        }
        mock_provider.get_nav_history.return_value = [
            {"date": f"2024-01-{i:02d}", "nav": 1.0 + i * 0.01} for i in range(1, 31)
        ]
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.post(
                "/api/fund-reports/generate",
                json={"fund_code": "000001", "include_metrics": True},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "华夏成长" in data["data"]["content"]
        assert "total_return" in data["data"]["metrics"]

    @pytest.mark.anyio
    async def test_generate_report_with_unbounded_sharpe_ratio(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_info.return_value = {
            "code": "000001",
            "name": "stable growth",
            "fund_type": "stock",
        }
        mock_provider.get_nav_history.return_value = [
            {"date": f"2024-01-{i:02d}", "nav": float(2**i)} for i in range(1, 31)
        ]
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.post(
                "/api/fund-reports/generate",
                json={"fund_code": "000001", "include_metrics": True},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["metrics"]["sharpe_ratio"] is None
        assert "N/A" in data["data"]["content"]

    @pytest.mark.anyio
    async def test_report_fund_not_found(self, client):
        mock_provider = AsyncMock()
        mock_provider.get_info.return_value = None
        with patch("backend.api.funds.get_provider", return_value=mock_provider):
            resp = await client.post(
                "/api/fund-reports/generate",
                json={"fund_code": "999999"},
            )
        assert resp.json()["success"] is False
        assert resp.json()["error_code"] == "FUND_NOT_FOUND"
