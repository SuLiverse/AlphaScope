from __future__ import annotations

import socket

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("requests")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


class FakeNewsResponse:
    url = "https://example.com/story"
    headers = {"content-type": "text/html; charset=utf-8"}
    encoding = "utf-8"

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield b"""
        <html>
          <head>
            <title>AlphaScope parses a test article</title>
            <meta name="description" content="A concise summary for the test article.">
            <meta property="og:site_name" content="Example News">
          </head>
          <body>
            <article>
              <p>First paragraph with market context.</p>
              <p>Second paragraph with more details.</p>
            </article>
          </body>
        </html>
        """

    def close(self):
        return None


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_parse_news_url_extracts_article_fields(client, monkeypatch):
    monkeypatch.setattr(
        "backend.security.url_guard.socket.getaddrinfo",
        lambda host, port, type: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    monkeypatch.setattr("requests.get", lambda *args, **kwargs: FakeNewsResponse())

    async with client:
        resp = await client.post(
            "/api/news/parse-url",
            json={"url": "https://example.com/story", "symbol": "600519"},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["title"] == "AlphaScope parses a test article"
    assert data["summary"] == "A concise summary for the test article."
    assert "First paragraph" in data["content"]
    assert data["source"] == "Example News"
    assert data["source_status"] == "ok"
    assert data["degraded"] is False


@pytest.mark.anyio
async def test_parse_news_url_blocks_local_network(client):
    async with client:
        resp = await client.post(
            "/api/news/parse-url",
            json={"url": "http://127.0.0.1:8000/private"},
        )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["success"] is True
    assert payload["error_code"] == "NEWS_URL_PARSE_DEGRADED"
    assert payload["data"]["degraded"] is True
    assert payload["data"]["source_status"] == "blocked"
