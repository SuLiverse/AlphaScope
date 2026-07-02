"""新闻存储层 — 管理 news_items 和 announcements 表"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.storage.db import Database

_MOJIBAKE_MARKERS = (
    "\ufffd",
    "\u00c2",
    "\u00c3",
    "\u00e2",
    "\u00e4",
    "\u00e5",
    "\u00e6",
    "\u00e7",
    "\u00e8",
    "\u00e9",
)


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def _looks_mojibake(value: str) -> bool:
    if not value:
        return False
    if any("\u0080" <= ch <= "\u009f" for ch in value):
        return True
    return sum(1 for ch in value if ch in _MOJIBAKE_MARKERS) >= 2


def _repair_text(value: Any) -> str:
    text = str(value or "")
    if not text or not _looks_mojibake(text):
        return text
    try:
        repaired = text.encode("latin1").decode("utf-8")
    except UnicodeError:
        return text
    if _contains_cjk(repaired) and len(repaired) <= len(text):
        return repaired
    return repaired if _contains_cjk(repaired) else text


# ============== News CRUD ==============


def list_news(
    symbol: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db = Database()
    with db.transaction() as conn:
        conditions = []
        params: list[Any] = []

        if symbol:
            conditions.append("symbols LIKE ?")
            params.append(f"%{symbol}%")
        if event_type:
            conditions.append("event_type=?")
            params.append(event_type)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM news_items{where} ORDER BY published_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row_to_news(r) for r in rows]


def get_news(news_id: str) -> Optional[dict[str, Any]]:
    db = Database()
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM news_items WHERE id=?", (news_id,)).fetchone()
    return _row_to_news(row) if row else None


def search_news(query: str, limit: int = 20) -> list[dict[str, Any]]:
    db = Database()
    with db.transaction() as conn:
        pattern = f"%{query}%"
        rows = conn.execute(
            "SELECT * FROM news_items "
            "WHERE title LIKE ? OR summary LIKE ? "
            "ORDER BY published_at DESC LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall()
    return [_row_to_news(r) for r in rows]


def _row_to_news(row) -> dict[str, Any]:
    symbols = row["symbols"] or ""
    if isinstance(symbols, str):
        try:
            symbols = json.loads(symbols)
        except Exception:
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]

    return {
        "id": row["id"],
        "title": _repair_text(row["title"]),
        "summary": _repair_text(row["summary"]),
        "source": _repair_text(row["source"]),
        "source_url": row["source_url"] or "",
        "published_at": row["published_at"] or "",
        "symbols": symbols,
        "event_type": row["event_type"] or "other",
        "sentiment": row["sentiment"] or 0,
        "importance": row["importance"] or 0.5,
        "confidence": row["confidence"] or 0.6,
    }


# ============== Announcement CRUD ==============


def list_announcements(
    symbol: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db = Database()
    with db.transaction() as conn:
        conditions = []
        params: list[Any] = []

        if symbol:
            conditions.append("symbol=?")
            params.append(symbol)
        if category:
            conditions.append("category=?")
            params.append(category)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM announcements{where} ORDER BY published_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_row_to_announcement(r) for r in rows]


def get_announcement(ann_id: str) -> Optional[dict[str, Any]]:
    db = Database()
    with db.transaction() as conn:
        row = conn.execute("SELECT * FROM announcements WHERE id=?", (ann_id,)).fetchone()
    return _row_to_announcement(row) if row else None


def _row_to_announcement(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "company_name": _repair_text(row["company_name"]),
        "title": _repair_text(row["title"]),
        "category": _repair_text(row["category"]) or "other",
        "published_at": row["published_at"] or "",
        "source": _repair_text(row["source"]),
        "source_url": row["source_url"] or "",
        "importance": row["importance"] or 0.5,
        "confidence": row["confidence"] or 0.9,
    }


# ============== Event Summary ==============


def get_event_summary(symbol: str, days: int = 30) -> dict[str, Any]:
    """获取事件摘要：类型分布 + 情绪趋势。"""
    db = Database()
    with db.transaction() as conn:
        # 事件类型分布
        rows = conn.execute(
            "SELECT event_type, COUNT(*) as cnt, AVG(sentiment) as avg_sent "
            "FROM news_items "
            "WHERE symbols LIKE ? AND published_at >= date('now', ?) "
            "GROUP BY event_type ORDER BY cnt DESC",
            (f"%{symbol}%", f"-{days} days"),
        ).fetchall()

        type_dist = {}
        for r in rows:
            et = r["event_type"] or "other"
            type_dist[et] = {
                "count": r["cnt"],
                "avg_sentiment": round(r["avg_sent"] or 0, 3),
            }

        # 总数和平均情绪
        total_row = conn.execute(
            "SELECT COUNT(*) as total, AVG(sentiment) as avg_sent "
            "FROM news_items "
            "WHERE symbols LIKE ? AND published_at >= date('now', ?)",
            (f"%{symbol}%", f"-{days} days"),
        ).fetchone()

    return {
        "symbol": symbol,
        "days": days,
        "total_news": total_row["total"] if total_row else 0,
        "avg_sentiment": round(total_row["avg_sent"] or 0, 3) if total_row else 0,
        "type_distribution": type_dist,
    }
