"""Tests for News Store + Event Impact — 新闻存储层 + 事件影响分析 + API"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


class _Row(dict):
    def __getitem__(self, key):
        return self.get(key)


# ============== news_store 测试 ==============


def _patch_news_db():
    """mock 进程级单例 Database, transaction() 上下文给出同一 mock conn。
    CRUD 现在走 with Database().transaction() as conn:, 不再暴露 _get_conn。"""
    conn = MagicMock()
    db_mock = MagicMock()
    db_mock.transaction.return_value.__enter__.return_value = conn
    db_mock.transaction.return_value.__exit__.return_value = False
    return patch("backend.news_store.Database", return_value=db_mock), conn


class TestNewsStore:
    """测试 news_store CRUD"""

    def test_list_news(self):
        from backend.news_store import list_news

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = list_news()
            assert isinstance(result, list)

    def test_list_news_with_symbol(self):
        from backend.news_store import list_news

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            list_news(symbol="600519")

    def test_list_news_with_event_type(self):
        from backend.news_store import list_news

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            list_news(event_type="earnings")

    def test_get_news_not_found(self):
        from backend.news_store import get_news

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = None
            assert get_news("nonexistent") is None

    def test_search_news(self):
        from backend.news_store import search_news

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = search_news("茅台")
            assert isinstance(result, list)

    def test_row_to_news_repairs_legacy_mojibake_text(self):
        from backend.news_store import _row_to_news

        item = _row_to_news(
            _Row(
                id="news_1",
                title="è´µå·è\u0085å°ä¸æ§è¡è¡ä¸ç»­ç­¾",
                summary="5æ21æ¥åå¸å\u0085¬å",
                source="è¯å¸æ¶æ¥ç½",
                source_url="",
                published_at="2026-05-22T09:05:00+08:00",
                symbols='["600519"]',
                event_type="news",
                sentiment=0,
                importance=0.5,
                confidence=0.6,
            )
        )

        assert "贵州茅台" in item["title"]
        assert "公告" in item["summary"]
        assert item["source"] == "证券时报网"

    def test_list_announcements(self):
        from backend.news_store import list_announcements

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = list_announcements()
            assert isinstance(result, list)

    def test_list_announcements_with_symbol(self):
        from backend.news_store import list_announcements

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            list_announcements(symbol="600519")

    def test_get_announcement_not_found(self):
        from backend.news_store import get_announcement

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = None
            assert get_announcement("nonexistent") is None

    def test_row_to_announcement_repairs_legacy_mojibake_text(self):
        from backend.news_store import _row_to_announcement

        item = _row_to_announcement(
            _Row(
                id="ann_1",
                symbol="600519",
                company_name="è´µå·è\u0085å°",
                title="å¹´åº¦æ¥å",
                category="å®ææ¥å",
                published_at="2026-05-22T09:05:00+08:00",
                source="å·¨æ½®èµè®¯",
                source_url="",
                importance=0.6,
                confidence=0.9,
            )
        )

        assert item["company_name"] == "贵州茅台"
        assert item["title"] == "年度报告"
        assert item["category"] == "定期报告"

    def test_get_event_summary(self):
        from backend.news_store import get_event_summary

        patcher, conn = _patch_news_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            conn.execute.return_value.fetchone.return_value = {
                "total": 0,
                "avg_sent": 0,
            }
            result = get_event_summary("600519")
            assert result["symbol"] == "600519"


# ============== event_impact 测试 ==============


class TestEventImpact:
    """测试事件影响分析"""

    def test_analyze_event_impact_empty(self):
        from backend.event_impact import analyze_event_impact

        result = analyze_event_impact([], [])
        assert result == []

    def test_analyze_event_impact_with_data(self):
        from backend.event_impact import analyze_event_impact

        events = [
            {
                "published_at": "2025-01-10",
                "event_type": "earnings",
                "sentiment": 0.5,
                "title": "test",
            },
        ]
        prices = [
            {"date": f"2025-01-{i:02d}", "close": 100 + i, "change_pct": 0.5}
            for i in range(5, 20)
        ]
        result = analyze_event_impact(events, prices, window_days=3)
        assert len(result) == 1
        assert "impact" in result[0]
        assert result[0]["impact"]["impact_level"] in (
            "强正面",
            "正面",
            "中性",
            "负面",
            "强负面",
            "未知",
        )

    def test_sentiment_trend_empty(self):
        from backend.event_impact import get_sentiment_trend

        result = get_sentiment_trend([])
        assert result == []

    def test_sentiment_trend_with_data(self):
        from backend.event_impact import get_sentiment_trend

        events = [
            {"published_at": "2025-01-10", "sentiment": 0.5},
            {"published_at": "2025-01-10", "sentiment": -0.3},
            {"published_at": "2025-01-11", "sentiment": 0.8},
        ]
        result = get_sentiment_trend(events)
        assert len(result) == 2
        assert result[0]["date"] == "2025-01-10"
        assert result[0]["count"] == 2

    def test_correlate_empty(self):
        from backend.event_impact import correlate_events_prices

        result = correlate_events_prices([], [])
        assert result["correlation"] == 0

    def test_correlate_with_data(self):
        from backend.event_impact import correlate_events_prices

        events = [
            {
                "published_at": "2025-01-10",
                "sentiment": 0.8,
                "event_type": "earnings",
                "title": "good",
            },
            {
                "published_at": "2025-01-15",
                "sentiment": -0.5,
                "event_type": "litigation",
                "title": "bad",
            },
        ]
        prices = [
            {"date": f"2025-01-{i:02d}", "close": 100 + i, "change_pct": 0.5}
            for i in range(5, 25)
        ]
        result = correlate_events_prices(events, prices)
        assert "correlation" in result
        assert result["event_count"] == 2

    def test_classify_impact(self):
        from backend.event_impact import _classify_impact

        assert _classify_impact(5) == "强正面"
        assert _classify_impact(2) == "正面"
        assert _classify_impact(0) == "中性"
        assert _classify_impact(-2) == "负面"
        assert _classify_impact(-5) == "强负面"


# ============== API 测试 ==============


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_list_news(client):
    """GET /api/news"""
    with (
        patch("backend.news_store.list_news", return_value=[]),
        patch("backend.api.news._fetch_and_store_news") as mock_fetch,
    ):
        resp = await client.get("/api/news")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "news" in resp.json()["data"]
    mock_fetch.assert_awaited_once()


@pytest.mark.anyio
async def test_list_news_refetches_after_empty_store(client):
    """GET /api/news 空库时触发采集并返回第二次查询结果"""
    news_item = {
        "id": "news_1",
        "title": "贵州茅台新闻",
        "summary": "",
        "source": "eastmoney",
        "source_url": "",
        "published_at": "2026-05-25T10:00:00+08:00",
        "symbols": ["600519"],
    }
    with (
        patch("backend.news_store.list_news", side_effect=[[], [news_item]]),
        patch("backend.api.news._fetch_and_store_news") as mock_fetch,
    ):
        resp = await client.get("/api/news?symbol=600519")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 1
    assert data["news"][0]["title"] == "贵州茅台新闻"
    mock_fetch.assert_awaited_once()


@pytest.mark.anyio
async def test_list_announcements(client):
    """GET /api/news/announcements"""
    with patch("backend.news_store.list_announcements", return_value=[]):
        resp = await client.get("/api/news/announcements")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_list_announcements_empty_symbol_returns_degraded_metadata(client):
    with (
        patch("backend.news_store.list_announcements", return_value=[]),
        patch("backend.news_store.list_news", return_value=[]),
        patch("backend.api.news._fetch_and_store_announcements") as mock_fetch,
    ):
        resp = await client.get("/api/news/announcements?symbol=600519&limit=8")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["error_code"] == "ANNOUNCEMENTS_DEGRADED"
    assert data["data"]["announcements"] == []
    assert data["data"]["degraded"] is True
    assert data["data"]["source_status"] == "empty"
    mock_fetch.assert_awaited_once()


@pytest.mark.anyio
async def test_get_news_not_found(client):
    """GET /api/news/{id} 不存在"""
    with patch("backend.news_store.get_news", return_value=None):
        resp = await client.get("/api/news/nonexistent")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


@pytest.mark.anyio
async def test_search_news(client):
    """POST /api/news/search"""
    with patch("backend.news_store.search_news", return_value=[]):
        resp = await client.post("/api/news/search", json={"query": "test"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_get_event_summary(client):
    """GET /api/news/events/{symbol}"""
    with patch(
        "backend.news_store.get_event_summary",
        return_value={
            "symbol": "600519",
            "days": 30,
            "total_news": 0,
            "avg_sentiment": 0,
            "type_distribution": {},
        },
    ):
        resp = await client.get("/api/news/events/600519")
    assert resp.status_code == 200
    assert resp.json()["data"]["symbol"] == "600519"


@pytest.mark.anyio
async def test_get_event_impact_no_events(client):
    """GET /api/news/impact/{symbol} 无事件"""
    with patch("backend.news_store.list_news", return_value=[]):
        resp = await client.get("/api/news/impact/600519")
    assert resp.status_code == 200
    assert resp.json()["success"] is False
