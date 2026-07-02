"""自选股存储层 — 持久化用户自选列表(SQLite)。

供「自选晨报」后端持久化,使自选在清理 localStorage / 打包重装后仍保留。
"""

from __future__ import annotations

import time
from typing import Any

from backend.storage.db import Database

_WATCHLIST_TABLE = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    added_at REAL NOT NULL
)
"""


def _ensure_schema() -> None:
    """建表(幂等)。包进进程级 DB 锁, 避免与后台告警扫描线程并发撞锁。"""
    db = Database()
    with db.transaction() as conn:
        conn.execute(_WATCHLIST_TABLE)
        conn.commit()


def list_watchlist() -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT symbol, name, added_at FROM watchlist ORDER BY added_at DESC"
        ).fetchall()
    return [
        {"symbol": r["symbol"], "name": r["name"], "added_at": r["added_at"]}
        for r in rows
    ]


def add_watchlist(symbol: str, name: str = "") -> None:
    symbol = (symbol or "").strip()
    if not symbol:
        return
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO watchlist (symbol, name, added_at) VALUES (?,?,?) "
            "ON CONFLICT(symbol) DO UPDATE SET name=excluded.name",
            (symbol, name or symbol, time.time()),
        )
        conn.commit()


def remove_watchlist(symbol: str) -> None:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol=?", ((symbol or "").strip(),))
        conn.commit()
