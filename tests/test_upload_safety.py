"""Regression tests for knowledge upload filename safety."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

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
async def test_knowledge_upload_sanitizes_path_traversal_filename(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.api.knowledge.UPLOADS_DIR", tmp_path / "uploads")
    mock_doc = MagicMock()
    mock_doc.doc_id = "doc-safe"
    mock_doc.filename = "evil.pdf"
    mock_doc.chunk_count = 1
    mock_doc.processing_time_ms = 5.0

    with patch(
        "backend.rag.document_pipeline.DocumentPipeline.process_and_persist",
        return_value=mock_doc,
    ) as process_and_persist:
        resp = await client.post(
            "/api/knowledge/upload",
            files={"file": ("../../evil.pdf", b"pdf-bytes", "application/pdf")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    saved_path = Path(process_and_persist.call_args.args[0])
    metadata = process_and_persist.call_args.kwargs["metadata"]
    assert saved_path.parent == tmp_path / "uploads"
    assert saved_path.name.endswith("_evil.pdf")
    assert metadata["original_name"] == "evil.pdf"
    assert saved_path.exists()


@pytest.mark.anyio
async def test_knowledge_upload_uses_sanitized_filename_for_disk_and_metadata(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.api.knowledge.UPLOADS_DIR", tmp_path / "uploads")
    mock_doc = MagicMock()
    mock_doc.doc_id = "doc-safe"
    mock_doc.filename = "report_2026.pdf"
    mock_doc.chunk_count = 1
    mock_doc.processing_time_ms = 5.0

    with patch(
        "backend.rag.document_pipeline.DocumentPipeline.process_and_persist",
        return_value=mock_doc,
    ) as process_and_persist:
        resp = await client.post(
            "/api/knowledge/upload",
            files={"file": ("report 2026.pdf", b"pdf-bytes", "application/pdf")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    saved_path = Path(process_and_persist.call_args.args[0])
    metadata = process_and_persist.call_args.kwargs["metadata"]
    assert saved_path.parent == tmp_path / "uploads"
    assert saved_path.name.endswith("_report_2026.pdf")
    assert metadata["original_name"] == "report_2026.pdf"
    assert saved_path.exists()
