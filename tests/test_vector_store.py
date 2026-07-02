"""vector_store.query 边界测试 — ChromaDB 无命中/结构异常不崩。

锁住上轮索引越界修复: results['documents'] 为 [] 或缺键时返回 [] 而非 IndexError。
用 __new__ 绕过 VectorStore 单例, mock get_collection 返回假 collection。
"""

from __future__ import annotations

from unittest.mock import MagicMock

from backend.rag.vector_store import VectorStore


def _make_store_with_collection(query_result: dict) -> VectorStore:
    """构造一个绕单例的 VectorStore, get_collection 返回 mock collection。"""
    vs = VectorStore.__new__(VectorStore)
    mock_collection = MagicMock()
    mock_collection.query.return_value = query_result
    vs.get_collection = lambda _name: mock_collection  # type: ignore[method-assign]
    return vs


def test_query_empty_documents_no_crash():
    """ChromaDB 无命中 documents=[] 时返回 [] 而非 IndexError。"""
    vs = _make_store_with_collection({"documents": []})
    assert vs.query("test", "query", n_results=5) == []


def test_query_missing_keys_no_crash():
    """结果缺 documents/metadatas/distances/ids 键时不崩, 返回填充默认值的列表。"""
    vs = _make_store_with_collection({"documents": [["a", "b"]]})  # 缺其它键
    result = vs.query("test", "query", n_results=5)
    assert len(result) == 2
    assert result[0]["text"] == "a"
    assert result[0]["metadata"] == {}
    assert result[0]["distance"] == 0
    assert result[0]["id"] == ""


def test_query_normal_result():
    """正常完整结果结构正确解析。"""
    vs = _make_store_with_collection(
        {
            "documents": [["doc1", "doc2"]],
            "metadatas": [[{"src": "x"}, {"src": "y"}]],
            "distances": [[0.1, 0.2]],
            "ids": [["id1", "id2"]],
        }
    )
    result = vs.query("test", "query", n_results=5)
    assert len(result) == 2
    assert result[0] == {"text": "doc1", "metadata": {"src": "x"}, "distance": 0.1, "id": "id1"}
    assert result[1]["id"] == "id2"


def test_query_mismatched_lengths_safe():
    """documents 与 metadata 长度不一致时逐元素长度检查不越界。"""
    vs = _make_store_with_collection(
        {
            "documents": [["a", "b", "c"]],
            "metadatas": [[{"src": "x"}]],  # 只有 1 个, documents 有 3 个
            "distances": [[0.1]],
            "ids": [["id1"]],
        }
    )
    result = vs.query("test", "query", n_results=5)
    assert len(result) == 3
    assert result[0]["metadata"] == {"src": "x"}
    assert result[1]["metadata"] == {}  # 越界回退默认
    assert result[2]["metadata"] == {}
