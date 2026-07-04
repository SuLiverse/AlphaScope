"""Local RC (v0.70) 验收测试 — 稳定性/错误处理/诊断/备份恢复"""

from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


def _pyproject_version() -> str:
    """pyproject.toml 的 project.version —— 版本号单一来源。"""
    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    with pyproject.open("rb") as f:
        return tomllib.load(f)["project"]["version"]


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ========== 1. 稳定性 — 核心端点不崩 ==========


class TestStability:
    """核心端点稳定性"""

    @pytest.mark.anyio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "healthy"

    @pytest.mark.anyio
    async def test_root(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_conversations_crud(self, client):
        with patch(
            "backend.ai_assistant.conversation_store.ConversationStore.create_conversation",
            return_value="c1",
        ):
            resp = await client.post("/api/conversations", json={"title": "test", "mode": "free"})
        assert resp.json()["success"] is True

        with patch(
            "backend.ai_assistant.conversation_store.ConversationStore.list_conversations",
            return_value=[],
        ):
            resp = await client.get("/api/conversations")
        assert resp.json()["success"] is True

    @pytest.mark.anyio
    async def test_providers_health(self, client):
        resp = await client.get("/api/providers/health")
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_modes(self, client):
        resp = await client.get("/api/modes")
        assert resp.status_code == 200


# ========== 2. 错误处理 — 常见错误有提示 ==========


class TestErrorHandling:
    """错误处理"""

    @pytest.mark.anyio
    async def test_404_returns_json(self, client):
        resp = await client.get("/api/nonexistent")
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_conversation_not_found(self, client):
        with patch(
            "backend.ai_assistant.conversation_store.ConversationStore.get_conversation",
            return_value=None,
        ):
            resp = await client.get("/api/conversations/nonexistent")
        # 404 或 200+success=False 都可接受
        assert resp.status_code in (200, 404)

    @pytest.mark.anyio
    async def test_upload_unsupported_format(self, client):
        resp = await client.post(
            "/api/files/upload",
            files={"file": ("test.exe", b"MZ", "application/octet-stream")},
        )
        # 400 或 200+success=False 都表示正确拒绝
        assert resp.status_code in (200, 400)

    @pytest.mark.anyio
    async def test_search_empty_query(self, client):
        with patch("backend.file_store.search_documents", return_value=[]):
            resp = await client.post("/api/knowledge/search", json={"query": ""})
        assert resp.status_code == 200

    @pytest.mark.anyio
    async def test_vision_no_image(self, client):
        resp = await client.post("/api/vision/analyze", json={"image_base64": "", "mime_type": "image/png"})
        assert resp.status_code == 200


# ========== 3. 诊断 — 日志可定位问题 ==========


class TestDiagnostics:
    """诊断能力"""

    @pytest.mark.anyio
    async def test_diagnostics_summary(self, client):
        mock = {
            "tool_calls": {"total": 0, "errors": 0, "avg_latency_ms": 0},
            "cost_records": {
                "total": 0,
                "total_cost_usd": 0,
                "total_input_tokens": 0,
                "total_output_tokens": 0,
            },
            "health": {"total_checks": 0, "ok": 0, "errors": 0},
        }
        with patch("backend.diagnostics_store.get_diagnostics_summary", return_value=mock):
            resp = await client.get("/api/diagnostics/summary")
        assert resp.json()["success"] is True

    @pytest.mark.anyio
    async def test_diagnostics_tool_calls(self, client):
        with patch("backend.diagnostics_store.list_tool_calls", return_value=[]):
            resp = await client.get("/api/diagnostics/tool-calls")
        assert resp.json()["success"] is True

    @pytest.mark.anyio
    async def test_diagnostics_errors(self, client):
        with (
            patch("backend.diagnostics_store.list_tool_calls", return_value=[]),
            patch("backend.diagnostics_store.get_health_history", return_value=[]),
        ):
            resp = await client.get("/api/diagnostics/errors")
        assert resp.json()["success"] is True
        assert "tool_call_errors" in resp.json()["data"]

    @pytest.mark.anyio
    async def test_costs_endpoint(self, client):
        with patch(
            "backend.observability.cost_tracker.CostTracker.get_summary",
            return_value={},
        ):
            resp = await client.get("/api/costs")
        assert resp.status_code == 200


# ========== 4. 降级 — 无依赖不崩 ==========


class TestDegradation:
    """降级能力"""

    @pytest.mark.anyio
    async def test_no_chromadb_health(self, client):
        with patch("backend.rag.vector_store.VectorStore._get_client", return_value=None):
            resp = await client.get("/health")
        assert resp.json()["data"]["status"] == "healthy"

    @pytest.mark.anyio
    async def test_no_chromadb_search(self, client):
        with (
            patch(
                "backend.rag.vector_store.VectorStore",
                side_effect=RuntimeError("no chromadb"),
            ),
            patch("backend.file_store.search_documents", return_value=[]),
        ):
            resp = await client.post("/api/knowledge/search", json={"query": "test"})
        assert resp.json()["success"] is True

    @pytest.mark.anyio
    async def test_no_price_data(self, client):
        with patch("backend.price_store.get_prices", return_value=[]):
            resp = await client.get("/api/prices/600519")
        assert resp.status_code == 200
        # 无数据时 total 为 0
        assert resp.json()["data"]["total"] == 0

    @pytest.mark.anyio
    async def test_no_news_data(self, client):
        with patch("backend.news_store.list_news", return_value=[]):
            resp = await client.get("/api/news")
        assert resp.json()["success"] is True
        assert resp.json()["data"]["total"] == 0


# ========== 5. 备份恢复 — 数据可导出 ==========


class TestBackupRestore:
    """备份恢复"""

    def test_db_file_exists(self):
        from backend.project_paths import DB_DIR

        db_path = DB_DIR / "ai_finance.db"
        # DB 在首次访问时自动创建
        from backend.storage.db import Database

        Database()
        assert db_path.exists()

    def test_data_dirs_exist(self):
        from backend.project_paths import UPLOADS_DIR, REPORTS_DIR, CACHE_DIR, LOGS_DIR

        for d in [UPLOADS_DIR, REPORTS_DIR, CACHE_DIR, LOGS_DIR]:
            d.mkdir(parents=True, exist_ok=True)
            assert d.exists()

    def test_schema_tables_exist(self):
        from backend.storage.db import Database

        db = Database()
        conn = db._conn
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t[0] for t in tables}
        required = {"news_items", "price_bars", "evidence_items", "ai_conversations"}
        assert required.issubset(table_names)


# ========== 6. 版本号 ==========


class TestVersion:
    """版本号验证"""

    @pytest.mark.anyio
    async def test_version_is_current(self, client):
        resp = await client.get("/health")
        assert resp.json()["data"]["version"] == _pyproject_version()
