"""E · 估值情景假设 路由测试(monkeypatch 取数,验证 assumptions 透传)。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from backend.api.main import app
import backend.valuation as val

client = TestClient(app)

_FEATURES = {
    "revenue_latest_yi": 50,
    "net_margin": 12,
    "fcf_latest_yi": 5,
    "shares_outstanding_yi": 10,
    "market_cap_yi": 200,
    "price": 20,
}


def test_valuation_default(monkeypatch):
    monkeypatch.setattr(val, "features_from_fundamentals", lambda s: (dict(_FEATURES), []))
    resp = client.get("/api/valuation/600519")
    assert resp.status_code == 200
    dcf = resp.json()["data"]["dcf"]
    assert dcf["assumptions"]["stage1_growth"] == 0.10  # 默认


def test_valuation_scenario_assumptions_flow(monkeypatch):
    monkeypatch.setattr(val, "features_from_fundamentals", lambda s: (dict(_FEATURES), []))
    resp = client.get("/api/valuation/600519?stage1_growth=0.25&terminal_g=0.03&beta=1.2")
    assert resp.status_code == 200
    a = resp.json()["data"]["dcf"]["assumptions"]
    assert a["stage1_growth"] == 0.25
    assert a["terminal_g"] == 0.03
    assert a["beta"] == 1.2


def test_valuation_higher_growth_lifts_value(monkeypatch):
    monkeypatch.setattr(val, "features_from_fundamentals", lambda s: (dict(_FEATURES), []))
    low = client.get("/api/valuation/600519?stage1_growth=0.05").json()["data"]["dcf"]["intrinsic_per_share"]
    high = client.get("/api/valuation/600519?stage1_growth=0.25").json()["data"]["dcf"]["intrinsic_per_share"]
    assert high > low


def test_valuation_clamps_out_of_range():
    resp = client.get("/api/valuation/600519?beta=99")
    assert resp.status_code == 422
