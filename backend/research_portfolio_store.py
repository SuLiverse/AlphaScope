"""研究组合持仓存储层 — 持久化用户的研究持仓(SQLite)。

供「组合与风控」页后端持久化,使持仓在清理 localStorage / 打包重装后仍保留。
与 portfolio_new.py 的「现金组合 + 交易流水」模型不同:这里存的是用户手工录入的
研究仓位(symbol/name/sector/shares/cost),与前端 ResearchPosition 一一对应。
"""

from __future__ import annotations

import time
from typing import Any

from backend.storage.db import Database

_POSITIONS_TABLE = """
CREATE TABLE IF NOT EXISTS research_positions (
    symbol TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    sector TEXT DEFAULT '',
    shares REAL NOT NULL,
    cost REAL NOT NULL,
    added_at REAL NOT NULL
)
"""


def _get_conn():
    db = Database()
    db._conn.execute(_POSITIONS_TABLE)
    db._conn.commit()
    return db._conn


def list_positions() -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT symbol, name, sector, shares, cost, added_at "
        "FROM research_positions ORDER BY added_at DESC"
    ).fetchall()
    return [
        {
            "symbol": r["symbol"],
            "name": r["name"] or "",
            "sector": r["sector"] or "",
            "shares": float(r["shares"]),
            "cost": float(r["cost"]),
            "added_at": r["added_at"],
        }
        for r in rows
    ]


def upsert_position(
    symbol: str,
    name: str = "",
    sector: str = "",
    shares: float = 0.0,
    cost: float = 0.0,
) -> None:
    symbol = (symbol or "").strip()
    if not symbol:
        return
    conn = _get_conn()
    conn.execute(
        "INSERT INTO research_positions "
        "(symbol, name, sector, shares, cost, added_at) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(symbol) DO UPDATE SET "
        "name=excluded.name, sector=excluded.sector, shares=excluded.shares, "
        "cost=excluded.cost",
        (symbol, name or symbol, sector or "", float(shares), float(cost), time.time()),
    )
    conn.commit()


def remove_position(symbol: str) -> bool:
    conn = _get_conn()
    cur = conn.execute(
        "DELETE FROM research_positions WHERE symbol=?",
        ((symbol or "").strip(),),
    )
    conn.commit()
    return cur.rowcount > 0


def clear_positions() -> int:
    conn = _get_conn()
    cur = conn.execute("DELETE FROM research_positions")
    conn.commit()
    return cur.rowcount
