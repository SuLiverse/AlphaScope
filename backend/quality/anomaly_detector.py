"""
Data Anomaly Detector (v0.12)

Simple rule-based + historical comparison to detect obviously bad data:
- Zero/negative prices
- Price moves exceeding limit-up/down
- Truncated or garbled news titles
- Duplicate timestamps with same title
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Detect anomalies in price and news data"""

    # A-stock limit-up/down: 10% for main board, 20% for ChiNext/STAR
    DEFAULT_PRICE_LIMIT_PCT = 10.0
    CHINEXT_STAR_PRICE_LIMIT_PCT = 20.0

    # Minimum title length (characters)
    MIN_TITLE_LENGTH = 4

    # Max same-timestamp same-title count before flagging
    MAX_DUPLICATE_TIMESTAMP = 3

    def check_price(
        self,
        bar: Dict[str, Any],
        history: Optional[List[Dict[str, Any]]] = None,
        symbol: str = "",
    ) -> List[str]:
        """
        Check a price bar for anomalies.

        Args:
            bar: Price bar dict with keys: open, high, low, close, volume, date
            history: Previous price bars for comparison
            symbol: Stock symbol for limit-up/down detection

        Returns:
            List of anomaly descriptions (empty = no anomalies)
        """
        anomalies = []

        close = bar.get("close", 0)
        open_ = bar.get("open", 0)
        high = bar.get("high", 0)
        low = bar.get("low", 0)
        volume = bar.get("volume", 0)

        # Zero or negative prices
        if close <= 0:
            anomalies.append(f"收盘价异常: {close}")
        if open_ < 0:
            anomalies.append(f"开盘价异常: {open_}")
        if high < 0:
            anomalies.append(f"最高价异常: {high}")
        if low < 0:
            anomalies.append(f"最低价异常: {low}")

        # Price consistency
        if high > 0 and low > 0 and high < low:
            anomalies.append(f"最高价({high}) < 最低价({low})")

        # Volume anomaly: zero volume but price changed
        if history and len(history) > 0:
            prev_close = history[-1].get("close", 0)
            if prev_close > 0 and volume == 0 and close != prev_close:
                anomalies.append(f"成交量为0但价格变化: {prev_close} -> {close}")

        # Limit-up/down check
        if history and len(history) > 0:
            prev_close = history[-1].get("close", 0)
            if prev_close > 0:
                change_pct = abs((close - prev_close) / prev_close) * 100
                limit = self._get_price_limit(symbol)
                if change_pct > limit + 0.5:  # 0.5% tolerance
                    anomalies.append(
                        f"涨跌幅({change_pct:.1f}%)超过涨跌停限制({limit}%)"
                    )

        return anomalies

    def check_news(
        self, news: Dict[str, Any], all_news: Optional[List[Dict[str, Any]]] = None
    ) -> List[str]:
        """
        Check a news item for anomalies.

        Args:
            news: News dict with keys: title, datetime, source
            all_news: All news items for duplicate detection

        Returns:
            List of anomaly descriptions (empty = no anomalies)
        """
        anomalies = []

        title = news.get("title", "")
        dt = news.get("datetime", "")
        news.get("source", "")

        # Title too short
        if len(title.strip()) < self.MIN_TITLE_LENGTH:
            anomalies.append(f"标题过短({len(title.strip())}字符): '{title[:20]}'")

        # Title is garbled (mostly non-Chinese, non-ASCII)
        if title and self._is_garbled(title):
            anomalies.append(f"标题可能是乱码: '{title[:30]}'")

        # Duplicate timestamp check
        if all_news and dt:
            same_ts_count = sum(
                1
                for n in all_news
                if n.get("datetime") == dt and n.get("title") == title
            )
            if same_ts_count > self.MAX_DUPLICATE_TIMESTAMP:
                anomalies.append(f"同一时间戳({dt})同标题出现{same_ts_count}次")

        return anomalies

    def check_batch(
        self,
        prices: Optional[List[Dict[str, Any]]] = None,
        news: Optional[List[Dict[str, Any]]] = None,
        symbol: str = "",
    ) -> Dict[str, Any]:
        """
        Batch check prices and news for anomalies.

        Returns:
            {
                "price_anomalies": [{bar_date, anomalies}],
                "news_anomalies": [{title, anomalies}],
                "total_anomalies": int,
            }
        """
        price_results = []
        news_results = []

        if prices:
            for i, bar in enumerate(prices):
                history = prices[:i] if i > 0 else []
                anomalies = self.check_price(bar, history, symbol)
                if anomalies:
                    price_results.append(
                        {
                            "date": bar.get("date", "unknown"),
                            "anomalies": anomalies,
                        }
                    )

        if news:
            for item in news:
                anomalies = self.check_news(item, news)
                if anomalies:
                    news_results.append(
                        {
                            "title": item.get("title", "")[:50],
                            "anomalies": anomalies,
                        }
                    )

        total = len(price_results) + len(news_results)
        if total > 0:
            logger.warning(
                "数据异常检测: %d 个价格异常, %d 个新闻异常",
                len(price_results),
                len(news_results),
            )

        return {
            "price_anomalies": price_results,
            "news_anomalies": news_results,
            "total_anomalies": total,
        }

    def _get_price_limit(self, symbol: str) -> float:
        """Get price limit percentage based on stock symbol.

        A 股主板 10% / 创业板(300)+科创板(688)20%。港股(5 位数字)、美股(字母代码)
        无涨跌停限制 → 返大值(999)避免误报"超涨跌停"。
        """
        if not symbol:
            return self.DEFAULT_PRICE_LIMIT_PCT
        digits = re.sub(r"\D", "", symbol)
        # 港股 5 位纯数字(如 00700)→ 无涨跌停
        if len(digits) == 5 and digits.isdigit():
            return 999.0
        # 美股字母代码(如 AAPL)→ 无涨跌停
        if not symbol[:1].isdigit():
            return 999.0
        # ChiNext (300xxx) and STAR (688xxx) have 20% limit
        if symbol.startswith("300") or symbol.startswith("688"):
            return self.CHINEXT_STAR_PRICE_LIMIT_PCT
        return self.DEFAULT_PRICE_LIMIT_PCT

    def _is_garbled(self, text: str) -> bool:
        """Check if text is garbled (mostly non-Chinese, non-ASCII)"""
        if not text:
            return False
        # Count Chinese chars, ASCII chars, and other
        chinese = sum(1 for c in text if "一" <= c <= "鿿")
        ascii_chars = sum(1 for c in text if ord(c) < 128)
        total = len(text.strip())
        if total == 0:
            return False
        # If less than 30% Chinese and less than 50% ASCII, likely garbled
        return (chinese / total < 0.3) and (ascii_chars / total < 0.5)


# Module-level singleton
_detector: Optional[AnomalyDetector] = None


def get_anomaly_detector() -> AnomalyDetector:
    """Get or create the global AnomalyDetector instance"""
    global _detector
    if _detector is None:
        _detector = AnomalyDetector()
    return _detector
