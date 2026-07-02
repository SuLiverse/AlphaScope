"""Finnhub Provider - US stock sentiment, insider trading, ESG data (free tier: 60 req/min)"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

from backend.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class FinnhubProvider(BaseProvider):
    """Finnhub data provider for US stock alternative data"""

    name = "finnhub"
    markets = ["US"]
    data_types = ["news", "sentiment", "insider", "esg", "calendar"]
    priority = 75
    license_level = "commercial"
    data_class = "alternative"
    freshness = "realtime"
    cost_tier = "freemium"
    rate_limit = {"per_minute": 60, "per_day": None}
    requires_key = True

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self) -> None:
        super().__init__()
        # 兼容两种环境变量:datasource_config 预设写入 FINNHUB_TOKEN,
        # 而 finnhub 官方 SDK 约定 FINNHUB_API_KEY。两者都接受,避免 UI 配置的 key 激活不了 provider。
        self._api_key = os.getenv("FINNHUB_API_KEY", "") or os.getenv("FINNHUB_TOKEN", "")

    def _headers(self) -> Dict[str, str]:
        return {"X-Finnhub-Token": self._api_key}

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        import requests

        url = f"{self.BASE_URL}{endpoint}"
        resp = requests.get(
            url, headers=self._headers(), params=params or {}, timeout=15
        )
        resp.raise_for_status()
        return resp.json()

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        """Get company news for US stocks"""
        symbol = query.get("symbol", "")
        if not symbol:
            return []
        try:
            from datetime import datetime, timedelta

            end = datetime.now().strftime("%Y-%m-%d")
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            raw = self._get(
                "/company-news", {"symbol": symbol, "from": start, "to": end}
            )
            if not isinstance(raw, list):
                return []
            return [
                {
                    "title": item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "source": f"finnhub/{item.get('source', 'unknown')}",
                    "datetime": item.get("datetime", ""),
                    "url": item.get("url", ""),
                    "symbols": [symbol],
                    "sentiment": item.get("sentiment", 0),
                }
                for item in raw[: query.get("limit", 20)]
            ]
        except Exception as e:
            logger.warning("Finnhub news failed: %s", e)
            return []

    def get_sentiment(self, query: dict, **kwargs) -> dict:
        """Get sentiment data for a stock"""
        symbol = query.get("symbol", "")
        if not symbol:
            return {}
        try:
            return self._get("/stock/sentiment", {"symbol": symbol})
        except Exception as e:
            logger.warning("Finnhub sentiment failed: %s", e)
            return {}

    def get_insider_transactions(self, query: dict, **kwargs) -> list:
        """Get insider trading data"""
        symbol = query.get("symbol", "")
        if not symbol:
            return []
        try:
            raw = self._get("/stock/insider-transactions", {"symbol": symbol})
            return raw.get("data", [])[: query.get("limit", 20)]
        except Exception as e:
            logger.warning("Finnhub insider failed: %s", e)
            return []

    def get_esg(self, query: dict, **kwargs) -> dict:
        """Get ESG scores"""
        symbol = query.get("symbol", "")
        if not symbol:
            return {}
        try:
            return self._get("/stock/esg", {"symbol": symbol})
        except Exception as e:
            logger.warning("Finnhub ESG failed: %s", e)
            return {}

    def get_calendar(self, query: dict, **kwargs) -> dict:
        """Get earnings calendar and economic events"""
        try:
            from datetime import datetime, timedelta

            start = datetime.now().strftime("%Y-%m-%d")
            end = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
            return self._get("/calendar/earnings", {"from": start, "to": end})
        except Exception as e:
            logger.warning("Finnhub calendar failed: %s", e)
            return {}
