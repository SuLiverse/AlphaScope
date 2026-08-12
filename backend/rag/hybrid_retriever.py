"""
Hybrid Retriever: 混合检索（BM25 + 向量语义 + 元数据过滤 + 时间衰减）。

架构文档要求的检索策略：
- 关键词 BM25
- 向量语义检索
- 元数据过滤
- 时间衰减排序
- 来源可信度排序
- reranker 重排
"""

import math
import time
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """检索结果"""

    text: str
    source: str = ""
    doc_type: str = ""  # news, report, announcement
    published_at: float = 0
    trust_score: float = 0.5
    vector_score: float = 0.0
    bm25_score: float = 0.0
    combined_score: float = 0.0
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class HybridRetriever:
    """混合检索器"""

    def __init__(
        self,
        vector_weight: float = 0.6,
        bm25_weight: float = 0.3,
        recency_weight: float = 0.1,
    ):
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.recency_weight = recency_weight
        self._half_life_days = 30  # 时间衰减半衰期

    def search(
        self,
        query: str,
        symbol: str = "",
        n_results: int = 10,
        doc_types: Optional[List[str]] = None,
        time_decay: bool = True,
    ) -> List[RetrievalResult]:
        """混合检索"""
        # 获取向量检索结果
        vector_results = self._vector_search(query, symbol, n_results * 2)
        # 获取 BM25 结果
        bm25_results = self._bm25_search(query, symbol, n_results * 2)

        # 合并结果
        merged = self._merge_results(vector_results, bm25_results)

        # 过滤
        if doc_types:
            merged = [r for r in merged if r.doc_type in doc_types]

        # 时间衰减
        if time_decay:
            for r in merged:
                r.combined_score *= self._time_decay_factor(r.published_at)

        # 来源可信度加权
        for r in merged:
            r.combined_score *= 0.5 + r.trust_score

        # 排序
        merged.sort(key=lambda x: x.combined_score, reverse=True)

        return merged[:n_results]

    def _vector_search(self, query: str, symbol: str, n: int) -> List[RetrievalResult]:
        """向量语义检索"""
        try:
            from backend.rag.retriever import Retriever

            retriever = Retriever()
            results = retriever.search(query, symbol=symbol, n_results=n)

            return [
                RetrievalResult(
                    text=r.get("text", ""),
                    source=r.get("metadata", {}).get("source", ""),
                    doc_type=r.get("metadata", {}).get("doc_type", "other"),
                    published_at=self._parse_timestamp(r.get("metadata", {}).get("published_at", "")),
                    trust_score=r.get("metadata", {}).get("trust_score", 0.5),
                    vector_score=r.get("distance", 0),
                    combined_score=1.0 - min(r.get("distance", 1.0), 1.0),
                    metadata=r.get("metadata", {}),
                )
                for r in results
            ]
        except Exception as e:
            logger.debug(f"向量检索失败: {e}")
            return []

    def _bm25_search(self, query: str, symbol: str, n: int) -> List[RetrievalResult]:
        """BM25 关键词检索"""
        try:
            from backend.evidence_store import _ensure_schema
            from backend.storage.db import Database

            _ensure_schema()
            keywords = [part for part in query.split()[:5] if part]
            if not keywords:
                return []
            db = Database()
            with db.transaction() as conn:
                # 简单的 LIKE 搜索作为 BM25 近似
                conditions = " OR ".join("(claim LIKE ? OR content_summary LIKE ? OR title LIKE ?)" for _ in keywords)
                params = [value for kw in keywords for value in (f"%{kw}%", f"%{kw}%", f"%{kw}%")]

                if symbol:
                    symbol_pattern = f'%"{symbol}"%'
                    conditions = f"({conditions}) AND (symbols LIKE ? OR symbols LIKE ? OR symbols IN ('', '[]'))"
                    params.extend((symbol_pattern, f"%{symbol}%"))

                # 搜索 evidence_items
                rows = conn.execute(
                    f"""SELECT id,
                               COALESCE(NULLIF(claim, ''), NULLIF(content_summary, ''), title),
                               source, evidence_type, data_date
                        FROM evidence_items
                        WHERE {conditions}
                        LIMIT ?""",
                    params + [n],
                ).fetchall()

                results = []
                for row in rows:
                    # 简单的 BM25 近似分数
                    text = row[1] or ""
                    match_count = sum(1 for kw in keywords if kw.casefold() in text.casefold())
                    bm25_score = match_count / max(len(keywords), 1)

                    results.append(
                        RetrievalResult(
                            text=row[1] or "",
                            source=row[2] or "",
                            doc_type=row[3] or "other",
                            published_at=self._parse_timestamp(row[4] or ""),
                            trust_score=0.7,  # evidence_items 默认较高信任
                            bm25_score=bm25_score,
                            combined_score=bm25_score,
                            metadata={"id": row[0]},
                        )
                    )

            return results
        except Exception as e:
            logger.debug(f"BM25 检索失败: {e}")
            return []

    def _merge_results(
        self, vector_results: List[RetrievalResult], bm25_results: List[RetrievalResult]
    ) -> List[RetrievalResult]:
        """合并去重向量和 BM25 结果"""
        seen_texts = set()
        merged = []

        for r in vector_results:
            key = r.text[:100]
            if key not in seen_texts:
                seen_texts.add(key)
                r.combined_score = (1.0 - min(r.vector_score, 1.0)) * self.vector_weight
                merged.append(r)

        for r in bm25_results:
            key = r.text[:100]
            if key in seen_texts:
                # 已有结果，累加 BM25 分数
                for existing in merged:
                    if existing.text[:100] == key:
                        existing.bm25_score = r.bm25_score
                        existing.combined_score += r.bm25_score * self.bm25_weight
                        break
            else:
                seen_texts.add(key)
                r.combined_score = r.bm25_score * self.bm25_weight
                merged.append(r)

        return merged

    def _time_decay_factor(self, timestamp: float) -> float:
        """时间衰减因子（指数衰减）"""
        if timestamp <= 0:
            return 0.5  # 无时间信息，给中等权重

        days_ago = (time.time() - timestamp) / 86400
        if days_ago < 0:
            days_ago = 0

        # 指数衰减: factor = 0.5 ^ (days / half_life)
        return math.pow(0.5, days_ago / self._half_life_days)

    def _parse_timestamp(self, date_str: str) -> float:
        """解析日期字符串为时间戳"""
        if not date_str:
            return 0
        try:
            from datetime import datetime

            for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"]:
                try:
                    return datetime.strptime(date_str[:19], fmt).timestamp()
                except ValueError:
                    continue
        except Exception:
            pass
        return 0


# 单例
_retriever: Optional[HybridRetriever] = None


def get_hybrid_retriever() -> HybridRetriever:
    """获取全局混合检索器"""
    global _retriever
    if _retriever is None:
        _retriever = HybridRetriever()
    return _retriever
