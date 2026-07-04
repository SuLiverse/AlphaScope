"""Reddit Provider - r/wallstreetbets sentiment (free via PRAW, 60 req/min)"""

from __future__ import annotations

import os
import logging

from backend.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class RedditProvider(BaseProvider):
    """Reddit data provider for retail sentiment

    r/wallstreetbets mention frequency is a strong predictor of short-term volatility.
    Academic research validates Reddit sentiment as a leading indicator.
    """

    name = "reddit"
    markets = ["US"]
    data_types = ["sentiment", "alternative", "social"]
    priority = 70
    license_level = "public"
    data_class = "alternative"
    freshness = "realtime"
    cost_tier = "free"
    rate_limit = {"per_minute": 60, "per_day": None}
    requires_key = True

    def __init__(self) -> None:
        super().__init__()
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                import praw

                self._client = praw.Reddit(
                    client_id=os.getenv("REDDIT_CLIENT_ID", ""),
                    client_secret=os.getenv("REDDIT_CLIENT_SECRET", ""),
                    user_agent="AlphaScope/1.0",
                )
            except ImportError:
                logger.warning("PRAW not installed, Reddit provider unavailable")
                return None
        return self._client

    def get_sentiment(self, query: dict, **kwargs) -> dict:
        """Get Reddit sentiment for a stock"""
        symbol = query.get("symbol", "")
        if not symbol:
            return {}
        client = self._get_client()
        if not client:
            return {}

        try:
            subreddit = client.subreddit("wallstreetbets+stocks+investing")
            mentions = []
            sentiment_scores = []

            for submission in subreddit.search(symbol, limit=query.get("limit", 20), sort="new"):
                title = submission.title
                score = submission.score
                mentions.append(
                    {
                        "title": title,
                        "score": score,
                        "url": submission.url,
                        "created": submission.created_utc,
                        "num_comments": submission.num_comments,
                    }
                )
                # Simple sentiment: positive upvotes = bullish
                if score > 100:
                    sentiment_scores.append(0.7)
                elif score > 50:
                    sentiment_scores.append(0.5)
                else:
                    sentiment_scores.append(0.3)

            avg_sentiment = sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0.5
            return {
                "symbol": symbol,
                "mention_count": len(mentions),
                "avg_sentiment": round(avg_sentiment, 2),
                "top_posts": mentions[:5],
                "source": "reddit",
            }
        except Exception as e:
            logger.warning("Reddit sentiment failed: %s", e)
            return {}

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        """Get trending posts as news items"""
        symbol = query.get("symbol", "")
        if not symbol:
            return []
        client = self._get_client()
        if not client:
            return []

        try:
            subreddit = client.subreddit("wallstreetbets+stocks")
            result = []
            for submission in subreddit.search(symbol, limit=query.get("limit", 10), sort="hot"):
                result.append(
                    {
                        "title": submission.title,
                        "summary": submission.selftext[:200] if submission.selftext else "",
                        "source": "reddit/wallstreetbets",
                        "datetime": str(submission.created_utc),
                        "url": submission.url,
                        "symbols": [symbol],
                        "sentiment": 0.7 if submission.score > 100 else 0.5,
                    }
                )
            return result
        except Exception as e:
            logger.warning("Reddit news failed: %s", e)
            return []
