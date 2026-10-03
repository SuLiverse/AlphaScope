"""RAG 检索链路回归测试 — 不碰真实 chroma/网络, 用 fake VectorStore 替身。

锁住三条修复路径 (不 mock 被测方法本身):
1. tool_router._tool_evidence_search 以新签名调用 Retriever.search,
   不再漏传 collection 首参导致必然 TypeError;
2. Retriever.search 不指定 collection 时遍历 DEFAULT_COLLECTIONS,
   合并结果按 distance 升序截断; 指定 collection 时单集合行为不变;
3. index_news/index_reports 写入 metadata 同时含单数 "symbol" 与复数 "symbols"。
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import patch

from backend.rag.retriever import DEFAULT_COLLECTIONS, Retriever
from backend.runtime.tool_router import ToolRouter


class _FakeVectorStore:
    """替身 VectorStore: 记录查询调用, 返回按集合预置的结果。"""

    def __init__(self, results_by_collection: Optional[dict] = None):
        self.queries: list[tuple] = []  # (collection, query, n_results, where)
        self.added: list[dict] = []  # add_documents 调用记录
        self._results = results_by_collection or {}

    def query(self, collection_name, query_text, n_results=5, where=None):
        self.queries.append((collection_name, query_text, n_results, where))
        return list(self._results.get(collection_name, []))

    def add_documents(self, collection_name, documents, metadatas, ids):
        self.added.append(
            {
                "collection": collection_name,
                "documents": documents,
                "metadatas": metadatas,
                "ids": ids,
            }
        )
        return len(documents)


def _make_retriever(fake_store) -> Retriever:
    """构造挂在 fake store 上的真实 Retriever (只替换 VectorStore 构造)。"""
    with patch("backend.rag.retriever.VectorStore", return_value=fake_store):
        return Retriever()


# ============== (a) _tool_evidence_search 不再 TypeError ==============


def test_evidence_search_no_type_error_with_symbol():
    """带 symbol 的证据检索: 不抛 TypeError, 结果无 error 键, 过滤透传。"""
    router = ToolRouter()
    fake = _FakeVectorStore(
        {"news_chunks": [{"text": "n", "metadata": {}, "distance": 0.2, "id": "n1"}]}
    )
    with patch("backend.rag.retriever.VectorStore", return_value=fake):
        result = router._tool_evidence_search(query="苹果 业绩", symbol="AAPL")

    assert "error" not in result
    assert result["query"] == "苹果 业绩"
    assert [r["id"] for r in result["results"]] == ["n1"]
    # 查询必须落在 4 个默认集合上 (而不是把 query 文本当 collection 名)
    assert [q[0] for q in fake.queries] == DEFAULT_COLLECTIONS
    # symbol 过滤透传到 where
    assert all(q[3] == {"symbol": "AAPL"} for q in fake.queries)


def test_evidence_search_empty_symbol_means_no_filter():
    """空 symbol 归一化为 None, 不带 where 过滤。"""
    router = ToolRouter()
    fake = _FakeVectorStore()
    with patch("backend.rag.retriever.VectorStore", return_value=fake):
        result = router._tool_evidence_search(query="大盘 走势", symbol="")

    assert "error" not in result
    assert fake.queries, "应遍历默认集合"
    assert all(q[3] is None for q in fake.queries)


# ============== (b) 无 collection 遍历 4 集合并按 distance 排序 ==============


def test_search_without_collection_merges_and_sorts_by_distance():
    """collection 缺省时遍历 4 个集合, 合并结果按 distance 升序截取 top N。"""
    fake = _FakeVectorStore(
        {
            "news_chunks": [{"text": "n", "metadata": {}, "distance": 0.9, "id": "n1"}],
            "report_chunks": [{"text": "r", "metadata": {}, "distance": 0.1, "id": "r1"}],
            "announcement_chunks": [{"text": "a", "metadata": {}, "distance": 0.5, "id": "a1"}],
            "user_documents": [{"text": "u", "metadata": {}, "distance": 0.3, "id": "u1"}],
        }
    )
    retriever = _make_retriever(fake)
    results = retriever.search(query="任意", n_results=3)

    assert [r["id"] for r in results] == ["r1", "u1", "a1"]
    assert [r["distance"] for r in results] == [0.1, 0.3, 0.5]
    assert [q[0] for q in fake.queries] == DEFAULT_COLLECTIONS


def test_search_with_single_collection_unchanged():
    """显式指定 collection 时单集合行为不变。"""
    fake = _FakeVectorStore(
        {"news_chunks": [{"text": "n", "metadata": {}, "distance": 0.4, "id": "n1"}]}
    )
    retriever = _make_retriever(fake)
    results = retriever.search(query="任意", n_results=5, collection="news_chunks")

    assert [r["id"] for r in results] == ["n1"]
    assert [q[0] for q in fake.queries] == ["news_chunks"]


def test_search_without_collection_survives_collection_errors():
    """单集合查询失败不拖垮整体遍历 (与 pipeline.search_evidence 同语义)。"""
    fake = _FakeVectorStore(
        {"user_documents": [{"text": "u", "metadata": {}, "distance": 0.2, "id": "u1"}]}
    )
    original_query = fake.query

    def _flaky(collection_name, query_text, n_results=5, where=None):
        if collection_name == "news_chunks":
            raise RuntimeError("collection missing")
        return original_query(collection_name, query_text, n_results, where)

    fake.query = _flaky
    retriever = _make_retriever(fake)
    results = retriever.search(query="任意", n_results=5)

    assert [r["id"] for r in results] == ["u1"]


# ============== (c) metadata 同时含 symbol 与 symbols ==============


def test_index_news_metadata_has_both_symbol_keys():
    """index_news 写入单数 symbol (列表第一个非空值) 且保留复数 symbols。"""
    fake = _FakeVectorStore()
    retriever = _make_retriever(fake)
    count = retriever.index_news(
        [
            {
                "title": "苹果发布新品",
                "summary": "业绩超预期",
                "symbols": ["AAPL", "MSFT"],
                "source": "新浪财经",
                "datetime": 1720000000,
            }
        ]
    )

    assert count >= 1
    meta = fake.added[0]["metadatas"][0]
    assert meta["symbol"] == "AAPL"
    assert meta["symbols"] == "AAPL,MSFT"


def test_index_news_prefers_explicit_symbol_field():
    """条目带单值 symbol 字段时优先于 symbols 列表。"""
    fake = _FakeVectorStore()
    retriever = _make_retriever(fake)
    retriever.index_news(
        [{"title": "标题", "summary": "摘要", "symbol": "GOOG", "symbols": ["AAPL"]}]
    )

    meta = fake.added[0]["metadatas"][0]
    assert meta["symbol"] == "GOOG"


def test_index_reports_metadata_has_both_symbol_keys():
    """index_reports 同样写入单数 symbol 且保留复数 symbols。"""
    fake = _FakeVectorStore()
    retriever = _make_retriever(fake)
    count = retriever.index_reports(
        [
            {
                "title": "研报标题",
                "summary": "核心观点",
                "symbols": ["600519"],
                "institution": "某券商",
                "datetime": 1720000000,
            }
        ]
    )

    assert count >= 1
    meta = fake.added[0]["metadatas"][0]
    assert meta["symbol"] == "600519"
    assert meta["symbols"] == "600519"
