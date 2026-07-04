"""SEC EDGAR Provider - 美股公告和财报官方核心源

免费, 无需API Key, 需设置 User-Agent
"""

from __future__ import annotations

import logging
import os

import requests

from .base import BaseProvider

logger = logging.getLogger(__name__)

SEC_BASE = "https://data.sec.gov"
_SUBMISSIONS_URL = f"{SEC_BASE}/submissions"
_COMPANY_FACTS_URL = f"{SEC_BASE}/api/xbrl/companyfacts"
# SEC 提供免费的 ticker → CIK 映射
_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"


class SECProvider(BaseProvider):
    name = "sec"
    markets = ["US"]
    data_types = ["announcements", "fundamentals"]
    priority = 95
    license_level = "public"

    def __init__(self) -> None:
        super().__init__()
        self._user_agent = os.environ.get(
            "SEC_USER_AGENT",
            "AlphaScope research@example.com",
        )
        self._headers = {"User-Agent": self._user_agent}
        self._ticker_cik_map: dict[str, str] = {}
        self._cik_loaded = False

    def _get(self, url: str) -> dict:
        resp = requests.get(url, headers=self._headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def _load_ticker_cik_map(self) -> None:
        """加载 SEC 官方 ticker → CIK 映射表"""
        if self._cik_loaded:
            return
        try:
            data = self._get(_TICKER_CIK_URL)
            # 格式: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
            for entry in data.values():
                ticker = entry.get("ticker", "").upper()
                cik = str(entry.get("cik_str", ""))
                if ticker and cik:
                    self._ticker_cik_map[ticker] = cik.zfill(10)
            self._cik_loaded = True
            logger.info("SEC ticker-CIK 映射已加载: %d 条", len(self._ticker_cik_map))
        except Exception as e:
            logger.warning("加载 SEC ticker-CIK 映射失败: %s", e)

    def get_announcements(self, query: dict, **kwargs) -> list[dict]:
        """获取公司最近提交文件 (10-K, 10-Q, 8-K 等)"""
        cik = query.get("cik", "")
        symbol = query.get("symbol", "")

        # 如果只有 symbol, 通过映射表查找 CIK
        if not cik and symbol:
            cik = self._symbol_to_cik(symbol)
        if not cik:
            return []

        # 补齐 CIK 到 10 位
        cik_padded = cik.zfill(10)
        form_filter = query.get("form_type", "")
        limit = query.get("limit", 30)

        try:
            data = self._get(f"{_SUBMISSIONS_URL}/CIK{cik_padded}.json")
            company = data.get("name", "")
            recent = data.get("filings", {}).get("recent", {})

            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            accessions = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])
            descriptions = recent.get("primaryDocDescription", [])

            results = []
            for i in range(min(len(forms), limit * 2)):  # 多取一些以应对过滤
                if form_filter and forms[i] != form_filter:
                    continue
                if len(results) >= limit:
                    break

                acc_no = accessions[i].replace("-", "")
                desc = descriptions[i] if i < len(descriptions) else ""
                doc_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_no}/{primary_docs[i]}"

                results.append(
                    {
                        "source": "sec",
                        "upstream": "sec",
                        "symbol": symbol,
                        "company_name": company,
                        "title": f"{forms[i]} - {desc}" if desc else f"{forms[i]} - {company}",
                        "category": self._form_to_category(forms[i]),
                        "datetime": dates[i],
                        "url": doc_url,
                        "source_url": doc_url,
                        "form_type": forms[i],
                        "accession_number": accessions[i],
                        "confidence": 0.95,
                    }
                )

            self._record_success(0)
            return results

        except Exception as e:
            self._record_failure(str(e))
            logger.debug("SEC announcements failed: %s", e)
            return []

    def get_fundamentals(self, query: dict, **kwargs) -> dict:
        """获取公司 XBRL 财务数据"""
        cik = query.get("cik", "")
        if not cik:
            symbol = query.get("symbol", "")
            if symbol:
                cik = self._symbol_to_cik(symbol)
        if not cik:
            return {}

        cik_padded = cik.zfill(10)
        try:
            data = self._get(f"{_COMPANY_FACTS_URL}/CIK{cik_padded}.json")
            self._record_success(0)
            return {
                "company_name": data.get("entityName", ""),
                "cik": cik,
                "source": "sec",
                "facts": data.get("facts", {}),
            }
        except Exception as e:
            self._record_failure(str(e))
            logger.debug("SEC fundamentals failed: %s", e)
            return {}

    def _symbol_to_cik(self, symbol: str) -> str:
        """将 ticker 转为 CIK (使用 SEC 官方映射表)"""
        self._load_ticker_cik_map()
        cik = self._ticker_cik_map.get(symbol.upper(), "")
        if not cik:
            logger.debug("SEC 未找到 ticker %s 的 CIK", symbol)
        return cik

    @staticmethod
    def _form_to_category(form_type: str) -> str:
        """将 SEC 表格类型映射为公告类别"""
        mapping = {
            "10-K": "earnings",
            "10-Q": "earnings",
            "20-F": "earnings",
            "8-K": "other",
            "DEF 14A": "other",
            "S-1": "financing",
            "S-3": "financing",
            "424B": "financing",
            "SC 13D": "mna",
            "SC 13G": "mna",
            "DEFA14A": "other",
        }
        return mapping.get(form_type, "other")
