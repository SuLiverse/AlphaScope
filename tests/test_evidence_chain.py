"""Tests for Evidence Chain — 证据存储层 + 证据链引擎 + API"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


# ============== evidence_store 测试 ==============


def _patch_evidence_db():
    """mock 进程级单例 Database, transaction() 上下文给出同一 mock conn。
    CRUD 现在走 with Database().transaction() as conn:, 不再暴露 _get_conn。"""
    conn = MagicMock()
    db_mock = MagicMock()
    db_mock.transaction.return_value.__enter__.return_value = conn
    db_mock.transaction.return_value.__exit__.return_value = False
    return patch("backend.evidence_store.Database", return_value=db_mock), conn


class TestEvidenceStore:
    """测试 evidence_store CRUD"""

    def test_save_evidence(self):
        from backend.evidence_store import save_evidence

        patcher, conn = _patch_evidence_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = {
                "id": "ev1",
                "evidence_type": "news",
                "title": "test",
                "source": "cls",
                "source_url": "",
                "content_summary": "",
                "symbols": "[]",
                "confidence": 0.7,
                "relevance": 0.5,
                "claim": "test claim",
                "data_date": "2025-01-01",
                "created_at": time.time(),
            }
            save_evidence(
                evidence_type="news",
                title="test",
                source="cls",
                claim="test claim",
            )
            assert conn.execute.called

    def test_get_evidence_not_found(self):
        from backend.evidence_store import get_evidence

        patcher, conn = _patch_evidence_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = None
            result = get_evidence("nonexistent")
            assert result is None

    def test_list_evidence(self):
        from backend.evidence_store import list_evidence

        patcher, conn = _patch_evidence_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = list_evidence()
            assert isinstance(result, list)

    def test_list_evidence_with_filters(self):
        from backend.evidence_store import list_evidence

        patcher, conn = _patch_evidence_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            list_evidence(evidence_type="news", symbol="600519")

    def test_delete_evidence_not_found(self):
        from backend.evidence_store import delete_evidence

        patcher, conn = _patch_evidence_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = None
            assert delete_evidence("nonexistent") is False

    def test_delete_evidence_success(self):
        from backend.evidence_store import delete_evidence

        patcher, conn = _patch_evidence_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = {"id": "ev1"}
            assert delete_evidence("ev1") is True

    def test_search_evidence(self):
        from backend.evidence_store import search_evidence

        patcher, conn = _patch_evidence_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = search_evidence("test")
            assert isinstance(result, list)

    def test_save_evidence_link(self):
        from backend.evidence_store import save_evidence_link

        patcher, conn = _patch_evidence_db()
        with patcher:
            save_evidence_link("ev1", "claim text", "conv1", "msg1")
            assert conn.execute.called

    def test_get_evidence_for_claim(self):
        from backend.evidence_store import get_evidence_for_claim

        patcher, conn = _patch_evidence_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = get_evidence_for_claim("claim")
            assert isinstance(result, list)


# ============== evidence_chain 引擎测试 ==============


class TestEvidenceChain:
    """测试 build_evidence_chain"""

    def test_empty_input(self):
        from backend.quality.evidence_chain import build_evidence_chain

        result = build_evidence_chain([])
        assert result["bundles"] == []
        assert result["coverage"] == 1.0
        assert result["overall_confidence"] == 0.0

    def test_single_evidence(self):
        from backend.quality.evidence_chain import build_evidence_chain

        items = [
            {
                "type": "fund_flow",
                "claim": "主力净流入",
                "source": "eastmoney",
                "data_date": "2025-01-01",
            }
        ]
        result = build_evidence_chain(items)
        assert len(result["bundles"]) == 1
        assert result["bundles"][0]["source_count"] == 1
        assert result["bundles"][0]["confidence"] > 0

    def test_multi_source_boost(self):
        from backend.quality.evidence_chain import build_evidence_chain

        today = time.strftime("%Y-%m-%d")
        items = [
            {
                "type": "news",
                "claim": "公司业绩增长",
                "source": "cls",
                "data_date": today,
            },
            {
                "type": "news",
                "claim": "公司业绩增长",
                "source": "eastmoney",
                "data_date": today,
            },
            {
                "type": "news",
                "claim": "公司业绩增长",
                "source": "sina",
                "data_date": today,
            },
        ]
        result = build_evidence_chain(items)
        assert len(result["bundles"]) == 1
        assert result["bundles"][0]["source_count"] == 3
        assert result["bundles"][0]["confidence"] > 0.7  # 多源提升

    def test_contradiction_detection(self):
        from backend.quality.evidence_chain import _detect_contradictions

        # 模拟同 bundle 内有买入和卖出信号
        bundles = [
            {
                "claim": "资金面分析",
                "evidence": [
                    {"claim": "主力资金净流入建议买入"},
                    {"claim": "北向资金持续卖出"},
                ],
                "confidence": 0.7,
                "source_count": 2,
                "trust_score": 0.7,
                "decay_factor": 0.9,
                "contradictions": [],
            }
        ]
        contradictions = _detect_contradictions(bundles)
        assert len(contradictions) > 0
        assert len(bundles[0]["contradictions"]) > 0

    def test_missing_evidence_detection(self):
        from backend.quality.evidence_chain import build_evidence_chain

        agent_signals = [
            {"agent": "技术面分析师", "signal": "买入", "has_evidence": False},
            {"agent": "基本面分析师", "signal": "买入", "has_evidence": True},
        ]
        result = build_evidence_chain([], agent_signals=agent_signals)
        assert len(result["missing_evidence"]) == 1
        assert "技术面分析师" in result["missing_evidence"][0]

    def test_coverage_calculation(self):
        from backend.quality.evidence_chain import build_evidence_chain

        agent_signals = [
            {"agent": "A", "signal": "买入", "has_evidence": True},
            {"agent": "B", "signal": "卖出", "has_evidence": False},
        ]
        result = build_evidence_chain([], agent_signals=agent_signals)
        assert result["coverage"] == 0.5

    def test_time_decay_recent(self):
        from backend.quality.evidence_chain import _time_decay

        today = time.strftime("%Y-%m-%d")
        decay = _time_decay(today, time.time())
        assert decay > 0.9

    def test_time_decay_old(self):
        from backend.quality.evidence_chain import _time_decay

        decay = _time_decay("2020-01-01", time.time())
        assert decay < 0.2

    def test_claim_grouping(self):
        from backend.quality.evidence_chain import build_evidence_chain

        items = [
            {
                "type": "news",
                "claim": "营收同比增长20%",
                "source": "cls",
                "data_date": "2025-01-01",
            },
            {
                "type": "report",
                "claim": "营收同比增长20%",
                "source": "eastmoney",
                "data_date": "2025-01-01",
            },
            {
                "type": "news",
                "claim": "新产品发布",
                "source": "cls",
                "data_date": "2025-01-01",
            },
        ]
        result = build_evidence_chain(items)
        assert len(result["bundles"]) == 2

    def test_agent_signals_none(self):
        from backend.quality.evidence_chain import build_evidence_chain

        result = build_evidence_chain([], agent_signals=None)
        assert result["missing_evidence"] == []
        assert result["coverage"] == 1.0


# ============== API 测试 ==============


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_list_evidence(client):
    with patch("backend.evidence_store.list_evidence", return_value=[]):
        resp = await client.get("/api/evidence")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "evidence" in data["data"]


@pytest.mark.anyio
async def test_get_evidence_not_found(client):
    with patch("backend.evidence_store.get_evidence", return_value=None):
        resp = await client.get("/api/evidence/nonexistent")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


@pytest.mark.anyio
async def test_get_evidence_found(client):
    mock_item = {
        "id": "ev1",
        "evidence_type": "news",
        "title": "test",
        "source": "cls",
        "source_url": "",
        "content_summary": "",
        "symbols": [],
        "confidence": 0.7,
        "relevance": 0.5,
        "claim": "test claim",
        "data_date": "2025-01-01",
        "created_at": time.time(),
    }
    with patch("backend.evidence_store.get_evidence", return_value=mock_item):
        resp = await client.get("/api/evidence/ev1")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["id"] == "ev1"


@pytest.mark.anyio
async def test_create_evidence(client):
    mock_item = {
        "id": "ev2",
        "evidence_type": "news",
        "title": "test",
        "source": "cls",
        "claim": "claim",
    }
    with patch("backend.evidence_store.save_evidence", return_value=mock_item):
        resp = await client.post(
            "/api/evidence",
            json={
                "evidence_type": "news",
                "title": "test",
                "source": "cls",
                "claim": "claim",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_search_evidence(client):
    with patch("backend.evidence_store.search_evidence", return_value=[]):
        resp = await client.post(
            "/api/evidence/search", json={"query": "test", "limit": 10}
        )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_build_chain(client):
    resp = await client.post(
        "/api/evidence/chain",
        json={
            "evidence": [
                {
                    "type": "news",
                    "claim": "test",
                    "source": "cls",
                    "data_date": "2025-01-01",
                }
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "bundles" in data["data"]


@pytest.mark.anyio
async def test_delete_evidence_not_found(client):
    with patch("backend.evidence_store.delete_evidence", return_value=False):
        resp = await client.delete("/api/evidence/nonexistent")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


@pytest.mark.anyio
async def test_delete_evidence_success(client):
    with patch("backend.evidence_store.delete_evidence", return_value=True):
        resp = await client.delete("/api/evidence/ev1")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
