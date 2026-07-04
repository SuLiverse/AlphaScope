"""基金数据源适配 — 统一接口获取基金信息、净值、持仓"""

from __future__ import annotations

import logging
import asyncio
from typing import Any, Optional

logger = logging.getLogger(__name__)

FUND_PROVIDER_TIMEOUT_SECONDS = 8.0


async def _run_blocking(fn, *, name: str):
    return await asyncio.wait_for(
        asyncio.to_thread(fn),
        timeout=FUND_PROVIDER_TIMEOUT_SECONDS,
    )


class FundDataProvider:
    """基金数据源基类"""

    async def search(self, keyword: str) -> list[dict[str, Any]]:
        """搜索基金"""
        raise NotImplementedError

    async def get_info(self, code: str) -> Optional[dict[str, Any]]:
        """获取基金基本信息"""
        raise NotImplementedError

    async def get_nav_history(self, code: str, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        """获取历史净值"""
        raise NotImplementedError


class AkShareFundProvider(FundDataProvider):
    """通过 AkShare 获取基金数据"""

    async def search(self, keyword: str) -> list[dict[str, Any]]:
        try:
            import akshare as ak

            df = await _run_blocking(ak.fund_name_em, name="fund-search")
            mask = df["基金简称"].str.contains(keyword, na=False)
            results = df[mask].head(20)
            return [
                {
                    "code": row["基金代码"],
                    "name": row["基金简称"],
                    "fund_type": row.get("基金类型", ""),
                    "company": row.get("管理人", ""),
                }
                for _, row in results.iterrows()
            ]
        except Exception as e:
            logger.warning(f"基金搜索失败: {e}")
            return []

    async def get_info(self, code: str) -> Optional[dict[str, Any]]:
        try:
            import akshare as ak

            df = await _run_blocking(
                lambda: ak.fund_individual_basic_info_xq(symbol=code),
                name="fund-info",
            )
            if df.empty:
                return None
            info = dict(zip(df["item"], df["value"]))
            return {
                "code": code,
                "name": info.get("基金名称", ""),
                "fund_type": info.get("基金类型", ""),
                "manager": info.get("基金经理", ""),
                "company": info.get("基金公司", ""),
                "inception_date": info.get("成立日期", ""),
                "total_assets": info.get("资产规模", 0),
            }
        except Exception as e:
            logger.warning(f"获取基金信息失败 {code}: {e}")
            return None

    async def get_nav_history(self, code: str, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        try:
            import akshare as ak

            df = await _run_blocking(
                lambda: ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势"),
                name="fund-nav",
            )
            if df.empty:
                return []
            records = []
            for _, row in df.iterrows():
                records.append(
                    {
                        "date": str(row.get("净值日期", "")),
                        "nav": float(row.get("单位净值", 0)),
                        "daily_return": float(row.get("日增长率", 0)) / 100 if "日增长率" in row else None,
                    }
                )
            if start_date:
                records = [r for r in records if r["date"] >= start_date]
            if end_date:
                records = [r for r in records if r["date"] <= end_date]
            return records
        except Exception as e:
            logger.warning(f"获取净值失败 {code}: {e}")
            return []


class CachedFundProvider(FundDataProvider):
    """带缓存的基金数据源"""

    def __init__(self, inner: FundDataProvider):
        self._inner = inner
        self._cache: dict[str, Any] = {}

    async def search(self, keyword: str) -> list[dict[str, Any]]:
        return await self._inner.search(keyword)

    async def get_info(self, code: str) -> Optional[dict[str, Any]]:
        cache_key = f"info:{code}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = await self._inner.get_info(code)
        if result:
            self._cache[cache_key] = result
        return result

    async def get_nav_history(self, code: str, start_date: str = "", end_date: str = "") -> list[dict[str, Any]]:
        cache_key = f"nav:{code}:{start_date}:{end_date}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        result = await self._inner.get_nav_history(code, start_date, end_date)
        self._cache[cache_key] = result
        return result


# 默认数据源
_default_provider: Optional[FundDataProvider] = None


def get_provider() -> FundDataProvider:
    global _default_provider
    if _default_provider is None:
        _default_provider = CachedFundProvider(AkShareFundProvider())
    return _default_provider


def set_provider(provider: FundDataProvider):
    global _default_provider
    _default_provider = provider
