"""证据存储层 — 管理 evidence_items 和 evidence_links 表"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.storage.db import Database

_EVIDENCE_TABLE = """
CREATE TABLE IF NOT EXISTS evidence_items (
    id TEXT PRIMARY KEY,
    evidence_type TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT,
    published_at TEXT,
    content_summary TEXT,
    symbols TEXT,
    confidence REAL DEFAULT 0.7,
    relevance REAL DEFAULT 0.5
)
"""

_LINK_TABLE = """
CREATE TABLE IF NOT EXISTS evidence_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id TEXT REFERENCES evidence_items(id) ON DELETE CASCADE,
    conversation_id TEXT DEFAULT '',
    message_id TEXT DEFAULT '',
    claim TEXT NOT NULL,
    created_at REAL NOT NULL
)
"""

_LINK_INDEX = """
CREATE INDEX IF NOT EXISTS idx_evidence_links_claim ON evidence_links(claim)
"""


def _ensure_schema() -> None:
    """建表(幂等)。包进进程级 DB 锁, 避免与后台线程/请求线程并发写时撞锁。"""
    db = Database()
    with db.transaction() as conn:
        conn.execute(_EVIDENCE_TABLE)
        conn.execute(_LINK_TABLE)
        conn.execute(_LINK_INDEX)
        # 补列：claim, data_date, created_at（如果不存在）
        _add_column_if_missing(conn, "evidence_items", "claim", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "evidence_items", "data_date", "TEXT DEFAULT ''")
        _add_column_if_missing(conn, "evidence_items", "created_at", "REAL DEFAULT 0")
        conn.commit()


def _add_column_if_missing(conn, table: str, column: str, col_def: str) -> None:
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except Exception:
        pass  # 列已存在


# ============== Evidence CRUD ==============


def save_evidence(
    evidence_type: str,
    title: str,
    source: str,
    claim: str = "",
    content_summary: str = "",
    symbols: list[str] | None = None,
    confidence: float = 0.7,
    source_url: str = "",
    data_date: str = "",
    relevance: float = 0.5,
) -> dict[str, Any]:
    _ensure_schema()
    evidence_id = uuid.uuid4().hex[:16]
    now = time.time()
    symbols_json = json.dumps(symbols or [], ensure_ascii=False)
    db = Database()
    # 注意: _db_lock 不可重入, 写入事务内不得调用 get_evidence(它会再次获取同一把锁)。
    # 写完提交后在锁外再调 get_evidence 读回结果。
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO evidence_items "
            "(id, evidence_type, title, source, source_url, content_summary, symbols, "
            "confidence, relevance, claim, data_date, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                evidence_id,
                evidence_type,
                title,
                source,
                source_url,
                content_summary,
                symbols_json,
                confidence,
                relevance,
                claim,
                data_date,
                now,
            ),
        )
        conn.commit()
    return get_evidence(evidence_id)


def get_evidence(evidence_id: str) -> Optional[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT * FROM evidence_items WHERE id=?", (evidence_id,)
        ).fetchone()
    return _row_to_evidence(row) if row else None


def list_evidence(
    evidence_type: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        if evidence_type and symbol:
            pattern = f"%{symbol}%"
            rows = conn.execute(
                "SELECT * FROM evidence_items WHERE evidence_type=? AND symbols LIKE ? "
                "ORDER BY created_at DESC LIMIT ?",
                (evidence_type, pattern, limit),
            ).fetchall()
        elif evidence_type:
            rows = conn.execute(
                "SELECT * FROM evidence_items WHERE evidence_type=? ORDER BY created_at DESC LIMIT ?",
                (evidence_type, limit),
            ).fetchall()
        elif symbol:
            pattern = f"%{symbol}%"
            rows = conn.execute(
                "SELECT * FROM evidence_items WHERE symbols LIKE ? ORDER BY created_at DESC LIMIT ?",
                (pattern, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM evidence_items ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [_row_to_evidence(r) for r in rows]


def delete_evidence(evidence_id: str) -> bool:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id FROM evidence_items WHERE id=?", (evidence_id,)
        ).fetchone()
        if not existing:
            return False
        conn.execute("DELETE FROM evidence_items WHERE id=?", (evidence_id,))
        conn.execute("DELETE FROM evidence_links WHERE evidence_id=?", (evidence_id,))
        conn.commit()
        return True


def search_evidence(query: str, limit: int = 20) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        pattern = f"%{query}%"
        rows = conn.execute(
            "SELECT * FROM evidence_items "
            "WHERE title LIKE ? OR claim LIKE ? OR content_summary LIKE ? "
            "ORDER BY created_at DESC LIMIT ?",
            (pattern, pattern, pattern, limit),
        ).fetchall()
    return [_row_to_evidence(r) for r in rows]


def _row_to_evidence(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "evidence_type": row["evidence_type"],
        "title": row["title"],
        "source": row["source"],
        "source_url": row["source_url"] or "",
        "content_summary": row["content_summary"] or "",
        "symbols": json.loads(row["symbols"] or "[]"),
        "confidence": row["confidence"] or 0.7,
        "relevance": row["relevance"] or 0.5,
        "claim": row["claim"] or "",
        "data_date": row["data_date"] or "",
        "created_at": row["created_at"] or 0,
    }


# ============== Evidence Links ==============


def save_evidence_link(
    evidence_id: str,
    claim: str,
    conversation_id: str = "",
    message_id: str = "",
) -> None:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO evidence_links (evidence_id, conversation_id, message_id, claim, created_at) "
            "VALUES (?,?,?,?,?)",
            (evidence_id, conversation_id, message_id, claim, time.time()),
        )
        conn.commit()


def get_evidence_for_claim(claim_keyword: str) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        pattern = f"%{claim_keyword}%"
        rows = conn.execute(
            "SELECT e.* FROM evidence_items e "
            "JOIN evidence_links l ON e.id = l.evidence_id "
            "WHERE l.claim LIKE ? "
            "ORDER BY e.confidence DESC",
            (pattern,),
        ).fetchall()
    return [_row_to_evidence(r) for r in rows]
