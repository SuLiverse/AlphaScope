"""HybridRetriever 排序与 BM25 腿的表征测试 — 不碰真实 chroma/网络。

锁住两条修复路径:
1. _merge_results 的 combined_score 必须与相似度同向(距离越小分越高);
2. _bm25_search 必须走 Database.transaction 锁定的连接, 而非不存在的 get_connection。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.rag.hybrid_retriever import HybridRetriever, RetrievalResult


def test_merge_results_ranking_higher_similarity_first():
    """vector_score 是距离: 0.1(更相似)必须排在 0.9(更不相似)前面。"""
    retriever = HybridRetriever()
    near = RetrievalResult(text="near doc", vector_score=0.1)
    far = RetrievalResult(text="far doc", vector_score=0.9)

    retriever._merge_results([near, far], [])

    assert near.combined_score > far.combined_score


def test_vector_search_combined_score_is_similarity():
    """_vector_search 的 combined_score = 1.0 - distance, 与相似度同向。"""
    fake_result = {"text": "doc", "metadata": {}, "distance": 0.2}
    with patch("backend.rag.retriever.Retriever.search", return_value=[fake_result]):
        retriever = HybridRetriever()
        results = retriever._vector_search("query", "", 5)

    assert len(results) == 1
    assert results[0].vector_score == 0.2
    assert results[0].combined_score == pytest.approx(0.8)


def test_bm25_search_uses_locked_connection():
    """_bm25_search 通过 transaction() 取连接, 不再因 get_connection 抛 AttributeError。"""
    fake_conn = MagicMock()
    fake_conn.execute.return_value.fetchall.return_value = [(1, "苹果 业绩 超预期", "新浪财经", "news", "2026-08-01")]
    fake_transaction = MagicMock()
    fake_transaction.return_value.__enter__.return_value = fake_conn

    with patch("backend.storage.db.Database.transaction", fake_transaction):
        retriever = HybridRetriever()
        results = retriever._bm25_search("苹果 业绩 超预期", "", 5)

    assert len(results) == 1
    assert results[0].bm25_score > 0
    assert results[0].text == "苹果 业绩 超预期"
