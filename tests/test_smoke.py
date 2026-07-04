"""Smoke Tests — 关键用户路径端到端验证"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_smoke_health(client):
    """GET /health 返回 healthy"""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["status"] == "healthy"


@pytest.mark.anyio
async def test_smoke_conversation_create_and_list(client):
    """创建会话后可列出"""
    resp = await client.post("/api/conversations", json={"title": "smoke", "mode": "free"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "id" in data["data"]

    resp = await client.get("/api/conversations")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_smoke_chat_stream(client):
    """POST /api/chat/stream 返回 SSE 流"""
    mock_orch = MagicMock()
    mock_orch.new_conversation.return_value = "test-conv-id"
    mock_orch.send_message.return_value = {
        "mode": "free",
        "content": "hello world",
        "evidence": [],
        "agents": {},
    }

    with patch("backend.ai_assistant.orchestrator.ChatOrchestrator", return_value=mock_orch):
        resp = await client.post(
            "/api/chat/stream",
            json={"message": "hi", "mode": "free"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    body = resp.text
    assert '"type"' in body
    assert '"done"' in body


@pytest.mark.anyio
async def test_smoke_vision_analyze(client):
    """POST /api/vision/analyze 返回分析结果"""
    from backend.vision.chart_detector import ChartDetectionResult
    from backend.vision.vision_agent import VisionAnalysisResult

    mock_result = VisionAnalysisResult(
        detection=ChartDetectionResult(is_chart=True, chart_type="kline", ticker="600519"),
        summary="test analysis",
        ok=True,
    )

    with patch("backend.vision.vision_agent.analyze_image", return_value=mock_result):
        resp = await client.post(
            "/api/vision/analyze",
            json={"image_base64": "dGVzdA==", "mime_type": "image/png"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["analysis"] == "test analysis"
    assert data["data"]["ticker"] == "600519"


@pytest.mark.anyio
async def test_smoke_upload(client):
    """POST /api/files/upload 上传 PNG"""
    resp = await client.post(
        "/api/files/upload",
        files={"file": ("test.png", PNG_BYTES, "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["filename"] == "test.png"
