"""Regression tests for generic file upload filename safety."""

from __future__ import annotations

import sys
from pathlib import Path

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
async def test_generic_file_upload_sanitizes_path_traversal_filename(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.project_paths.UPLOADS_DIR", tmp_path / "uploads")

    async with client:
        resp = await client.post(
            "/api/files/upload",
            files={"file": ("../../evil chart.png", b"png-bytes", "image/png")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["filename"] == "evil_chart.png"
    saved_files = list((tmp_path / "uploads").iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].parent == tmp_path / "uploads"
    assert saved_files[0].name.endswith("_evil_chart.png")


@pytest.mark.anyio
async def test_generic_file_upload_rejects_empty_sanitized_filename(client, tmp_path, monkeypatch):
    monkeypatch.setattr("backend.project_paths.UPLOADS_DIR", tmp_path / "uploads")

    async with client:
        resp = await client.post(
            "/api/files/upload",
            files={"file": ("..", b"png-bytes", "image/png")},
        )

    assert resp.status_code == 400
