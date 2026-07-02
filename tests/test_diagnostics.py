"""Tests for Diagnostics — 诊断存储层 + API"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


# ============== diagnostics_store 测试 ==============


def _patch_diagnostics_db():
    """mock 进程级单例 Database, transaction() 上下文给出同一 mock conn。
    CRUD 现在走 with Database().transaction() as conn:, 不再暴露 _get_conn。"""
    conn = MagicMock()
    db_mock = MagicMock()
    db_mock.transaction.return_value.__enter__.return_value = conn
    db_mock.transaction.return_value.__exit__.return_value = False
    return patch("backend.diagnostics_store.Database", return_value=db_mock), conn


class TestDiagnosticsStore:
    """测试 diagnostics_store CRUD"""

    def test_save_tool_call(self):
        from backend.diagnostics_store import save_tool_call

        patcher, conn = _patch_diagnostics_db()
        with patcher:
            save_tool_call("search", '{"q": "test"}', '{"results": []}', "ok", 100)
            assert conn.execute.called
            assert conn.commit.called

    def test_list_tool_calls(self):
        from backend.diagnostics_store import list_tool_calls

        patcher, conn = _patch_diagnostics_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = list_tool_calls()
            assert isinstance(result, list)

    def test_save_cost_record(self):
        from backend.diagnostics_store import save_cost_record

        patcher, conn = _patch_diagnostics_db()
        with patcher:
            save_cost_record("deepseek-chat", "deepseek", 1000, 500, 0.01, "standard")
            assert conn.execute.called

    def test_list_cost_records(self):
        from backend.diagnostics_store import list_cost_records

        patcher, conn = _patch_diagnostics_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = list_cost_records()
            assert isinstance(result, list)

    def test_list_cost_records_with_model(self):
        from backend.diagnostics_store import list_cost_records

        patcher, conn = _patch_diagnostics_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            list_cost_records(model="deepseek-chat")

    def test_get_health_history(self):
        from backend.diagnostics_store import get_health_history

        patcher, conn = _patch_diagnostics_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = get_health_history()
            assert isinstance(result, list)

    def test_get_diagnostics_summary(self):
        from backend.diagnostics_store import get_diagnostics_summary

        patcher, conn = _patch_diagnostics_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = {
                "total": 0,
                "cnt": 0,
                "avg_lat": 0,
                "total_cost": 0,
                "total_input": 0,
                "total_output": 0,
                "ok_count": 0,
                "error_count": 0,
            }
            result = get_diagnostics_summary()
            assert "tool_calls" in result
            assert "cost_records" in result
            assert "health" in result


# ============== API 测试 ==============


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_get_tool_calls(client):
    """GET /api/diagnostics/tool-calls"""
    with patch("backend.diagnostics_store.list_tool_calls", return_value=[]):
        resp = await client.get("/api/diagnostics/tool-calls")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "tool_calls" in resp.json()["data"]


@pytest.mark.anyio
async def test_get_model_calls(client):
    """GET /api/diagnostics/model-calls"""
    with patch("backend.diagnostics_store.list_cost_records", return_value=[]):
        resp = await client.get("/api/diagnostics/model-calls")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_get_health_history(client):
    """GET /api/diagnostics/health-history"""
    with patch("backend.diagnostics_store.get_health_history", return_value=[]):
        resp = await client.get("/api/diagnostics/health-history")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_get_errors(client):
    """GET /api/diagnostics/errors"""
    with (
        patch("backend.diagnostics_store.list_tool_calls", return_value=[]),
        patch("backend.diagnostics_store.get_health_history", return_value=[]),
    ):
        resp = await client.get("/api/diagnostics/errors")
    assert resp.status_code == 200
    assert "tool_call_errors" in resp.json()["data"]
    assert "health_errors" in resp.json()["data"]


@pytest.mark.anyio
async def test_get_summary(client):
    """GET /api/diagnostics/summary"""
    mock_summary = {
        "tool_calls": {"total": 0, "errors": 0, "avg_latency_ms": 0},
        "cost_records": {
            "total": 0,
            "total_cost_usd": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
        },
        "health": {"total_checks": 0, "ok": 0, "errors": 0},
    }
    with patch(
        "backend.diagnostics_store.get_diagnostics_summary", return_value=mock_summary
    ):
        resp = await client.get("/api/diagnostics/summary")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "tool_calls" in resp.json()["data"]
