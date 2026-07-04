"""Northbound Capital Provider - 沪深港通北向资金 (free via AkShare)"""

from __future__ import annotations

import logging

from backend.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class NorthboundProvider(BaseProvider):
    """Northbound capital flow (沪深港通北向资金) provider

    Key Alpha signal for A-share market: foreign institutional money flow.
    Data published daily at 18:00 CST after market close.
    """

    name = "northbound"
    markets = ["CN"]
    data_types = ["fund_flow", "northbound", "institutional"]
    priority = 85
    license_level = "public"
    data_class = "sentiment"
    freshness = "daily"
    cost_tier = "free"
    rate_limit = {"per_minute": 30, "per_day": None}
    requires_key = False

    def get_fund_flow(self, query: dict, **kwargs) -> list[dict]:
        """Get northbound capital flow data"""
        try:
            import akshare as ak

            # Daily northbound flow
            df = ak.stock_hsgt_north_net_flow_in_em(symbol="北向")
            if df is None or df.empty:
                return []
            limit = query.get("limit", 30)
            result = []
            for _, row in df.tail(limit).iterrows():
                result.append(
                    {
                        "date": str(row.get("date", row.get("日期", ""))),
                        "net_flow": float(row.get("value", row.get("当日净流入", 0))),
                        "buy_volume": float(row.get("当日买入", 0)) if "当日买入" in row.index else 0,
                        "sell_volume": float(row.get("当日卖出", 0)) if "当日卖出" in row.index else 0,
                        "source": "northbound",
                        "type": "northbound_flow",
                    }
                )
            return result
        except Exception as e:
            logger.warning("Northbound flow failed: %s", e)
            return []

    def get_top_holdings(self, query: dict, **kwargs) -> list[dict]:
        """Get top northbound holdings"""
        try:
            import akshare as ak

            df = ak.stock_hsgt_hold_stock_em(market="北向")
            if df is None or df.empty:
                return []
            limit = query.get("limit", 50)
            result = []
            for _, row in df.head(limit).iterrows():
                result.append(
                    {
                        "symbol": str(row.get("代码", "")),
                        "name": str(row.get("名称", "")),
                        "holding_ratio": float(row.get("持股占比", 0)) if "持股占比" in row.index else 0,
                        "net_flow": float(row.get("当日净买入", 0)) if "当日净买入" in row.index else 0,
                        "source": "northbound",
                    }
                )
            return result
        except Exception as e:
            logger.warning("Northbound holdings failed: %s", e)
            return []

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        """Northbound doesn't provide news, use fund_flow instead"""
        return self.get_fund_flow(query, **kwargs)
