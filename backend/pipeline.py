"""数据管道 - 整合 Provider → 去重 → 可信度 → 存储 → RAG

v0.12 核心模块, 将所有数据层串联为完整管道。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Optional

from backend.providers.registry import get_registry
from backend.quality.dedup import Deduplicator
from backend.quality.source_rank import SourceRanker
from backend.storage.db import Database
from backend.rag.retriever import Retriever
from backend.utils.tracer import traced
from backend.utils.datetime_util import normalize_dt_str

logger = logging.getLogger(__name__)


class ResourceUnavailableError(Exception):
    """Raised when a required resource (e.g., RAG Retriever) is not available"""

    pass


class DataPipeline:
    """数据采集与存储管道

    流程: Provider → Dedup → SourceRank → SQLite → ChromaDB
    Thread-safe singleton with double-checked locking.
    """

    _instance: Optional["DataPipeline"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "DataPipeline":
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                inst._retriever = None
                inst._retriever_failed = False
                inst._retriever_error = ""
                cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._registry = get_registry()
        self._dedup = Deduplicator()
        self._ranker = SourceRanker()
        self._db = Database()

    @property
    def retriever(self) -> Retriever:
        """懒加载 Retriever (ChromaDB 初始化较重)

        Raises ResourceUnavailableError if initialization failed,
        so callers can catch and degrade gracefully.
        """
        if self._retriever is None and not self._retriever_failed:
            try:
                self._retriever = Retriever()
            except Exception as e:
                self._retriever_failed = True
                self._retriever_error = str(e)
                logger.error(
                    "Retriever 初始化失败, 后续 RAG 调用将抛 ResourceUnavailableError: %s",
                    e,
                )
        if self._retriever is None:
            raise ResourceUnavailableError(f"RAG 不可用: {self._retriever_error}")
        return self._retriever

    @property
    def registry(self):
        return self._registry

    @property
    def db(self) -> Database:
        return self._db

    @property
    def dedup(self) -> Deduplicator:
        return self._dedup

    @property
    def ranker(self) -> SourceRanker:
        return self._ranker

    # ---- 新闻管道 ----

    def ingest_news(
        self,
        market: str = "CN",
        symbol: str = "",
        limit: int = 30,
    ) -> list[dict]:
        """采集 → 去重 → 排序 → 事件抽取 → 存储 → 索引"""
        start = time.time()
        try:
            # 1. 从 Provider 获取
            with traced("ingest_news.fetch", "pipeline", market=market, symbol=symbol):
                items = self._registry.get(
                    data_type="news",
                    market=market,
                    symbol=symbol,
                    limit=limit,
                )
            if not items:
                self._log_fetch("news", "empty", "success", 0, 0)
                return []

            # 2. 去重
            items = self._dedup.dedup_news(items)

            # 3. 可信度排序
            items = self._ranker.rank_items(items, source_key="source")

            # 4. 事件抽取 (v0.12)
            items = self._enrich_news_with_events(items)

            # 4.5 数据质量观测: 持久化前检测标题过短/乱码/重复时间戳。失败安全不阻断。
            news_anomaly_count = self._detect_news_anomalies(items)

            # 5. 持久化
            for item in items:
                self._db.insert_news(self._to_news_row(item))

            # 6. RAG 索引
            self._index_news(items)

            latency = (time.time() - start) * 1000
            self._log_fetch("news", market, "success", latency, len(items))
            logger.info(
                "[Pipeline] 新闻采集完成: %d 条 (%.0fms)%s",
                len(items),
                latency,
                f", 检测到 {news_anomaly_count} 条异常" if news_anomaly_count else "",
            )
            return items

        except Exception as e:
            latency = (time.time() - start) * 1000
            self._log_fetch("news", market, "error", latency, 0, str(e))
            logger.error("[Pipeline] 新闻采集失败: %s", e)
            return []

    # ---- 研报管道 ----

    def ingest_reports(
        self,
        symbol: str,
        market: str = "CN",
        limit: int = 20,
    ) -> list[dict]:
        """采集 → 去重 → 排序 → 存储 → 索引"""
        start = time.time()
        try:
            items = self._registry.get(
                data_type="reports",
                market=market,
                symbol=symbol,
                limit=limit,
            )
            if not items:
                self._log_fetch("reports", symbol, "success", 0, 0)
                return []

            items = self._dedup.dedup_reports(items)
            items = self._ranker.rank_items(items, source_key="source")

            for item in items:
                self._db.insert_report(self._to_report_row(item))

            self._index_reports(items)

            latency = (time.time() - start) * 1000
            self._log_fetch("reports", symbol, "success", latency, len(items))
            logger.info("[Pipeline] 研报采集完成: %d 条 (%.0fms)", len(items), latency)
            return items

        except Exception as e:
            latency = (time.time() - start) * 1000
            self._log_fetch("reports", symbol, "error", latency, 0, str(e))
            logger.error("[Pipeline] 研报采集失败: %s", e)
            return []

    # ---- 公告管道 ----

    def ingest_announcements(
        self,
        symbol: str,
        market: str = "CN",
        limit: int = 30,
        start_date: str = "",
        end_date: str = "",
    ) -> list[dict]:
        """采集 → 去重 → 排序 → 存储 → 索引"""
        start = time.time()
        try:
            items = self._registry.get(
                data_type="announcements",
                market=market,
                symbol=symbol,
                limit=limit,
                start_date=start_date,
                end_date=end_date,
            )
            if not items:
                self._log_fetch("announcements", symbol, "success", 0, 0)
                return []

            items = self._dedup.dedup_announcements(items)
            items = self._ranker.rank_items(items, source_key="source")

            # 事件分类 (v0.12)
            items = self._enrich_announcements_with_events(items)

            for item in items:
                self._db.insert_announcement(self._to_announcement_row(item))

            self._index_announcements(items)

            latency = (time.time() - start) * 1000
            self._log_fetch("announcements", symbol, "success", latency, len(items))
            logger.info("[Pipeline] 公告采集完成: %d 条 (%.0fms)", len(items), latency)
            return items

        except Exception as e:
            latency = (time.time() - start) * 1000
            self._log_fetch("announcements", symbol, "error", latency, 0, str(e))
            logger.error("[Pipeline] 公告采集失败: %s", e)
            return []

    # ---- 行情管道 ----

    def ingest_prices(
        self,
        symbol: str,
        market: str = "CN",
        **kwargs,
    ) -> list[dict]:
        """采集行情数据并持久化"""
        start = time.time()
        try:
            items = self._registry.get(
                data_type="prices",
                market=market,
                symbol=symbol,
                **kwargs,
            )
            if not items:
                self._log_fetch("prices", symbol, "success", 0, 0)
                return []

            # 数据质量观测: 落库前检测每条 bar 的异常(零负价/高低倒挂等)。
            # 失败安全 + 不阻断落库(尊重既有"数据进来"语义), 仅 log 标记。
            anomaly_count = self._detect_price_anomalies(items, symbol)

            with self._db.transaction() as conn:
                for item in items:
                    conn.execute(
                        """INSERT OR REPLACE INTO price_bars
                        (symbol, date, market, frequency, open, high, low, close,
                         volume, amount, turnover, amplitude, change_pct, adjust, source)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item.get("symbol", symbol),
                            item.get("date", ""),
                            item.get("market", market),
                            item.get("frequency", "1d"),
                            item.get("open", 0),
                            item.get("high", 0),
                            item.get("low", 0),
                            item.get("close", 0),
                            item.get("volume", 0),
                            item.get("amount", 0),
                            item.get("turnover", 0),
                            item.get("amplitude", 0),
                            item.get("change_pct", 0),
                            item.get("adjust", ""),
                            item.get("source", "akshare"),
                        ),
                    )
                conn.commit()

            # _log_fetch → insert_fetch_log 自带 _db_lock; 必须在 transaction 锁外调用, 否则死锁。
            latency = (time.time() - start) * 1000
            self._log_fetch("prices", symbol, "success", latency, len(items))
            logger.info(
                "[Pipeline] 行情采集完成: %d 条 (%.0fms)%s",
                len(items),
                latency,
                f", 检测到 {anomaly_count} 条异常 bar" if anomaly_count else "",
            )
            return items

        except Exception as e:
            latency = (time.time() - start) * 1000
            self._log_fetch("prices", symbol, "error", latency, 0, str(e))
            logger.error("[Pipeline] 行情采集失败: %s", e)
            return []

    def _detect_price_anomalies(self, items: list[dict], symbol: str) -> int:
        """落库前对 bars 做数据质量观测(零负价/高低倒挂等不依赖历史的异常)。

        失败安全: anomaly_detector 不可用或抛错时返回 0, 绝不阻断采集落库。
        仅 log 标记异常, 不修改/丢弃数据(尊重既有"数据进来"语义)。
        返回检测到异常的 bar 数量。
        """
        try:
            from backend.quality.anomaly_detector import get_anomaly_detector

            detector = get_anomaly_detector()
            count = 0
            for item in items:
                anomalies = detector.check_price(item, history=None, symbol=symbol)
                if anomalies:
                    count += 1
                    logger.warning(
                        "[Pipeline] 行情异常 %s %s: %s",
                        symbol,
                        item.get("date", ""),
                        "; ".join(anomalies),
                    )
            return count
        except Exception as e:  # noqa: BLE001
            logger.debug("[Pipeline] 异常检测跳过(检测器不可用): %s", e)
            return 0

    def _detect_news_anomalies(self, items: list[dict]) -> int:
        """持久化前对新闻做质量观测(标题过短/乱码/重复时间戳)。

        失败安全不阻断; check_news 用 datetime 字段, provider item 可能用 published_at,
        这里归一化传入。返回检测到异常的条数。
        """
        try:
            from backend.quality.anomaly_detector import get_anomaly_detector

            detector = get_anomaly_detector()
            # 归一化字段名: check_news 读 datetime, 兼容 published_at
            normalized = []
            for item in items:
                norm = dict(item)
                if "datetime" not in norm and item.get("published_at"):
                    norm["datetime"] = item["published_at"]
                normalized.append(norm)
            count = 0
            for news in normalized:
                anomalies = detector.check_news(news, all_news=normalized)
                if anomalies:
                    count += 1
                    logger.warning(
                        "[Pipeline] 新闻异常: %s",
                        "; ".join(anomalies),
                    )
            return count
        except Exception as e:  # noqa: BLE001
            logger.debug("[Pipeline] 新闻异常检测跳过: %s", e)
            return 0

    # ---- 基本面管道 ----

    def ingest_fundamentals(
        self,
        symbol: str,
        market: str = "CN",
    ) -> dict:
        """采集基本面数据"""
        start = time.time()
        try:
            result = self._registry.get(
                data_type="fundamentals",
                market=market,
                symbol=symbol,
            )
            latency = (time.time() - start) * 1000
            status = "success" if result else "empty"
            self._log_fetch("fundamentals", symbol, status, latency, 1 if result else 0)
            return result if isinstance(result, dict) else {}
        except Exception as e:
            latency = (time.time() - start) * 1000
            self._log_fetch("fundamentals", symbol, "error", latency, 0, str(e))
            return {}

    # ---- 资金流管道 ----

    def ingest_fund_flow(
        self,
        symbol: str,
        market: str = "CN",
    ) -> list[dict]:
        """采集资金流数据"""
        start = time.time()
        try:
            items = self._registry.get(
                data_type="fund_flow",
                market=market,
                symbol=symbol,
            )
            latency = (time.time() - start) * 1000
            self._log_fetch(
                "fund_flow", symbol, "success", latency, len(items) if items else 0
            )
            return items if items else []
        except Exception as e:
            latency = (time.time() - start) * 1000
            self._log_fetch("fund_flow", symbol, "error", latency, 0, str(e))
            return []

    # ---- RAG 检索 ----

    def search_evidence(
        self,
        query: str,
        symbol: str = "",
        n_results: int = 10,
    ) -> list[dict]:
        """跨所有 collection 检索相关证据"""
        retriever = self.retriever
        if not retriever:
            return []

        all_results = []
        collections = [
            "news_chunks",
            "report_chunks",
            "announcement_chunks",
            "user_documents",
        ]

        for col in collections:
            try:
                results = retriever.search(
                    collection=col,
                    query=query,
                    n_results=n_results,
                    symbol=symbol if symbol else None,
                )
                all_results.extend(results)
            except Exception as e:
                logger.debug("RAG 检索 %s 失败: %s", col, e)

        # 按距离排序, 取 top N
        all_results.sort(key=lambda x: x.get("distance", 1.0))
        return all_results[:n_results]

    # ---- 管道状态 ----

    def status(self) -> dict:
        """获取管道整体状态"""
        providers = self._registry.list_providers()
        with self._db.transaction() as conn:
            db_path = conn.execute("PRAGMA database_list").fetchone()
        rag_stats = {}
        if self._retriever:
            try:
                rag_stats = self._retriever.store.get_collection_stats()
            except Exception:
                pass

        return {
            "providers": len(providers),
            "provider_list": [p["name"] for p in providers],
            "db_path": str(db_path[2]) if db_path else "unknown",
            "dedup_stats": self._dedup.stats,
            "rag_collections": rag_stats,
            "timestamp": datetime.now().isoformat(),
        }

    # ---- 内部方法 ----

    def _log_fetch(
        self,
        source: str,
        endpoint: str,
        status: str,
        latency_ms: float,
        items_count: int,
        error: str = "",
    ) -> None:
        """记录抓取日志"""
        try:
            self._db.insert_fetch_log(
                {
                    "source": source,
                    "endpoint": endpoint,
                    "status": status,
                    "latency_ms": round(latency_ms, 1),
                    "items_count": items_count,
                    "error_message": error,
                    "started_at": datetime.now().isoformat(),
                    "finished_at": datetime.now().isoformat(),
                }
            )
        except Exception as e:
            logger.debug("记录抓取日志失败: %s", e)

    def _index_news(self, items: list[dict]) -> None:
        """索引新闻到 RAG"""
        retriever = self.retriever
        if not retriever:
            return
        try:
            count = retriever.index_news(items)
            if count:
                logger.info("[Pipeline] 新闻 RAG 索引: %d chunks", count)
        except Exception as e:
            logger.debug("新闻 RAG 索引失败: %s", e)

    def _index_reports(self, items: list[dict]) -> None:
        """索引研报到 RAG"""
        retriever = self.retriever
        if not retriever:
            return
        try:
            count = retriever.index_reports(items)
            if count:
                logger.info("[Pipeline] 研报 RAG 索引: %d chunks", count)
        except Exception as e:
            logger.debug("研报 RAG 索引失败: %s", e)

    def _index_announcements(self, items: list[dict]) -> None:
        """索引公告到 RAG"""
        retriever = self.retriever
        if not retriever:
            return
        try:
            count = retriever.index_announcements(items)
            if count:
                logger.info("[Pipeline] 公告 RAG 索引: %d chunks", count)
        except Exception as e:
            logger.debug("公告 RAG 索引失败: %s", e)

    @staticmethod
    def _enrich_news_with_events(items: list[dict]) -> list[dict]:
        """用事件抽取器为新闻条目补充 event_type 和 sentiment"""
        try:
            from backend.events.extractor import EventExtractor

            extractor = EventExtractor()
            for item in items:
                if item.get("event_type"):
                    continue  # 已有事件类型, 跳过
                events = extractor.extract_from_news_item(item)
                if events:
                    evt = events[0]
                    item["event_type"] = evt.event_type
                    item["sentiment"] = evt.sentiment
                    item["importance"] = max(
                        item.get("importance", 0.5), evt.importance
                    )
        except Exception as e:
            logger.debug("新闻事件抽取跳过: %s", e)
        return items

    @staticmethod
    def _enrich_announcements_with_events(items: list[dict]) -> list[dict]:
        """用事件抽取器为公告条目补充 category"""
        try:
            from backend.events.extractor import EventExtractor

            extractor = EventExtractor()
            for item in items:
                if item.get("category"):
                    continue  # 已有分类, 跳过
                events = extractor.extract_from_announcement(item)
                if events:
                    evt = events[0]
                    # 映射 event_type → category
                    type_to_cat = {
                        "earnings": "earnings",
                        "dividend": "dividend",
                        "mna": "mna",
                        "financing": "financing",
                        "litigation": "litigation",
                    }
                    item["category"] = type_to_cat.get(evt.event_type, "other")
                    item["importance"] = max(
                        item.get("importance", 0.5), evt.importance
                    )
        except Exception as e:
            logger.debug("公告事件抽取跳过: %s", e)
        return items

    @staticmethod
    def _to_news_row(item: dict) -> dict:
        """将 Provider 返回的 dict 转为 DB 新闻行格式 (v0.13: datetime 归一化)"""
        return {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "summary": item.get("summary", ""),
            "content": item.get("content", ""),
            "source": item.get("source", ""),
            "upstream": item.get("upstream", ""),
            "source_url": item.get("source_url", item.get("url", "")),
            "published_at": normalize_dt_str(
                item.get("datetime", item.get("published_at", ""))
            ),
            "fetched_at": normalize_dt_str(item.get("fetched_at", ""))
            or datetime.now().isoformat(),
            "symbols": item.get("symbols", []),
            "industries": item.get("industries", []),
            "event_type": item.get("event_type", ""),
            "sentiment": item.get("sentiment", 0),
            "importance": item.get("importance", 0.5),
            "confidence": item.get("confidence", 0.6),
            "license_level": item.get("license_level", "research_only"),
        }

    @staticmethod
    def _to_report_row(item: dict) -> dict:
        """将 Provider 返回的 dict 转为 DB 研报行格式 (v0.13: datetime 归一化)"""
        return {
            "id": item.get("id", ""),
            "title": item.get("title", ""),
            "report_type": item.get("report_type", "company"),
            "institution": item.get("institution", ""),
            "authors": item.get("authors", []),
            "symbols": item.get("symbols", []),
            "industry": item.get("industry", ""),
            "rating": item.get("rating", ""),
            "target_price": item.get("target_price"),
            "summary": item.get("summary", ""),
            "pdf_url": item.get("pdf_url", item.get("url", "")),
            "published_at": normalize_dt_str(
                item.get("datetime", item.get("published_at", ""))
            ),
            "fetched_at": normalize_dt_str(item.get("fetched_at", ""))
            or datetime.now().isoformat(),
            "source": item.get("source", ""),
            "source_url": item.get("source_url", item.get("url", "")),
            "pdf_hash": item.get("pdf_hash", ""),
            "confidence": item.get("confidence", 0.8),
            "license_level": item.get("license_level", "restricted"),
        }

    @staticmethod
    def _to_announcement_row(item: dict) -> dict:
        """将 Provider 返回的 dict 转为 DB 公告行格式 (v0.13: datetime 归一化)"""
        return {
            "id": item.get("id", ""),
            "symbol": item.get("symbol", ""),
            "company_name": item.get("company_name", ""),
            "title": item.get("title", ""),
            "category": item.get("category", ""),
            "published_at": normalize_dt_str(
                item.get("datetime", item.get("published_at", ""))
            ),
            "fetched_at": normalize_dt_str(item.get("fetched_at", ""))
            or datetime.now().isoformat(),
            "source": item.get("source", ""),
            "source_url": item.get("source_url", item.get("url", "")),
            "pdf_url": item.get("pdf_url", item.get("url", "")),
            "pdf_hash": item.get("pdf_hash", ""),
            "parsed_text_path": item.get("parsed_text_path", ""),
            "importance": item.get("importance", 0.5),
            "confidence": item.get("confidence", 0.9),
        }


# ---- 便捷函数 ----

_pipeline: Optional[DataPipeline] = None


def get_pipeline() -> DataPipeline:
    """获取全局 DataPipeline 单例"""
    global _pipeline
    if _pipeline is None:
        _pipeline = DataPipeline()
    return _pipeline


def ingest_news(market: str = "CN", symbol: str = "", limit: int = 30) -> list[dict]:
    return get_pipeline().ingest_news(market, symbol, limit)


def ingest_reports(symbol: str, market: str = "CN", limit: int = 20) -> list[dict]:
    return get_pipeline().ingest_reports(symbol, market, limit)


def ingest_announcements(
    symbol: str,
    market: str = "CN",
    limit: int = 30,
    start_date: str = "",
    end_date: str = "",
) -> list[dict]:
    return get_pipeline().ingest_announcements(
        symbol, market, limit, start_date, end_date
    )


def search_evidence(query: str, symbol: str = "", n_results: int = 10) -> list[dict]:
    return get_pipeline().search_evidence(query, symbol, n_results)
