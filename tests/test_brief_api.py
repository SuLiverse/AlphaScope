"""#5 自选晨报 API 测试(monkeypatch 本地价格/新闻取数)。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from backend.api.main import app
import backend.news_store as ns
import backend.price_store as ps

client = TestClient(app)


def test_brief_aggregates(monkeypatch):
    monkeypatch.setattr(
        ps,
        "get_prices",
        lambda s, **k: [
            {"date": "2026-06-17", "close": 1600, "change_pct": 1.2},
            {"date": "2026-06-18", "close": 1620, "change_pct": 1.25},
        ],
    )
    monkeypatch.setattr(
        ns,
        "list_news",
        lambda symbol=None, limit=3: [{"title": "利好消息", "published_at": "2026-06-18", "url": "x"}],
    )
    resp = client.get("/api/brief?symbols=600519,000001")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 2
    item = data["items"][0]
    assert item["symbol"] == "600519"
    assert item["close"] == 1620  # 取 date 最大的一根
    assert item["change_pct"] == 1.25
    assert item["news_count"] == 1


def test_brief_empty_symbols():
    resp = client.get("/api/brief")
    assert resp.status_code == 200
    assert resp.json()["data"]["count"] == 0


def test_brief_degrades_per_symbol(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no data")

    monkeypatch.setattr(ps, "get_prices", boom)
    monkeypatch.setattr(ns, "list_news", boom)
    resp = client.get("/api/brief?symbols=600519")
    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["symbol"] == "600519"
    assert item["close"] is None and item["news_count"] == 0
