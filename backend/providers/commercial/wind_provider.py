"""Wind 万得 Provider - 机构级金融数据 (Stub)

Wind 是国内领先的金融终端, 覆盖行情、宏观、财报、研报、债券、基金等。
需要 Wind 终端账号和 API 授权。

费用: 约 39,800 元/年 (全功能终端)
API: 支持 Python/MATLAB/R/C++/C#/VBA
"""

from __future__ import annotations

import logging

from ..base import BaseProvider

logger = logging.getLogger(__name__)


class WindProvider(BaseProvider):
    name = "wind"
    markets = ["CN"]
    data_types = [
        "news",
        "reports",
        "announcements",
        "prices",
        "fundamentals",
        "fund_flow",
    ]
    priority = 98
    license_level = "commercial"

    def __init__(self) -> None:
        super().__init__()
        from backend.datasource_config import get_active_key

        self._api_key = get_active_key("wind", "WIND_API_KEY")
        self._client = None

    def _check_available(self) -> bool:
        if not self._api_key:
            logger.debug("Wind API Key 未配置 (WIND_API_KEY)")
            return False
        try:
            # Wind SDK: from WindPy import w
            # w.start()
            return True
        except ImportError:
            logger.debug("Wind SDK 未安装 (WindPy)")
            return False

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("Wind Provider 需要配置 WIND_API_KEY 和安装 WindPy SDK")

    def get_reports(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("Wind Provider 需要配置 WIND_API_KEY 和安装 WindPy SDK")

    def get_announcements(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("Wind Provider 需要配置 WIND_API_KEY 和安装 WindPy SDK")

    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        raise NotImplementedError("Wind Provider 需要配置 WIND_API_KEY 和安装 WindPy SDK")

    def get_fundamentals(self, query: dict, **kwargs) -> dict:
        raise NotImplementedError("Wind Provider 需要配置 WIND_API_KEY 和安装 WindPy SDK")
