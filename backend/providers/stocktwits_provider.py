"""Stocktwits Provider - US retail sentiment with bullish/bearish voting (free REST API)"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class StocktwitsProvider(BaseProvider):
    """Stocktwits data provider for US retail sentiment

    Standard for US retail sentiment: each message has bullish/bearish vote.
    Free REST API with no authentication required for basic access.
    """

    name = "stocktwits"
    markets = ["US"]
    data_types = ["sentiment", "alternative", "social"]
    priority = 65
    license_level = "public"
    data_class = "alternative"
    freshness = "realtime"
    cost_tier = "free"
    rate_limit = {"per_minute": 200, "per_day": None}
    requires_key = False

    BASE_URL = "https://api.stocktwits.com/api/2"

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        import requests

        url = f"{self.BASE_URL}{endpoint}"
        resp = requests.get(url, params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_sentiment(self, query: dict, **kwargs) -> dict:
        """Get Stocktwits sentiment for a stock"""
        symbol = query.get("symbol", "")
        if not symbol:
            return {}
        try:
            raw = self._get(f"/streams/symbol/{symbol}.json", {"limit": query.get("limit", 30)})
            messages = raw.get("messages", [])
            if not messages:
                return {"symbol": symbol, "sentiment": 0.5, "message_count": 0}

            bullish = 0
            bearish = 0
            total = 0
            for msg in messages:
                sentiment = msg.get("entities", {}).get("sentiment", {})
                if sentiment:
                    if sentiment.get("basic") == "Bullish":
                        bullish += 1
                    elif sentiment.get("basic") == "Bearish":
                        bearish += 1
                total += 1

            if total > 0:
                sentiment_score = bullish / total  # 0 = all bearish, 1 = all bullish
            else:
                sentiment_score = 0.5

            return {
                "symbol": symbol,
                "bullish_count": bullish,
                "bearish_count": bearish,
                "total_messages": total,
                "sentiment_score": round(sentiment_score, 2),
                "source": "stocktwits",
            }
        except Exception as e:
            logger.warning("Stocktwits sentiment failed: %s", e)
            return {}

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        """Get Stocktwits messages as news items"""
        symbol = query.get("symbol", "")
        if not symbol:
            return []
        try:
            raw = self._get(f"/streams/symbol/{symbol}.json", {"limit": query.get("limit", 10)})
            messages = raw.get("messages", [])
            result = []
            for msg in messages:
                sentiment = msg.get("entities", {}).get("sentiment", {})
                sentiment_val = (
                    0.7 if sentiment.get("basic") == "Bullish" else 0.3 if sentiment.get("basic") == "Bearish" else 0.5
                )
                result.append(
                    {
                        "title": msg.get("body", "")[:100],
                        "summary": msg.get("body", ""),
                        "source": "stocktwits",
                        "datetime": msg.get("created_at", ""),
                        "url": f"https://stocktwits.com/message/{msg.get('id', '')}",
                        "symbols": [symbol],
                        "sentiment": sentiment_val,
                    }
                )
            return result
        except Exception as e:
            logger.warning("Stocktwits news failed: %s", e)
            return []
