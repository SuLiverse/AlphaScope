from __future__ import annotations

from backend import news_data
from backend.cache import TTLCache


def test_ttl_cache_can_return_bounded_stale_value(monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr("backend.cache.time.time", lambda: now[0])
    cache = TTLCache()
    cache.set("news", ["cached"], ttl_seconds=10)

    now[0] = 1_011.0
    assert cache.get_fresh_or_stale("news", max_stale_seconds=30) == (["cached"], True)

    now[0] = 1_041.0
    assert cache.get_fresh_or_stale("news", max_stale_seconds=30) == (None, False)


def test_news_returns_stale_when_all_upstreams_are_empty(monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr("backend.cache.time.time", lambda: now[0])
    cache = TTLCache()
    cache_key = "news:CN:600519:30:_"
    cached = [{"title": "last known good"}]
    cache.set(cache_key, cached, ttl_seconds=10)
    now[0] = 1_011.0

    class EmptyPipeline:
        def ingest_news(self, **_kwargs):
            return []

    monkeypatch.setattr("backend.cache.get_cache", lambda: cache)
    monkeypatch.setattr("backend.pipeline.get_pipeline", lambda: EmptyPipeline())
    monkeypatch.setattr(news_data, "_get_registry", lambda: None)
    monkeypatch.setattr(news_data, "fetch_telegraph_cls", lambda **_kwargs: [])
    monkeypatch.setattr(news_data, "fetch_telegraph_em", lambda **_kwargs: [])
    monkeypatch.setattr(news_data, "fetch_telegraph_sina", lambda **_kwargs: [])

    assert news_data.fetch_news_via_provider(symbol="600519") == cached
