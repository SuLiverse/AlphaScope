"""数据库层 - SQLite + 文件缓存

轻量化实现, 后续可迁移到 PostgreSQL。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

from backend.project_paths import DB_DIR

DB_PATH = DB_DIR / "ai_finance.db"


class Database:
    """SQLite 数据库管理

    Thread-safe singleton with double-checked locking.
    """

    _instance: Optional["Database"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "Database":
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        # Use class-level lock to prevent race between __new__ and __init__
        with type(self)._lock:
            if self._initialized:
                return
            self._initialized = True
            self._db_lock = threading.Lock()
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._create_tables()

    @contextmanager
    def transaction(self):
        """Acquire the DB lock for thread-safe read/write operations.

        External callers (task_queue, agent_store, etc.) should use this
        instead of accessing _conn directly to ensure proper locking.
        """
        with self._db_lock:
            yield self._conn

    def _create_tables(self) -> None:
        """创建核心数据表"""
        cur = self._conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS news_items (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                summary TEXT,
                content TEXT,
                source TEXT NOT NULL,
                upstream TEXT,
                source_url TEXT,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                symbols TEXT,
                industries TEXT,
                event_type TEXT,
                sentiment REAL DEFAULT 0,
                importance REAL DEFAULT 0.5,
                confidence REAL DEFAULT 0.6,
                license_level TEXT DEFAULT 'research_only'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS research_reports (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                report_type TEXT DEFAULT 'company',
                institution TEXT,
                authors TEXT,
                symbols TEXT,
                industry TEXT,
                rating TEXT,
                target_price REAL,
                summary TEXT,
                pdf_url TEXT,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                source TEXT NOT NULL,
                source_url TEXT,
                pdf_hash TEXT,
                confidence REAL DEFAULT 0.8,
                license_level TEXT DEFAULT 'restricted'
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                company_name TEXT,
                title TEXT NOT NULL,
                category TEXT,
                published_at TEXT,
                fetched_at TEXT NOT NULL,
                source TEXT NOT NULL,
                source_url TEXT,
                pdf_url TEXT,
                pdf_hash TEXT,
                parsed_text_path TEXT,
                importance REAL DEFAULT 0.5,
                confidence REAL DEFAULT 0.9
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS price_bars (
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                market TEXT DEFAULT 'CN',
                frequency TEXT DEFAULT '1d',
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL DEFAULT 0,
                amount REAL DEFAULT 0,
                turnover REAL DEFAULT 0,
                amplitude REAL DEFAULT 0,
                change_pct REAL DEFAULT 0,
                adjust TEXT DEFAULT 'hfq',
                source TEXT DEFAULT 'akshare',
                PRIMARY KEY (symbol, date, frequency)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS source_fetch_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                endpoint TEXT,
                status TEXT NOT NULL,
                latency_ms REAL,
                items_count INTEGER DEFAULT 0,
                error_message TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT
            )
        """)

        cur.execute("""
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
        """)

        # 创建索引
        cur.execute("CREATE INDEX IF NOT EXISTS idx_news_source ON news_items(source)")
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_news_published ON news_items(published_at)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_reports_source ON research_reports(source)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_announcements_symbol ON announcements(symbol)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_announcements_source ON announcements(source)"
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_bars(symbol)")

        self._conn.commit()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def insert_news(self, item: dict) -> None:
        """插入新闻条目"""
        with self._db_lock:
            cur = self._conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO news_items
                (id, title, summary, content, source, upstream, source_url,
                 published_at, fetched_at, symbols, industries, event_type,
                 sentiment, importance, confidence, license_level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.get("id", ""),
                    item.get("title", ""),
                    item.get("summary", ""),
                    item.get("content", ""),
                    item.get("source", ""),
                    item.get("upstream", ""),
                    item.get("source_url", ""),
                    item.get("published_at", ""),
                    item.get("fetched_at", datetime.now().isoformat()),
                    json.dumps(item.get("symbols", []), ensure_ascii=False),
                    json.dumps(item.get("industries", []), ensure_ascii=False),
                    item.get("event_type", ""),
                    item.get("sentiment", 0),
                    item.get("importance", 0.5),
                    item.get("confidence", 0.6),
                    item.get("license_level", "research_only"),
                ),
            )
        self._conn.commit()

    def insert_report(self, item: dict) -> None:
        """插入研报条目"""
        with self._db_lock:
            cur = self._conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO research_reports
                (id, title, report_type, institution, authors, symbols, industry,
                 rating, target_price, summary, pdf_url, published_at, fetched_at,
                 source, source_url, pdf_hash, confidence, license_level)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.get("id", ""),
                    item.get("title", ""),
                    item.get("report_type", "company"),
                    item.get("institution", ""),
                    json.dumps(item.get("authors", []), ensure_ascii=False),
                    json.dumps(item.get("symbols", []), ensure_ascii=False),
                    item.get("industry", ""),
                    item.get("rating", ""),
                    item.get("target_price"),
                    item.get("summary", ""),
                    item.get("pdf_url", ""),
                    item.get("published_at", ""),
                    item.get("fetched_at", datetime.now().isoformat()),
                    item.get("source", ""),
                    item.get("source_url", ""),
                    item.get("pdf_hash", ""),
                    item.get("confidence", 0.8),
                    item.get("license_level", "restricted"),
                ),
            )
            self._conn.commit()

    def insert_announcement(self, item: dict) -> None:
        """插入公告条目"""
        with self._db_lock:
            cur = self._conn.cursor()
            cur.execute(
                """INSERT OR REPLACE INTO announcements
                (id, symbol, company_name, title, category, published_at, fetched_at,
                 source, source_url, pdf_url, pdf_hash, parsed_text_path,
                 importance, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.get("id", ""),
                    item.get("symbol", ""),
                    item.get("company_name", ""),
                    item.get("title", ""),
                    item.get("category", ""),
                    item.get("published_at", ""),
                    item.get("fetched_at", datetime.now().isoformat()),
                    item.get("source", ""),
                    item.get("source_url", ""),
                    item.get("pdf_url", ""),
                    item.get("pdf_hash", ""),
                    item.get("parsed_text_path", ""),
                    item.get("importance", 0.5),
                    item.get("confidence", 0.9),
                ),
            )
            self._conn.commit()

    def insert_fetch_log(self, log: dict) -> None:
        """插入抓取日志"""
        with self._db_lock:
            cur = self._conn.cursor()
            cur.execute(
                """INSERT INTO source_fetch_logs
                (source, endpoint, status, latency_ms, items_count,
                 error_message, started_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    log.get("source", ""),
                    log.get("endpoint", ""),
                    log.get("status", ""),
                    log.get("latency_ms", 0),
                    log.get("items_count", 0),
                    log.get("error_message", ""),
                    log.get("started_at", datetime.now().isoformat()),
                    log.get("finished_at", ""),
                ),
            )
            self._conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
