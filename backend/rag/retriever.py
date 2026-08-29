"""RAG 检索器 - 统一检索接口"""

from __future__ import annotations

import logging
from typing import Optional

from .chunker import TextChunker
from .vector_store import VectorStore

logger = logging.getLogger(__name__)

# 无 collection 指定时遍历的默认集合 (与 pipeline.search_evidence 一致)
DEFAULT_COLLECTIONS = ["news_chunks", "report_chunks", "announcement_chunks", "user_documents"]


class Retriever:
    """统一 RAG 检索器

    整合分块和向量检索, 提供端到端的文档索引和查询。
    """

    def __init__(self) -> None:
        self.chunker = TextChunker()
        self.store = VectorStore()

    def index_document(
        self,
        collection: str,
        text: str,
        metadata: dict,
    ) -> int:
        """将文档分块并索引到向量库

        Returns:
            索引的 chunk 数量
        """
        chunks = self.chunker.chunk_text(text, metadata)
        if not chunks:
            return 0

        self.store.add_documents(
            collection_name=collection,
            documents=[c["text"] for c in chunks],
            metadatas=[{k: v for k, v in c.items() if k != "text"} for c in chunks],
            ids=[c["chunk_id"] for c in chunks],
        )
        return len(chunks)

    def search(
        self,
        query: str,
        n_results: int = 5,
        symbol: Optional[str] = None,
        collection: Optional[str] = None,
    ) -> list[dict]:
        """检索相似文档

        Args:
            query: 查询文本
            n_results: 返回条数
            symbol: 可选的 symbol 过滤 (匹配 metadata 中的 "symbol" 键)
            collection: 指定单一集合; 为 None 时遍历 DEFAULT_COLLECTIONS 并按 distance 合并
        """
        where = None
        if symbol:
            where = {"symbol": symbol}

        if collection is not None:
            return self.store.query(collection, query, n_results, where)

        all_results: list[dict] = []
        for col in DEFAULT_COLLECTIONS:
            try:
                all_results.extend(self.store.query(col, query, n_results, where))
            except Exception as e:
                logger.debug("RAG 检索 %s 失败: %s", col, e)

        # 按 distance 升序排序, 取 top N
        all_results.sort(key=lambda x: x.get("distance", 1.0))
        return all_results[:n_results]

    def index_news(self, items: list[dict]) -> int:
        """批量索引新闻"""
        count = 0
        for item in items:
            text = f"{item.get('title', '')}\n{item.get('summary', '')}\n{item.get('content', '')}"
            if not text.strip():
                continue
            metadata = {
                "source": item.get("source", ""),
                "doc_type": "news",
                "published_at": str(item.get("datetime", "")),
                "symbols": ",".join(item.get("symbols", [])),
            }
            count += self.index_document("news_chunks", text, metadata)
        return count

    def index_reports(self, items: list[dict]) -> int:
        """批量索引研报"""
        count = 0
        for item in items:
            text = f"{item.get('title', '')}\n{item.get('summary', '')}"
            if not text.strip():
                continue
            metadata = {
                "source": item.get("source", ""),
                "doc_type": "report",
                "institution": item.get("institution", ""),
                "symbols": ",".join(item.get("symbols", [])),
                "published_at": str(item.get("datetime", "")),
            }
            count += self.index_document("report_chunks", text, metadata)
        return count

    def index_announcements(self, items: list[dict]) -> int:
        """批量索引公告"""
        count = 0
        for item in items:
            text = f"{item.get('title', '')}\n{item.get('content', '')}"
            if not text.strip():
                continue
            metadata = {
                "source": item.get("source", ""),
                "doc_type": "announcement",
                "symbol": item.get("symbol", ""),
                "published_at": str(item.get("datetime", "")),
            }
            count += self.index_document("announcement_chunks", text, metadata)
        return count
