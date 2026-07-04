"""
Web Search Provider: 联网搜索数据源。

支持 Tavily / SerpAPI / Bing Search 等搜索 API。
当前为 Tavily 实现，其他可通过配置扩展。
"""

import os
import logging
from typing import List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""

    title: str
    url: str
    snippet: str
    published_at: str = ""
    source: str = "web"
    score: float = 0.0


class WebSearchProvider:
    """联网搜索 Provider"""

    def __init__(self, provider: str = "tavily", api_key: str = ""):
        self.provider = provider
        self.api_key = api_key or os.getenv("TAVILY_API_KEY", "")
        self._available = bool(self.api_key)

    def is_available(self) -> bool:
        return self._available

    def search(self, query: str, max_results: int = 5) -> List[SearchResult]:
        """执行搜索"""
        if not self._available:
            return []

        if self.provider == "tavily":
            return self._search_tavily(query, max_results)
        else:
            logger.warning(f"不支持的搜索 Provider: {self.provider}")
            return []

    def _search_tavily(self, query: str, max_results: int) -> List[SearchResult]:
        """使用 Tavily API 搜索"""
        try:
            import requests

            resp = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": query,
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

            results = []
            for item in data.get("results", []):
                results.append(
                    SearchResult(
                        title=item.get("title", ""),
                        url=item.get("url", ""),
                        snippet=item.get("content", "")[:300],
                        published_at=item.get("published_date", ""),
                        source="tavily",
                        score=item.get("score", 0),
                    )
                )
            return results

        except ImportError:
            logger.warning("requests 未安装，无法使用 Tavily 搜索")
            return []
        except Exception as e:
            logger.warning(f"Tavily 搜索失败: {e}")
            return []

    def search_financial(self, query: str, stock_code: str = "", max_results: int = 5) -> List[SearchResult]:
        """金融相关搜索（自动添加金融关键词）"""
        enhanced_query = query
        if stock_code:
            enhanced_query = f"{stock_code} {query}"
        return self.search(enhanced_query, max_results)


# 单例
_provider: Optional[WebSearchProvider] = None


def get_web_search_provider() -> WebSearchProvider:
    """获取全局 Web 搜索 Provider"""
    global _provider
    if _provider is None:
        _provider = WebSearchProvider()
    return _provider
