"""文件存储层 — 管理 documents 和 document_chunks 表"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.storage.db import Database

_DOC_TABLE = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    source_type TEXT DEFAULT 'upload',
    source_url TEXT DEFAULT '',
    title TEXT NOT NULL,
    content_hash TEXT DEFAULT '',
    file_path TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}',
    trust_score REAL DEFAULT 0.5,
    created_at REAL NOT NULL
)
"""

_CHUNK_TABLE = """
CREATE TABLE IF NOT EXISTS document_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    embedding_id TEXT DEFAULT '',
    metadata TEXT DEFAULT '{}'
)
"""


def _ensure_schema() -> None:
    """建表(幂等)。包进进程级 DB 锁, 避免与后台线程/请求线程并发写时撞锁。"""
    db = Database()
    with db.transaction() as conn:
        conn.execute(_DOC_TABLE)
        conn.execute(_CHUNK_TABLE)
        conn.commit()


# ============== Document CRUD ==============


def save_document(
    title: str,
    file_path: str = "",
    content_hash: str = "",
    source_type: str = "upload",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _ensure_schema()
    now = time.time()
    doc_id = uuid.uuid4().hex[:16]
    meta_json = json.dumps(metadata or {}, ensure_ascii=False)
    db = Database()
    # 注意: _db_lock 不可重入, 写入事务内不得调用 get_document(它会再次获取同一把锁)。
    # 写完提交后在锁外再调 get_document 读回结果。
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO documents (id, title, file_path, content_hash, source_type, metadata, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (doc_id, title, file_path, content_hash, source_type, meta_json, now),
        )
        conn.commit()
    return get_document(doc_id)


def get_document(doc_id: str) -> Optional[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return _row_to_doc(row) if row else None


def list_documents(
    source_type: Optional[str] = None, limit: int = 50
) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        if source_type:
            rows = conn.execute(
                "SELECT * FROM documents WHERE source_type=? ORDER BY created_at DESC LIMIT ?",
                (source_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM documents ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_row_to_doc(r) for r in rows]


def delete_document(doc_id: str) -> bool:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id FROM documents WHERE id=?", (doc_id,)
        ).fetchone()
        if not existing:
            return False
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.execute("DELETE FROM document_chunks WHERE document_id=?", (doc_id,))
        conn.commit()
        return True


def _row_to_doc(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "file_path": row["file_path"] or "",
        "content_hash": row["content_hash"] or "",
        "source_type": row["source_type"] or "upload",
        "metadata": json.loads(row["metadata"] or "{}"),
        "trust_score": row["trust_score"] or 0.5,
        "created_at": row["created_at"],
    }


# ============== Chunk CRUD ==============


def save_chunks(
    doc_id: str, chunks: list[str], embedding_ids: list[str] | None = None
) -> int:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        ids = embedding_ids or [""] * len(chunks)
        for i, (chunk, eid) in enumerate(zip(chunks, ids)):
            conn.execute(
                "INSERT INTO document_chunks (document_id, chunk_index, content, embedding_id) VALUES (?,?,?,?)",
                (doc_id, i, chunk, eid),
            )
        conn.commit()
    return len(chunks)


def get_chunks(doc_id: str) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM document_chunks WHERE document_id=? ORDER BY chunk_index",
            (doc_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "document_id": r["document_id"],
            "chunk_index": r["chunk_index"],
            "content": r["content"],
            "embedding_id": r["embedding_id"] or "",
        }
        for r in rows
    ]


def delete_chunks(doc_id: str) -> int:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        cursor = conn.execute(
            "DELETE FROM document_chunks WHERE document_id=?", (doc_id,)
        )
        conn.commit()
        return cursor.rowcount


# ============== Search ==============


def search_documents(query: str, limit: int = 20) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        pattern = f"%{query}%"
        rows = conn.execute(
            "SELECT DISTINCT d.* FROM documents d "
            "LEFT JOIN document_chunks c ON d.id = c.document_id "
            "WHERE d.title LIKE ? OR c.content LIKE ? "
            "ORDER BY d.created_at DESC LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall()
    return [_row_to_doc(r) for r in rows]


def content_hash(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()
