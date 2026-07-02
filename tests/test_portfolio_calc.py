"""组合计算 API — 持久化持仓 + 组合优化 + 绩效报告契约测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.api.main import app

    return TestClient(app)


def _clear_positions():
    from backend import research_portfolio_store

    research_portfolio_store.clear_positions()


# ---------------- 持久化持仓 ----------------


def test_store_upsert_list_remove():
    from backend import research_portfolio_store

    _clear_positions()
    research_portfolio_store.upsert_position(
        "600519", "贵州茅台", "白酒", 100, 1500.0
    )
    items = research_portfolio_store.list_positions()
    assert len(items) == 1
    assert items[0]["symbol"] == "600519"
    assert items[0]["shares"] == 100.0

    # 更新(upsert 同 symbol)
    research_portfolio_store.upsert_position("600519", "贵州茅台", "白酒", 200, 1600.0)
    items = research_portfolio_store.list_positions()
    assert len(items) == 1
    assert items[0]["shares"] == 200.0
    assert items[0]["cost"] == 1600.0

    assert research_portfolio_store.remove_position("600519")
    assert research_portfolio_store.list_positions() == []


def test_api_positions_crud(client):
    _clear_positions()
    # 新增
    r = client.post(
        "/api/portfolio/positions",
        json={"symbol": "000001", "name": "平安银行", "sector": "银行", "shares": 500, "cost": 12.5},
    )
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert any(i["symbol"] == "000001" for i in items)

    # 列表
    r = client.get("/api/portfolio/positions")
    assert r.status_code == 200
    assert any(i["symbol"] == "000001" for i in r.json()["data"]["items"])

    # 删除
    r = client.delete("/api/portfolio/positions/000001")
    assert r.status_code == 200
    _clear_positions()


# ---------------- 组合优化 ----------------


def test_optimize_needs_two_symbols(client):
    r = client.post("/api/portfolio/optimize", json={"symbols": ["600519"], "method": "max_sharpe"})
    assert r.status_code == 400


def test_optimize_returns_structure(client):
    """优化端点:无行情时返回 400(数据不足),结构清晰;不抛 500。"""
    r = client.post(
        "/api/portfolio/optimize",
        json={"symbols": ["600519", "999999"], "method": "max_sharpe", "days": 30},
    )
    # 这两个代码大概率拉不到足够公共交易日 → 400 数据不足(而非 500)
    assert r.status_code in (400, 200)


def test_optimizers_available(client):
    r = client.get("/api/portfolio/optimizers")
    assert r.status_code == 200
    data = r.json()["data"]["optimizers"]
    assert isinstance(data, list)


# ---------------- 绩效报告 ----------------


def test_performance_needs_input(client):
    r = client.post("/api/portfolio/performance", json={})
    assert r.status_code == 400


def test_performance_short_curve(client):
    """数据不足时返回 available + error,不抛。"""
    r = client.post("/api/portfolio/performance", json={"equity_curve": [100.0, 101.0]})
    assert r.status_code == 200
    body = r.json()["data"]
    # 要么 quantstats 算出指标,要么返回 available/error
    assert "available" in body


def test_performance_available_endpoint(client):
    r = client.get("/api/portfolio/performance/available")
    assert r.status_code == 200
    assert "available" in r.json()["data"]


# ---------------- optimizer 纯函数 ----------------


def test_optimizer_equal_weight_fallback():
    """optimize_portfolio 在数据不足时退化等权并标 degraded(纯函数,无网络)。"""
    from backend.portfolio_optimizer import optimize_portfolio

    # returns=None → 数据不足,degraded
    res = optimize_portfolio(None, method="max_sharpe")
    assert res["degraded"] is True
    assert res["forbidden_live_order"] is True
    assert res["research_only"] is True


def test_optimizer_equal_weight_method():
    from backend.portfolio_optimizer import optimize_portfolio

    # 构造 2 资产 × 40 时间的合成收益
    rows = [[0.01, 0.005] for _ in range(40)]
    res = optimize_portfolio(rows, method="equal_weight", asset_names=["A", "B"])
    assert res["optimizer"] == "equal_weight"
    assert abs(sum(res["weights"].values()) - 1.0) < 0.01
