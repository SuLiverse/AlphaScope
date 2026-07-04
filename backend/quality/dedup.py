"""数据去重模块

基于 fingerprint 的新闻/研报/公告去重:
- 同标题 + 同日期 + 同股票代码 → 合并
- 相似标题 + 同源链接 → 合并
- 公告 PDF hash 相同 → 合并
"""

from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)


def _normalize(text: str) -> str:
    """标准化文本: 去除空白、标点、统一大小写"""
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。、；：" "''【】《》（）\\(\\)\\[\\]{}!！?？,.;:\"'\\-]", "", text)
    return text.lower()


class Deduplicator:
    """数据去重器

    使用内存集合跟踪已处理的 fingerprint,
    支持新闻、研报、公告三种数据类型。
    """

    def __init__(self) -> None:
        self._seen_news: set[str] = set()
        self._seen_reports: set[str] = set()
        self._seen_announcements: set[str] = set()
        self._stats = {"news_dup": 0, "report_dup": 0, "announcement_dup": 0}

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def news_fingerprint(self, item: dict) -> str:
        """生成新闻条目的 fingerprint"""
        title = _normalize(item.get("title", ""))
        date = str(item.get("datetime", ""))[:10]
        source = item.get("source", "")
        raw = f"{title}_{date}_{source}"
        return hashlib.md5(raw.encode()).hexdigest()

    def is_news_dup(self, item: dict) -> bool:
        """检查新闻是否重复"""
        fp = self.news_fingerprint(item)
        if fp in self._seen_news:
            self._stats["news_dup"] += 1
            return True
        self._seen_news.add(fp)
        return False

    def report_fingerprint(self, item: dict) -> str:
        """生成研报条目的 fingerprint"""
        title = _normalize(item.get("title", ""))
        institution = _normalize(item.get("institution", ""))
        date = str(item.get("datetime", ""))[:10]
        # 优先使用 PDF hash
        pdf_hash = item.get("pdf_hash", "")
        if pdf_hash:
            return pdf_hash
        raw = f"{title}_{institution}_{date}"
        return hashlib.md5(raw.encode()).hexdigest()

    def is_report_dup(self, item: dict) -> bool:
        """检查研报是否重复"""
        fp = self.report_fingerprint(item)
        if fp in self._seen_reports:
            self._stats["report_dup"] += 1
            return True
        self._seen_reports.add(fp)
        return False

    def announcement_fingerprint(self, item: dict) -> str:
        """生成公告条目的 fingerprint"""
        # 优先使用 PDF hash
        pdf_hash = item.get("pdf_hash", "")
        if pdf_hash:
            return pdf_hash
        title = _normalize(item.get("title", ""))
        symbol = item.get("symbol", "")
        date = str(item.get("datetime", ""))[:10]
        raw = f"{title}_{symbol}_{date}"
        return hashlib.md5(raw.encode()).hexdigest()

    def is_announcement_dup(self, item: dict) -> bool:
        """检查公告是否重复"""
        fp = self.announcement_fingerprint(item)
        if fp in self._seen_announcements:
            self._stats["announcement_dup"] += 1
            return True
        self._seen_announcements.add(fp)
        return False

    def dedup_news(self, items: list[dict]) -> list[dict]:
        """批量新闻去重"""
        return [item for item in items if not self.is_news_dup(item)]

    def dedup_reports(self, items: list[dict]) -> list[dict]:
        """批量研报去重"""
        return [item for item in items if not self.is_report_dup(item)]

    def dedup_announcements(self, items: list[dict]) -> list[dict]:
        """批量公告去重"""
        return [item for item in items if not self.is_announcement_dup(item)]

    def reset(self) -> None:
        """重置去重状态"""
        self._seen_news.clear()
        self._seen_reports.clear()
        self._seen_announcements.clear()
        self._stats = {"news_dup": 0, "report_dup": 0, "announcement_dup": 0}
