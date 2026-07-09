"""量化 API 端点测试 - 本地回测引擎。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class TestQuantStatus:
    """本地量化能力状态端点。"""

    @pytest.mark.anyio
    async def test_status_is_local_and_runnable(self, client):
        resp = await client.get("/api/quant/status")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["connected"] is True
        assert data["data"]["execution_mode"] == "local"
        assert data["data"]["source_status"] == "local"
        assert data["data"]["can_run_backtest"] is True
        assert data["data"]["local_backtest_available"] is True
        assert data["data"]["capabilities"]["stock_pool_parse"] is True
        assert data["data"]["external_connected"] is False
        assert data["data"]["external_error"] is None
        assert data["data"]["degraded"] is False
        assert data["error_code"] is None


class TestQuantStrategies:
    """本地策略列表端点。"""

    @pytest.mark.anyio
    async def test_strategies_list_local(self, client):
        resp = await client.get("/api/quant/strategies")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["execution_mode"] == "local"
        assert data["data"]["degraded"] is False
        names = [strategy["name"] for strategy in data["data"]["strategies"]]
        assert "macd_momentum" in names
        assert "ma_crossover" in names
        assert "rsi_reversal" in names

    @pytest.mark.anyio
    async def test_strategy_detail(self, client):
        resp = await client.get("/api/quant/strategies/macd_momentum")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "macd_momentum"
        assert data["data"]["source"] == "local"

    @pytest.mark.anyio
    async def test_strategy_detail_not_found(self, client):
        resp = await client.get("/api/quant/strategies/not-a-strategy")

        assert resp.status_code == 404


class TestQuantReload:
    """本地策略重载端点。"""

    @pytest.mark.anyio
    async def test_reload_local_strategies(self, client):
        resp = await client.post("/api/quant/strategies/reload")

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["execution_mode"] == "local"
        assert data["data"]["reloaded"] >= 3
        assert data["data"]["local_backtest_available"] is True


class TestStockPoolExport:
    @pytest.mark.anyio
    async def test_stock_pool_export_returns_csv(self, client):
        resp = await client.post(
            "/api/quant/stock-pool/export",
            json={"text": "600519 Maotai\n300750 CATL\n600519 duplicate"},
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "alphascope-stock-pool.csv" in resp.headers["content-disposition"]
        lines = resp.text.strip().splitlines()
        assert lines[0] == "symbol,name,market,exchange,source"
        assert len(lines) == 3
        assert lines[1].startswith("600519,")
        assert lines[2].startswith("300750,")

    @pytest.mark.anyio
    async def test_stock_pool_export_rejects_empty_pool(self, client):
        resp = await client.post(
            "/api/quant/stock-pool/export",
            json={"text": "no symbols here"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error_code"] == "STOCK_POOL_EMPTY"


class TestQuantBacktest:
    """本地回测端点。"""

    @pytest.mark.anyio
    async def test_backtest_runs_local_engine(self, client):
        resp = await client.post(
            "/api/quant/backtest",
            json={
                "strategy_id": "macd_momentum",
                "symbol": "600519",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "initial_capital": 1000000,
                "allow_preview_data": True,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["status"] == "completed"
        assert data["data"]["source_status"] == "local"
        assert data["data"]["engine"] == "local"
        assert data["data"]["run_id"].startswith("local-")
        assert data["data"]["metrics"]["trade_count"] >= 0
        assert data["data"]["summary"]["bar_count"] >= 30
        assert data["data"]["summary"]["data_source"] in {
            "local_price_store",
            "provider",
            "local_preview",
        }
        assert isinstance(data["data"]["equity_curve"], list)

    @pytest.mark.anyio
    async def test_backtest_unknown_strategy_returns_clear_error(self, client):
        resp = await client.post(
            "/api/quant/backtest",
            json={
                "strategy_id": "not-a-strategy",
                "symbol": "600519",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["error_code"] == "LOCAL_BACKTEST_ERROR"
        assert "策略不存在" in data["error"]

    @pytest.mark.anyio
    async def test_backtest_rejects_preview_without_opt_in(self, client, monkeypatch):
        """无真实行情且未 allow_preview_data 时不得静默用合成 K 线。"""
        import backend.api.quant as quant_api

        monkeypatch.setattr(
            quant_api,
            "_load_local_bars",
            lambda *a, **k: ([], "unavailable"),
        )
        resp = await client.post(
            "/api/quant/backtest",
            json={
                "strategy_id": "macd_momentum",
                "symbol": "ZZZZZZ",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "allow_preview_data": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "真实行情不足" in (data.get("error") or "")


class TestQuantRuns:
    """本地运行记录端点。"""

    @pytest.mark.anyio
    async def test_runs_and_run_detail_after_backtest(self, client):
        run_resp = await client.post(
            "/api/quant/backtest",
            json={
                "strategy_id": "ma_crossover",
                "symbol": "000001",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "allow_preview_data": True,
            },
        )
        run_id = run_resp.json()["data"]["run_id"]

        list_resp = await client.get("/api/quant/runs")
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert list_data["success"] is True
        assert list_data["data"]["execution_mode"] == "local"
        assert any(item["run_id"] == run_id for item in list_data["data"]["runs"])

        detail_resp = await client.get(f"/api/quant/runs/{run_id}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["success"] is True
        assert detail_data["data"]["run_id"] == run_id
        assert detail_data["data"]["source_status"] == "local"

    @pytest.mark.anyio
    async def test_run_detail_not_found(self, client):
        resp = await client.get("/api/quant/runs/missing-run")

        assert resp.status_code == 404


class TestQuantLiveEndpoints:
    """实盘接口目前明确未接入。"""

    @pytest.mark.anyio
    async def test_live_start_not_implemented(self, client):
        resp = await client.post(
            "/api/quant/live/start",
            json={"strategy_id": "macd_momentum", "symbol": "600519"},
        )

        data = resp.json()
        assert data["success"] is False
        assert data["error_code"] == "LOCAL_LIVE_NOT_IMPLEMENTED"

    @pytest.mark.anyio
    async def test_live_stop_not_implemented(self, client):
        resp = await client.post("/api/quant/live/stop", json={"run_id": "r1"})

        data = resp.json()
        assert data["success"] is False
        assert data["error_code"] == "LOCAL_LIVE_NOT_IMPLEMENTED"
