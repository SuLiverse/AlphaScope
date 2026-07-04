"""FRED Provider - Federal Reserve Economic Data (800,000+ economic time series, completely free)"""

from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

from backend.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class FredProvider(BaseProvider):
    """FRED (Federal Reserve Economic Data) provider for macro economic data"""

    name = "fred"
    markets = ["GLOBAL", "US"]
    data_types = ["macro", "interest_rate", "gdp", "cpi", "employment", "housing"]
    priority = 90
    license_level = "public"
    data_class = "macro"
    freshness = "daily"
    cost_tier = "free"
    rate_limit = {"per_minute": 120, "per_day": None}
    requires_key = True

    BASE_URL = "https://api.stlouisfed.org/fred"

    # Key economic indicators
    KEY_SERIES = {
        "gdp": "GDP",
        "unemployment": "UNRATE",
        "cpi": "CPIAUCSL",
        "fed_funds_rate": "FEDFUNDS",
        "10y_treasury": "DGS10",
        "2y_treasury": "DGS2",
        "vix": "VIXCLS",
        "sp500": "SP500",
        "usd_cny": "DEXCHUS",
        "industrial_production": "INDPRO",
        "consumer_sentiment": "UMCSENT",
        "housing_starts": "HOUST",
        "retail_sales": "RSAFS",
        "pmi": "MANEMP",
    }

    def __init__(self) -> None:
        super().__init__()
        self._api_key = os.getenv("FRED_API_KEY", "")

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Any:
        import requests

        url = f"{self.BASE_URL}{endpoint}"
        params = params or {}
        params["api_key"] = self._api_key
        params["file_type"] = "json"
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_macro(self, query: dict, **kwargs) -> dict:
        """Get macro economic data"""
        series_id = query.get("series_id", "")
        if not series_id:
            # Return overview of key indicators
            return self._get_overview()
        try:
            raw = self._get(
                "/series/observations",
                {
                    "series_id": series_id,
                    "limit": query.get("limit", 30),
                    "sort_order": "desc",
                },
            )
            observations = raw.get("observations", [])
            return {
                "series_id": series_id,
                "observations": [{"date": obs.get("date"), "value": obs.get("value")} for obs in observations],
            }
        except Exception as e:
            logger.warning("FRED series %s failed: %s", series_id, e)
            return {}

    def _get_overview(self) -> dict:
        """Get overview of key economic indicators"""
        result = {}
        for name, series_id in list(self.KEY_SERIES.items())[:8]:
            try:
                raw = self._get(
                    "/series/observations",
                    {
                        "series_id": series_id,
                        "limit": 2,
                        "sort_order": "desc",
                    },
                )
                observations = raw.get("observations", [])
                if observations:
                    latest = observations[0]
                    result[name] = {
                        "series_id": series_id,
                        "date": latest.get("date"),
                        "value": latest.get("value"),
                    }
            except Exception as e:
                logger.debug("FRED %s failed: %s", name, e)
        return result

    def get_series(self, series_id: str, limit: int = 30) -> list:
        """Get time series data for a specific indicator"""
        try:
            raw = self._get(
                "/series/observations",
                {
                    "series_id": series_id,
                    "limit": limit,
                    "sort_order": "desc",
                },
            )
            return raw.get("observations", [])
        except Exception as e:
            logger.warning("FRED series %s failed: %s", series_id, e)
            return []

    def search(self, query: str, limit: int = 10) -> list:
        """Search for economic series"""
        try:
            raw = self._get(
                "/series/search",
                {
                    "search_text": query,
                    "limit": limit,
                },
            )
            return raw.get("seriess", [])
        except Exception as e:
            logger.warning("FRED search failed: %s", e)
            return []

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        """FRED doesn't provide news, return empty"""
        return []
