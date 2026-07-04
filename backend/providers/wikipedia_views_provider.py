"""Wikipedia Views Provider - company page views as retail attention indicator (free REST API)"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class WikipediaViewsProvider(BaseProvider):
    """Wikipedia page views data provider

    Company Wikipedia page views correlate with retail attention.
    Academic research validates this as a leading indicator for stock trading volume.
    """

    name = "wikipedia_views"
    markets = ["GLOBAL"]
    data_types = ["alternative", "attention"]
    priority = 50
    license_level = "public"
    data_class = "alternative"
    freshness = "daily"
    cost_tier = "free"
    rate_limit = {"per_minute": 200, "per_day": None}
    requires_key = False

    BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        import requests

        url = f"{self.BASE_URL}{endpoint}"
        headers = {"User-Agent": "AlphaScope/1.0 (https://github.com/TIANWEN-cpu/AlphaScope)"}
        resp = requests.get(url, headers=headers, params=params or {}, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_attention(self, query: dict, **kwargs) -> dict:
        """Get Wikipedia page views for a company"""
        page_title = query.get("page_title") or query.get("keyword", "")
        if not page_title:
            return {}
        try:
            from datetime import datetime, timedelta

            end = datetime.now().strftime("%Y%m%d")
            start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")

            # Try English Wikipedia first, then Chinese
            for lang in ["en", "zh"]:
                try:
                    raw = self._get(f"/all-access/user/{lang.wikipedia}/{page_title}/daily/{start}/{end}")
                    items = raw.get("items", [])
                    if items:
                        views = [item.get("views", 0) for item in items]
                        avg_views = sum(views) / len(views) if views else 0
                        recent = sum(views[-7:]) / 7 if len(views) >= 7 else views[-1] if views else 0
                        trend_pct = ((recent - avg_views) / max(avg_views, 1)) * 100

                        return {
                            "page_title": page_title,
                            "language": lang,
                            "avg_daily_views": int(avg_views),
                            "recent_7day_avg": int(recent),
                            "trend_pct": round(trend_pct, 1),
                            "total_30day": sum(views),
                            "source": "wikipedia",
                        }
                except Exception:
                    continue

            return {}
        except Exception as e:
            logger.warning("Wikipedia views failed: %s", e)
            return {}

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        """Wikipedia doesn't provide news"""
        return []

    def _map_symbol_to_page(self, symbol: str, name: str = "") -> str:
        """Map stock symbol to Wikipedia page title"""
        # Common mappings
        symbol_map = {
            "600519": "Kweichow_Moutai",
            "000858": "Wuliangye",
            "300750": "CATL",
            "AAPL": "Apple_Inc.",
            "GOOGL": "Alphabet_Inc.",
            "MSFT": "Microsoft",
            "TSLA": "Tesla,_Inc.",
            "NVDA": "Nvidia",
        }
        if symbol in symbol_map:
            return symbol_map[symbol]
        # Use company name if available
        if name:
            return name.replace(" ", "_")
        return ""
