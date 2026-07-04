"""东方财富 Provider - 通过 curl_cffi 访问东财搜索API

覆盖: 新闻搜索, 公告, 研报
"""

from __future__ import annotations

import logging

from .base import BaseProvider

logger = logging.getLogger(__name__)


class EastMoneyProvider(BaseProvider):
    name = "eastmoney"
    markets = ["CN"]
    data_types = ["news", "reports", "announcements"]
    priority = 70
    license_level = "research_only"

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        """东财快讯 - 委托给 AkShare Provider 的东财部分"""
        # 东财数据已在 AkShareProvider 中实现
        # 此 Provider 主要提供搜索能力
        keyword = query.get("keywords", "")
        if not keyword:
            return []

        try:
            import requests

            url = "https://search-api-web.eastmoney.com/search/jsonp"
            params = {
                "cb": "jQuery",
                "param": (
                    f'{{"uid":"","keyword":"{keyword}","type":["cmsArticleWebOld"],'
                    f'"client":"web","clientType":"web","clientVersion":"curr",'
                    f'"param":{{"cmsArticleWebOld":{{"searchScope":"default","sort":"default",'
                    f'"pageIndex":1,"pageSize":{query.get("limit", 20)},'
                    f'"preTag":"<em>","postTag":"</em>"}}}}}}'
                ),
            }
            resp = requests.get(url, params=params, timeout=10)
            text = resp.text
            # 解析 JSONP
            start = text.find("(") + 1
            end = text.rfind(")")
            import json

            data = json.loads(text[start:end])
            items = data.get("result", {}).get("cmsArticleWebOld", {}).get("list", [])
            results = []
            for item in items:
                results.append(
                    {
                        "source": "eastmoney",
                        "upstream": "eastmoney",
                        "title": item.get("title", "").replace("<em>", "").replace("</em>", ""),
                        "summary": item.get("content", "")[:200],
                        "datetime": item.get("date", ""),
                        "url": item.get("url", ""),
                    }
                )
            if results:
                self._record_success(0)
            return results
        except Exception as e:
            logger.debug("EastMoney search failed: %s", e)
            self._record_failure(str(e))
            return []

    def get_reports(self, query: dict, **kwargs) -> list[dict]:
        """东财研报 - 委托给 AkShare"""
        # 通过 AkShare 的东财研报接口获取
        try:
            import akshare as ak

            symbol = query.get("symbol", "")
            if not symbol:
                return []
            df = ak.stock_research_report_em(symbol=symbol)
            if df is None or len(df) == 0:
                return []
            results = []
            for _, row in df.head(query.get("limit", 30)).iterrows():
                results.append(
                    {
                        "source": "eastmoney",
                        "upstream": "eastmoney",
                        "title": str(row.get("报告名称", "")).strip(),
                        "institution": str(row.get("机构", "")).strip(),
                        "rating": str(row.get("最新评级", "")).strip(),
                        "datetime": str(row.get("日期", "")).strip(),
                        "pdf_url": str(row.get("报告链接", "")).strip(),
                        "symbols": [symbol],
                    }
                )
            return results
        except Exception as e:
            logger.debug("EastMoney reports failed: %s", e)
            return []
