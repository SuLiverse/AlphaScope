"""#4 导出 API 测试(mock 会话存储,不联网)。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from backend.api.main import app
import backend.ai_assistant.conversation_store as cs

client = TestClient(app)


def test_export_conversation_markdown(monkeypatch):
    monkeypatch.setattr(
        cs.ConversationStore,
        "get_conversation",
        lambda self, cid: {
            "title": "茅台分析",
            "stock_symbol": "600519",
            "stock_name": "贵州茅台",
            "mode": "deep",
        },
    )
    monkeypatch.setattr(
        cs.ConversationStore,
        "get_messages",
        lambda self, cid, limit=200: [
            {"role": "user", "content": "分析贵州茅台", "timestamp": "2026-06-18"},
            {
                "role": "assistant",
                "content": "营收同比 +18%。",
                "timestamp": "2026-06-18",
                "metadata": {},
            },
        ],
    )
    resp = client.get("/api/export/conversation/abc123.md")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "attachment" in resp.headers.get("content-disposition", "")
    assert ".md" in resp.headers.get("content-disposition", "")
    assert "茅台" in resp.text


def test_export_missing_conversation(monkeypatch):
    monkeypatch.setattr(cs.ConversationStore, "get_conversation", lambda self, cid: None)
    resp = client.get("/api/export/conversation/nope.md")
    assert resp.status_code == 404
