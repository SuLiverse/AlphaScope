"""基金 API 端点测试"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
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

    @pytest.mark.anyio
    async def test_legacy_dca_simulate_formula(self, client):
        # growth=1.1, periods=2, amount=1000: dca = 1000*1.1 + 1000 = 2100,
        # lumpsum = 2000*1.1^2 = 2420, winner = "lumpsum"
        resp = await client.post(
            "/api/funds/dca/simulate",
            json={"amount_per_period": 1000, "periods": 2, "annual_growth_pct": 10},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["dca"]["final_value"] == pytest.approx(2100.0)
        assert data["lumpsum"]["final_value"] == pytest.approx(2420.0)
        assert data["winner"] == "lumpsum"

    @pytest.mark.anyio
    async def test_legacy_dca_no_date_branch_formula(self, client):
        # 无日期分支同样走 _legacy_dca_result，数值与手工抽查一致
        resp = await client.post(
            "/api/fund-dca/simulate",
            json={"fund_code": "000001", "amount": 1000, "periods": 2, "annual_growth_pct": 10},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["dca"]["final_value"] == pytest.approx(2100.0)
        assert data["lumpsum"]["final_value"] == pytest.approx(2420.0)
        assert data["winner"] == "lumpsum"


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

    @pytest.mark.anyio
    async def test_create_portfolio_db_failure_returns_success_false(self, client):
        # 成功路径（不 fail）: 仍返回 success=True，防止过度 mock
        ok_mgr = PortfolioManager(db=_FlakyDb())
        with patch("backend.api.funds._get_portfolio_mgr", return_value=ok_mgr):
            resp = await client.post(
                "/api/fund-portfolio",
                json={"name": "正常组合", "description": "desc"},
            )
        assert resp.json()["success"] is True

        # DB 事务抛错: 显式失败而非假成功
        db = _FlakyDb()
        mgr = PortfolioManager(db=db)  # 构造消耗第 1 次事务（CREATE TABLE）
        db.fail_from(2)  # create 的 INSERT 事务抛错
        with patch("backend.api.funds._get_portfolio_mgr", return_value=mgr):
            resp = await client.post(
                "/api/fund-portfolio",
                json={"name": "失败组合", "description": "desc"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"]
        assert data["error_code"] == "PORTFOLIO_SAVE_FAILED"

    @pytest.mark.anyio
    async def test_update_portfolio_db_failure_returns_success_false(self, client):
        # 成功路径（不 fail）: 仍返回 success=True，防止过度 mock
        ok_db = _FlakyDb()
        ok_mgr = PortfolioManager(db=ok_db)
        ok_created = ok_mgr.create(name="正常组合")
        with patch("backend.api.funds._get_portfolio_mgr", return_value=ok_mgr):
            resp = await client.put(
                f"/api/fund-portfolio/{ok_created['id']}",
                json={"name": "新名字"},
            )
        assert resp.json()["success"] is True

        # DB 事务抛错: 显式失败而非假成功
        db = _FlakyDb()
        mgr = PortfolioManager(db=db)  # 第 1 次事务: CREATE TABLE
        created = mgr.create(name="原组合")  # 第 2 次事务: INSERT 成功
        db.fail_from(4)  # 第 3 次事务（get）成功, 第 4 次（UPDATE）抛错
        with patch("backend.api.funds._get_portfolio_mgr", return_value=mgr):
            resp = await client.put(
                f"/api/fund-portfolio/{created['id']}",
                json={"name": "新名字"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error"]
        assert data["error_code"] == "PORTFOLIO_SAVE_FAILED"


class _FlakyDb:
    """共享内存 SQLite 库，达到 fail_from 次数后 transaction() 抛错。"""

    def __init__(self):
        self._conn = sqlite3.connect(":memory:")
        self._conn.row_factory = sqlite3.Row
        self._calls = 0
        self._fail_from = 0

    def fail_from(self, n: int):
        self._fail_from = n

    @contextmanager
    def transaction(self):
        self._calls += 1
        if self._fail_from and self._calls >= self._fail_from:
            raise RuntimeError("disk full")
        yield self._conn


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
