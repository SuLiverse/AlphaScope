"""同花顺 iFinD Provider - 金融数据终端 (Stub)

iFinD 是同花顺的机构版金融数据终端, 覆盖 A 股、公告、研报、问财等。
需要 iFinD 账号和 API 授权。

费用: 标准版约 5,800 元/年
"""

from __future__ import annotations

import logging

from ..base import BaseProvider

logger = logging.getLogger(__name__)


class IFinDProvider(BaseProvider):
    name = "ifind"
    markets = ["CN"]
    data_types = ["news", "reports", "announcements", "prices", "fundamentals"]
    priority = 97
    license_level = "commercial"

    def __init__(self) -> None:
        super().__init__()
        from backend.datasource_config import get_active_key

        self._api_key = get_active_key("ifind", "IFIND_API_KEY")

    def _check_available(self) -> bool:
        if not self._api_key:
            logger.debug("iFinD API Key 未配置 (IFIND_API_KEY)")
            return False
        return True

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("iFinD Provider 需要配置 IFIND_API_KEY")

    def get_reports(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("iFinD Provider 需要配置 IFIND_API_KEY")

    def get_announcements(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("iFinD Provider 需要配置 IFIND_API_KEY")

    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("iFinD Provider 需要配置 IFIND_API_KEY")

    def get_fundamentals(self, query: dict, **kwargs) -> dict:
        raise NotImplementedError("iFinD Provider 需要配置 IFIND_API_KEY")
