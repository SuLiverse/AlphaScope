"""Regression tests for analysis guardrails."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_analysis_run_rejects_empty_market_data(client):
    with patch("backend.api.main.get_prices", return_value=[]):
        resp = await client.post(
            "/api/analysis/run",
            json={
                "stock_symbol": "600519.SH",
                "stock_name": "Maotai",
                "mode": "deep",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error"]


@pytest.mark.anyio
async def test_analysis_run_rejects_zero_only_market_data(client):
    with patch(
        "backend.api.main.get_prices",
        return_value=[
            {
                "date": "2026-05-01",
                "open": 0,
                "close": 0,
                "high": 0,
                "low": 0,
                "volume": 0,
            }
        ],
    ):
        resp = await client.post(
            "/api/analysis/run",
            json={
                "stock_symbol": "600519.SH",
                "stock_name": "Maotai",
                "mode": "deep",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error"]


@pytest.mark.anyio
async def test_analysis_run_marks_all_agent_model_failures_unsuccessful(client):
    bars = [
        {
            "date": "2026-05-01",
            "open": 10,
            "close": 10,
            "high": 11,
            "low": 9,
            "volume": 1000,
            "amount": 10000,
        },
        {
            "date": "2026-05-02",
            "open": 11,
            "close": 12,
            "high": 12,
            "low": 10,
            "volume": 1200,
            "amount": 14400,
        },
    ]
    runtime_result = {
        "mode": "standard",
        "summary": {"final": "HOLD", "buy": 0, "sell": 0, "hold": 3},
        "brief": "All model agents failed.",
        "research_report": "All model agents failed.",
        "agents": {
            "fundamental": {
                "signal": "HOLD",
                "confidence": 0,
                "reason": "provider deepseek is not configured",
            },
            "sentiment": {
                "signal": "HOLD",
                "confidence": 0,
                "reason": "provider deepseek is not configured",
            },
            "technical": {
                "signal": "HOLD",
                "confidence": 0,
                "reason": "provider deepseek is not configured",
            },
        },
        "critic": None,
        "chairman_summary": None,
        "external_agent": {
            "name": "tradingagents",
            "status": "failed",
            "error": "upstream timeout",
        },
        "mode_name": "standard",
        "model_status": {
            "status": "degraded",
            "degraded": True,
            "failure_type": "auth",
            "message": "all agent models failed",
            "ok_agents": 0,
            "total_agents": 3,
            "failed_agents": [],
        },
    }

    with (
        patch("backend.api.main.get_prices", return_value=bars),
        patch(
            "backend.runtime.orchestrator.run_agents_with_mode",
            return_value=runtime_result,
        ),
    ):
        resp = await client.post(
            "/api/analysis/run",
            json={
                "stock_symbol": "600519.SH",
                "stock_name": "Maotai",
                "mode": "standard",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == "analysis_all_agents_failed"
    assert data["data"]["result"]["model_status"]["ok_agents"] == 0
    assert data["data"]["result"]["model_status"]["total_agents"] == 3
    assert data["data"]["result"]["external_agent"]["error"] == "upstream timeout"


@pytest.mark.anyio
async def test_analysis_run_propagates_research_cutoff_and_question(client):
    bars = [
        {"date": "2026-06-29", "open": 99, "close": 100, "high": 101, "low": 98, "volume": 1000},
        {"date": "2026-06-30", "open": 100, "close": 110, "high": 111, "low": 99, "volume": 1200},
    ]
    captured = {}

    def fake_run_agents_with_mode(*, stock_data, **_kwargs):
        captured.update(stock_data)
        return {
            "mode": "deep",
            "summary": {"final": "观望"},
            "agents": {},
            "model_status": {"ok_agents": 0, "total_agents": 0},
            "research_snapshot": {"snapshot_id": "snap-1"},
        }

    with (
        patch("backend.api.main.get_prices", return_value=bars) as get_prices,
        patch("backend.runtime.orchestrator.run_agents_with_mode", side_effect=fake_run_agents_with_mode),
    ):
        resp = await client.post(
            "/api/analysis/run",
            json={
                "stock_symbol": "600519",
                "stock_name": "贵州茅台",
                "mode": "deep",
                "as_of": "2026-06-30",
                "research_question": "利润增长是否可持续？",
            },
        )

    assert resp.status_code == 200
    assert get_prices.call_args.kwargs["end_date"] == "2026-06-30"
    assert captured["as_of"] == "2026-06-30"
    assert captured["price_data_date"] == "2026-06-30"
    assert captured["research_question"] == "利润增长是否可持续？"
    assert captured["day_change"] == 10.0
    assert resp.json()["data"]["result"]["research_snapshot"] == {"snapshot_id": "snap-1"}


@pytest.mark.anyio
async def test_analysis_run_populates_quant_referee_indicators(client):
    bars = [
        {
            "date": f"2026-04-{index + 1:02d}",
            "open": 99 + index,
            "close": 100 + index,
            "high": 101 + index,
            "low": 98 + index,
            "volume": 1_000 + index * 10,
            "amount": 1_000_000,
        }
        for index in range(65)
    ]
    captured = {}

    def fake_run_agents_with_mode(*, stock_data, **_kwargs):
        captured.update(stock_data)
        return {
            "mode": "deep",
            "summary": {"final": "观望"},
            "agents": {},
            "model_status": {"ok_agents": 0, "total_agents": 0},
        }

    with (
        patch("backend.api.main.get_prices", return_value=bars),
        patch("backend.runtime.orchestrator.run_agents_with_mode", side_effect=fake_run_agents_with_mode),
    ):
        response = await client.post(
            "/api/analysis/run",
            json={"stock_symbol": "600519", "stock_name": "贵州茅台", "mode": "deep"},
        )

    assert response.status_code == 200
    for field in ("ma5", "ma20", "ma60", "rsi", "dif", "dea", "macd", "vol_ratio"):
        assert isinstance(captured[field], float), field


@pytest.mark.anyio
async def test_analysis_run_rejects_future_cutoff(client):
    resp = await client.post(
        "/api/analysis/run",
        json={"stock_symbol": "600519", "as_of": "2099-01-01"},
    )

    assert resp.status_code == 422
