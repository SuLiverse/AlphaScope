"""东方财富 Choice Provider - 金融数据终端 (Stub)

Choice 是东方财富的机构版数据终端, 覆盖行情、公告、研报、量化接口等。
需要 Choice 账号和 API 授权。
"""

from __future__ import annotations

import logging

from ..base import BaseProvider

logger = logging.getLogger(__name__)


class ChoiceProvider(BaseProvider):
    name = "choice"
    markets = ["CN"]
    data_types = ["news", "reports", "announcements", "prices", "fundamentals"]
    priority = 96
    license_level = "commercial"

    def __init__(self) -> None:
        super().__init__()
        from backend.datasource_config import get_active_key

        self._api_key = get_active_key("choice", "CHOICE_API_KEY")

    def _check_available(self) -> bool:
        if not self._api_key:
            logger.debug("Choice API Key 未配置 (CHOICE_API_KEY)")
            return False
        return True

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("Choice Provider 需要配置 CHOICE_API_KEY")

    def get_reports(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("Choice Provider 需要配置 CHOICE_API_KEY")

    def get_announcements(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("Choice Provider 需要配置 CHOICE_API_KEY")

    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("Choice Provider 需要配置 CHOICE_API_KEY")

    def get_fundamentals(self, query: dict, **kwargs) -> dict:
        raise NotImplementedError("Choice Provider 需要配置 CHOICE_API_KEY")
