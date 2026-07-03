"""Tushare Pro Provider - 研报和公告的准专业数据源

需要 TUSHARE_TOKEN 环境变量
覆盖: 研报(research_report), 公告(anns_d), 行情, 财务
"""

from __future__ import annotations

import logging
from typing import Any

from .base import BaseProvider

logger = logging.getLogger(__name__)


class TushareProvider(BaseProvider):
    name = "tushare"
    markets = ["CN"]
    data_types = ["reports", "announcements", "prices", "fundamentals"]
    priority = 85
    license_level = "restricted"

    def __init__(self) -> None:
        super().__init__()
        from backend.datasource_config import get_active_key

        self._token = get_active_key("tushare", "TUSHARE_TOKEN")
        self._pro = None

    def _get_pro(self):
        if self._pro is None:
            if not self._token:
                raise ValueError("TUSHARE_TOKEN 环境变量未设置")
            import tushare as ts

            self._pro = ts.pro_api(self._token)
        return self._pro

    def get_reports(self, query: dict, **kwargs) -> list[dict]:
        """获取券商研报 (research_report 接口)"""
        try:
            pro = self._get_pro()
            params: dict[str, Any] = {}
            if query.get("symbol"):
                params["ts_code"] = query["symbol"]
            if query.get("start_date"):
                params["start_date"] = query["start_date"].replace("-", "")
            if query.get("end_date"):
                params["end_date"] = query["end_date"].replace("-", "")
            if query.get("report_type"):
                params["report_type"] = query["report_type"]
            if query.get("institution"):
                params["inst_name"] = query["institution"]

            df = pro.report_rc(**params) if params else pro.report_rc()
            if df is None or len(df) == 0:
                return []

            results = []
            for _, row in df.head(query.get("limit", 50)).iterrows():
                results.append(
                    {
                        "source": "tushare",
                        "upstream": "tushare",
                        "title": str(row.get("title", "")).strip(),
                        "institution": str(row.get("org_name", "")).strip(),
                        "authors": [str(row.get("author", ""))]
                        if row.get("author")
                        else [],
                        "report_type": str(row.get("report_type", "")).strip(),
                        "industry": str(row.get("industry_name", "")).strip(),
                        "rating": str(row.get("rating_name", "")).strip(),
                        "symbols": [str(row.get("stock_code", ""))]
                        if row.get("stock_code")
                        else [],
                        "datetime": str(row.get("pub_date", "")).strip(),
                        "pdf_url": str(row.get("url", "")).strip(),
                    }
                )
            return results
        except Exception as e:
            logger.debug("Tushare reports failed: %s", e)
            return []

    def get_announcements(self, query: dict, **kwargs) -> list[dict]:
        """获取上市公司公告 (anns_d 接口)"""
        try:
            pro = self._get_pro()
            params: dict[str, Any] = {}
            if query.get("symbol"):
                params["ts_code"] = query["symbol"]
            if query.get("start_date"):
                params["start_date"] = query["start_date"].replace("-", "")
            if query.get("end_date"):
                params["end_date"] = query["end_date"].replace("-", "")

            df = pro.anns_d(**params) if params else pro.anns_d()
            if df is None or len(df) == 0:
                return []

            results = []
            for _, row in df.head(query.get("limit", 50)).iterrows():
                results.append(
                    {
                        "source": "tushare",
                        "upstream": "tushare",
                        "symbol": str(row.get("ts_code", "")).strip(),
                        "title": str(row.get("title", "")).strip(),
                        "datetime": str(row.get("ann_date", "")).strip(),
                        "url": str(row.get("url", "")).strip(),
                        "pdf_url": str(row.get("url", "")).strip(),
                    }
                )
            return results
        except Exception as e:
            logger.debug("Tushare announcements failed: %s", e)
            return []

    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        """获取日线行情"""
        try:
            pro = self._get_pro()
            symbol = query.get("symbol", "")
            if not symbol:
                return []
            params: dict[str, Any] = {"ts_code": symbol}
            if query.get("start_date"):
                params["start_date"] = query["start_date"].replace("-", "")
            if query.get("end_date"):
                params["end_date"] = query["end_date"].replace("-", "")

            df = pro.daily(**params)
            if df is None or len(df) == 0:
                return []

            results = []
            for _, row in df.iterrows():
                results.append(
                    {
                        "symbol": symbol,
                        "market": "CN",
                        "date": str(row.get("trade_date", "")),
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "close": float(row.get("close", 0)),
                        "volume": float(row.get("vol", 0)),
                        "amount": float(row.get("amount", 0)),
                        "change_pct": float(row.get("pct_chg", 0)),
                        "source": "tushare",
                    }
                )
            return results
        except Exception as e:
            logger.debug("Tushare prices failed: %s", e)
            return []
