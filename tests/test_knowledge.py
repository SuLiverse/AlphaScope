"""Tests for Knowledge Base API — 知识库管理端点 + file_store CRUD"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


# ============== file_store 单元测试 ==============


def _patch_file_db():
    """mock 进程级单例 Database, transaction() 上下文给出同一 mock conn。
    CRUD 现在走 with Database().transaction() as conn:, 不再暴露 _get_conn。"""
    conn = MagicMock()
    db_mock = MagicMock()
    db_mock.transaction.return_value.__enter__.return_value = conn
    db_mock.transaction.return_value.__exit__.return_value = False
    return patch("backend.file_store.Database", return_value=db_mock), conn


class TestFileStore:
    """测试 file_store CRUD 函数"""

    def test_save_document(self, tmp_path):
        """save_document 返回正确的文档结构"""
        from backend.file_store import save_document

        patcher, conn = _patch_file_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = None
            conn.execute.return_value.fetchall.return_value = []

            # 测试函数调用不报错
            save_document(
                title="test.txt",
                file_path="/tmp/test.txt",
                content_hash="abc123",
                source_type="upload",
                metadata={"key": "value"},
            )
            assert conn.execute.called
            assert conn.commit.called

    def test_list_documents(self):
        """list_documents 调用正确的 SQL"""
        from backend.file_store import list_documents

        patcher, conn = _patch_file_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []

            result = list_documents()
            assert isinstance(result, list)
            assert conn.execute.called

    def test_list_documents_with_source_type(self):
        """list_documents 支持 source_type 过滤"""
        from backend.file_store import list_documents

        patcher, conn = _patch_file_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []

            list_documents(source_type="upload", limit=10)
            conn.execute.assert_called()

    def test_delete_document(self):
        """delete_document 删除不存在的文档返回 False"""
        from backend.file_store import delete_document

        patcher, conn = _patch_file_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = None

            result = delete_document("nonexistent")
            assert result is False

    def test_delete_document_exists(self):
        """delete_document 删除存在的文档返回 True"""
        from backend.file_store import delete_document

        patcher, conn = _patch_file_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = {"id": "abc"}

            result = delete_document("abc")
            assert result is True
            assert conn.commit.called

    def test_save_chunks(self):
        """save_chunks 返回正确的 chunk 数量"""
        from backend.file_store import save_chunks

        patcher, conn = _patch_file_db()
        with patcher:
            count = save_chunks("doc1", ["chunk1", "chunk2", "chunk3"])
            assert count == 3
            # 只统计插入 chunk 的 execute(建表 SQL 不计入业务调用计数)
            insert_calls = [
                c for c in conn.execute.call_args_list
                if "INSERT INTO document_chunks" in str(c)
            ]
            assert len(insert_calls) == 3

    def test_get_chunks(self):
        """get_chunks 返回列表"""
        from backend.file_store import get_chunks

        patcher, conn = _patch_file_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []

            result = get_chunks("doc1")
            assert isinstance(result, list)

    def test_delete_chunks(self):
        """delete_chunks 返回删除数量"""
        from backend.file_store import delete_chunks

        patcher, conn = _patch_file_db()
        with patcher:
            conn.execute.return_value.rowcount = 5

            count = delete_chunks("doc1")
            assert count == 5

    def test_search_documents(self):
        """search_documents 调用正确的 SQL"""
        from backend.file_store import search_documents

        patcher, conn = _patch_file_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []

            result = search_documents("test query")
            assert isinstance(result, list)

    def test_content_hash(self):
        """content_hash 返回 MD5 字符串"""
        from backend.file_store import content_hash

        h = content_hash(b"hello world")
        assert isinstance(h, str)
        assert len(h) == 32
        # 同样内容应返回同样的 hash
        assert content_hash(b"hello world") == h


# ============== Knowledge API 测试 ==============


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_list_documents(client):
    """GET /api/knowledge/documents 返回文档列表"""
    with patch("backend.file_store.list_documents", return_value=[]):
        resp = await client.get("/api/knowledge/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "documents" in data["data"]
    assert "total" in data["data"]


@pytest.mark.anyio
async def test_list_documents_with_filter(client):
    """GET /api/knowledge/documents?source_type=upload 支持过滤"""
    with patch("backend.file_store.list_documents", return_value=[]):
        resp = await client.get("/api/knowledge/documents?source_type=upload")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.anyio
async def test_get_document_not_found(client):
    """GET /api/knowledge/documents/{id} 不存在返回错误"""
    with patch("backend.file_store.get_document", return_value=None):
        resp = await client.get("/api/knowledge/documents/nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "不存在" in data["error"]


@pytest.mark.anyio
async def test_get_document_found(client):
    """GET /api/knowledge/documents/{id} 存在返回详情"""
    mock_doc = {
        "id": "abc123",
        "title": "test.txt",
        "file_path": "/tmp/test.txt",
        "content_hash": "hash",
        "source_type": "upload",
        "metadata": {},
        "trust_score": 0.5,
        "created_at": time.time(),
    }
    with (
        patch("backend.file_store.get_document", return_value=mock_doc),
        patch("backend.file_store.get_chunks", return_value=[]),
    ):
        resp = await client.get("/api/knowledge/documents/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["id"] == "abc123"
    assert "chunks" in data["data"]


@pytest.mark.anyio
async def test_delete_document_not_found(client):
    """DELETE /api/knowledge/documents/{id} 不存在返回错误"""
    with patch("backend.file_store.delete_document", return_value=False):
        resp = await client.delete("/api/knowledge/documents/nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "不存在" in data["error"]


@pytest.mark.anyio
async def test_delete_document_success(client):
    """DELETE /api/knowledge/documents/{id} 成功"""
    with patch("backend.file_store.delete_document", return_value=True):
        resp = await client.delete("/api/knowledge/documents/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["deleted"] == "abc123"


@pytest.mark.anyio
async def test_search_knowledge_vector(client):
    """POST /api/knowledge/search 向量搜索成功"""
    mock_results = [
        {"text": "chunk1", "metadata": {"doc_id": "d1"}, "distance": 0.5, "id": "c1"}
    ]
    with patch("backend.rag.vector_store.VectorStore") as MockVS:
        instance = MockVS.return_value
        instance.query.return_value = mock_results
        resp = await client.post(
            "/api/knowledge/search", json={"query": "test", "limit": 10}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["query"] == "test"
    assert len(data["data"]["results"]) == 1
    assert data["data"]["results"][0]["source"] == "vector"


@pytest.mark.anyio
async def test_search_knowledge_fallback(client):
    """POST /api/knowledge/search ChromaDB 不可用时降级到 SQLite"""
    with (
        patch(
            "backend.rag.vector_store.VectorStore",
            side_effect=RuntimeError("chromadb 未安装"),
        ),
        patch(
            "backend.file_store.search_documents",
            return_value=[
                {
                    "id": "d1",
                    "title": "test doc",
                    "source_type": "upload",
                    "file_path": "",
                    "content_hash": "",
                    "metadata": {},
                    "trust_score": 0.5,
                    "created_at": time.time(),
                }
            ],
        ),
    ):
        resp = await client.post(
            "/api/knowledge/search", json={"query": "test", "limit": 10}
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["results"]) == 1
    assert data["data"]["results"][0]["source"] == "sqlite"


@pytest.mark.anyio
async def test_upload_document_unsupported_format(client):
    """POST /api/knowledge/upload 不支持的格式返回错误"""
    resp = await client.post(
        "/api/knowledge/upload",
        files={"file": ("test.exe", b"content", "application/octet-stream")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "不支持" in data["error"]


@pytest.mark.anyio
async def test_upload_document_success(client):
    """POST /api/knowledge/upload 成功上传并处理"""
    mock_doc = MagicMock()
    mock_doc.doc_id = "new_doc_123"
    mock_doc.filename = "test.txt"
    mock_doc.chunk_count = 3
    mock_doc.processing_time_ms = 100.0

    with patch(
        "backend.rag.document_pipeline.DocumentPipeline.process_and_persist",
        return_value=mock_doc,
    ):
        resp = await client.post(
            "/api/knowledge/upload",
            files={"file": ("test.txt", b"hello world", "text/plain")},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["doc_id"] == "new_doc_123"
    assert data["data"]["chunks"] == 3
