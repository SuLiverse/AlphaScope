"""Tests for portfolio management API (v1.1.3)."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


@pytest.fixture
def client():
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from backend.api.main import app

    return TestClient(app)


class TestPortfolioAPI:
    """Test /api/portfolio/* endpoints."""

    def test_create_portfolio(self, client):
        resp = client.post(
            "/api/portfolio",
            json={"name": "测试组合", "initial_capital": 100000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["name"] == "测试组合"
        assert data["data"]["cash"] == 100000

    def test_list_portfolios(self, client):
        client.post("/api/portfolio", json={"name": "P1", "initial_capital": 50000})
        resp = client.get("/api/portfolio")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["data"], list)

    def test_get_portfolio(self, client):
        create = client.post("/api/portfolio", json={"name": "P2", "initial_capital": 80000})
        pid = create.json()["data"]["id"]
        resp = client.get(f"/api/portfolio/{pid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["name"] == "P2"

    def test_get_portfolio_not_found(self, client):
        resp = client.get("/api/portfolio/nonexistent")
        assert resp.status_code == 404

    def test_buy_trade(self, client):
        create = client.post("/api/portfolio", json={"name": "BuyTest", "initial_capital": 100000})
        pid = create.json()["data"]["id"]
        resp = client.post(
            f"/api/portfolio/{pid}/trade",
            json={"symbol": "600519", "side": "buy", "shares": 100, "price": 100.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["data"]["cash"] < 100000

    def test_sell_trade(self, client):
        create = client.post("/api/portfolio", json={"name": "SellTest", "initial_capital": 100000})
        pid = create.json()["data"]["id"]
        client.post(
            f"/api/portfolio/{pid}/trade",
            json={"symbol": "600519", "side": "buy", "shares": 100, "price": 100.0},
        )
        resp = client.post(
            f"/api/portfolio/{pid}/trade",
            json={"symbol": "600519", "side": "sell", "shares": 100, "price": 110.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True

    def test_sell_no_position(self, client):
        create = client.post("/api/portfolio", json={"name": "NoPos", "initial_capital": 100000})
        pid = create.json()["data"]["id"]
        resp = client.post(
            f"/api/portfolio/{pid}/trade",
            json={"symbol": "600519", "side": "sell", "shares": 100, "price": 100.0},
        )
        assert resp.status_code == 400

    def test_buy_insufficient_cash(self, client):
        create = client.post("/api/portfolio", json={"name": "Poor", "initial_capital": 1000})
        pid = create.json()["data"]["id"]
        resp = client.post(
            f"/api/portfolio/{pid}/trade",
            json={"symbol": "600519", "side": "buy", "shares": 100, "price": 100.0},
        )
        assert resp.status_code == 400

    def test_allocation(self, client):
        create = client.post("/api/portfolio", json={"name": "Alloc", "initial_capital": 100000})
        pid = create.json()["data"]["id"]
        client.post(
            f"/api/portfolio/{pid}/trade",
            json={"symbol": "600519", "side": "buy", "shares": 100, "price": 100.0},
        )
        resp = client.get(f"/api/portfolio/{pid}/allocation")
        assert resp.status_code == 200
        data = resp.json()
        assert "600519" in data["data"]
        assert "_cash" in data["data"]

    def test_trades_list(self, client):
        create = client.post("/api/portfolio", json={"name": "Trades", "initial_capital": 100000})
        pid = create.json()["data"]["id"]
        client.post(
            f"/api/portfolio/{pid}/trade",
            json={"symbol": "600519", "side": "buy", "shares": 100, "price": 100.0},
        )
        resp = client.get(f"/api/portfolio/{pid}/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["data"]) == 1
        assert data["data"][0]["side"] == "buy"
