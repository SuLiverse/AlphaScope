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


_schema_ensured = False


def _ensure_schema() -> None:
    """建表(幂等)。包进进程级 DB 锁。首次建表后置 flag, 后续调用跳过。"""
    global _schema_ensured
    if _schema_ensured:
        return
    db = Database()
    with db.transaction() as conn:
        conn.execute(_POSITIONS_TABLE)
        conn.commit()
    _schema_ensured = True


def list_positions() -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
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
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
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
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        cur = conn.execute(
            "DELETE FROM research_positions WHERE symbol=?",
            ((symbol or "").strip(),),
        )
        conn.commit()
        return cur.rowcount > 0


def clear_positions() -> int:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        cur = conn.execute("DELETE FROM research_positions")
        conn.commit()
        return cur.rowcount
