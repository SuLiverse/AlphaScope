"""告警存储层 — 持久化自选股监控告警(SQLite)。

供「自选股监控 / 通知中心」后端持久化,使告警在重启后仍保留。
告警由 ScheduledReportManager 定时扫描自选股行情后写入。
"""

from __future__ import annotations

import time
from typing import Any

from backend.storage.db import Database

_ALERT_TABLE = """
CREATE TABLE IF NOT EXISTS watchlist_alerts (
    alert_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT DEFAULT '',
    alert_type TEXT NOT NULL,
    message TEXT DEFAULT '',
    severity TEXT DEFAULT 'info',
    timestamp REAL NOT NULL,
    acknowledged INTEGER DEFAULT 0
)
"""


def _ensure_schema() -> None:
    """建表(幂等)。包进进程级 DB 锁, 避免与后台监控线程/请求线程并发写时撞锁。"""
    db = Database()
    with db.transaction() as conn:
        conn.execute(_ALERT_TABLE)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_watchlist_alerts_ts "
            "ON watchlist_alerts(timestamp DESC)"
        )
        conn.commit()


def list_alerts(
    *, unacknowledged_only: bool = False, limit: int = 200
) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    where = "WHERE acknowledged=0" if unacknowledged_only else ""
    with db.transaction() as conn:
        rows = conn.execute(
            f"SELECT alert_id, symbol, name, alert_type, message, severity, "
            f"timestamp, acknowledged FROM watchlist_alerts {where} "
            f"ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        {
            "alert_id": r["alert_id"],
            "symbol": r["symbol"],
            "name": r["name"],
            "type": r["alert_type"],
            "message": r["message"],
            "severity": r["severity"],
            "timestamp": r["timestamp"],
            "acknowledged": bool(r["acknowledged"]),
        }
        for r in rows
    ]


def count_unacknowledged() -> int:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM watchlist_alerts WHERE acknowledged=0"
        ).fetchone()
    return int(row["c"]) if row else 0


def add_alert(
    *,
    alert_id: str,
    symbol: str,
    name: str,
    alert_type: str,
    message: str,
    severity: str = "info",
    timestamp: float | None = None,
) -> bool:
    """写入一条告警。按 alert_id 去重(已存在返回 False)。"""
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT alert_id FROM watchlist_alerts WHERE alert_id=?", (alert_id,)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO watchlist_alerts "
            "(alert_id, symbol, name, alert_type, message, severity, timestamp, acknowledged) "
            "VALUES (?,?,?,?,?,?,?,0)",
            (
                alert_id,
                symbol,
                name,
                alert_type,
                message,
                severity,
                timestamp or time.time(),
            ),
        )
        conn.commit()
    return True


def acknowledge_alert(alert_id: str) -> bool:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE watchlist_alerts SET acknowledged=1 WHERE alert_id=?", (alert_id,)
        )
        conn.commit()
        return cur.rowcount > 0


def acknowledge_all() -> int:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        cur = conn.execute(
            "UPDATE watchlist_alerts SET acknowledged=1 WHERE acknowledged=0"
        )
        conn.commit()
        return cur.rowcount


def clear_all(*, acknowledged_only: bool = False) -> int:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        if acknowledged_only:
            cur = conn.execute("DELETE FROM watchlist_alerts WHERE acknowledged=1")
        else:
            cur = conn.execute("DELETE FROM watchlist_alerts")
        conn.commit()
        return cur.rowcount
