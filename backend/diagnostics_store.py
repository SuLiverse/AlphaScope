"""诊断存储层 — 管理 tool_calls、cost_records 表 + 健康历史"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.storage.db import Database

_TOOL_CALLS_TABLE = """
CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT DEFAULT '',
    agent_id TEXT DEFAULT '',
    tool_name TEXT NOT NULL,
    input_json TEXT DEFAULT '{}',
    output_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'ok',
    latency_ms REAL DEFAULT 0,
    created_at REAL NOT NULL
)
"""

_COST_RECORDS_TABLE = """
CREATE TABLE IF NOT EXISTS cost_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT DEFAULT '',
    agent_id TEXT DEFAULT '',
    model TEXT NOT NULL,
    vendor TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0,
    mode TEXT DEFAULT '',
    created_at REAL NOT NULL
)
"""


def _ensure_schema() -> None:
    """建表(幂等)。包进进程级 DB 锁, 避免与后台线程/请求线程并发写时撞锁。"""
    db = Database()
    with db.transaction() as conn:
        conn.execute(_TOOL_CALLS_TABLE)
        conn.execute(_COST_RECORDS_TABLE)
        conn.commit()


# ============== Tool Calls ==============


def save_tool_call(
    tool_name: str,
    input_json: str = "{}",
    output_json: str = "{}",
    status: str = "ok",
    latency_ms: float = 0,
    conversation_id: str = "",
    agent_id: str = "",
) -> None:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO tool_calls (conversation_id, agent_id, tool_name, input_json, "
            "output_json, status, latency_ms, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                conversation_id,
                agent_id,
                tool_name,
                input_json,
                output_json,
                status,
                latency_ms,
                time.time(),
            ),
        )
        conn.commit()


def list_tool_calls(limit: int = 50) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM tool_calls ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {
            "id": r["id"],
            "tool_name": r["tool_name"],
            "status": r["status"],
            "latency_ms": r["latency_ms"] or 0,
            "conversation_id": r["conversation_id"] or "",
            "agent_id": r["agent_id"] or "",
            "created_at": r["created_at"] or 0,
        }
        for r in rows
    ]


# ============== Cost Records ==============


def save_cost_record(
    model: str,
    vendor: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0,
    mode: str = "",
    conversation_id: str = "",
    agent_id: str = "",
) -> None:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO cost_records (conversation_id, agent_id, model, vendor, "
            "input_tokens, output_tokens, cost_usd, mode, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                conversation_id,
                agent_id,
                model,
                vendor,
                input_tokens,
                output_tokens,
                cost_usd,
                mode,
                time.time(),
            ),
        )
        conn.commit()


def list_cost_records(
    model: Optional[str] = None, limit: int = 50
) -> list[dict[str, Any]]:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        if model:
            rows = conn.execute(
                "SELECT * FROM cost_records WHERE model=? ORDER BY created_at DESC LIMIT ?",
                (model, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM cost_records ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
    return [
        {
            "id": r["id"],
            "model": r["model"],
            "vendor": r["vendor"] or "",
            "input_tokens": r["input_tokens"] or 0,
            "output_tokens": r["output_tokens"] or 0,
            "cost_usd": r["cost_usd"] or 0,
            "mode": r["mode"] or "",
            "created_at": r["created_at"] or 0,
        }
        for r in rows
    ]


# ============== Health History ==============


def get_health_history(limit: int = 50) -> list[dict[str, Any]]:
    """读取 source_fetch_logs 作为健康历史。"""
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM source_fetch_logs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [
        {
            "id": r["id"],
            "source": r["source"],
            "endpoint": r["endpoint"] or "",
            "status": r["status"],
            "latency_ms": r["latency_ms"] or 0,
            "items_count": r["items_count"] or 0,
            "error_message": r["error_message"] or "",
            "started_at": r["started_at"] or "",
            "finished_at": r["finished_at"] or "",
        }
        for r in rows
    ]


# ============== Diagnostics Summary ==============


def get_cost_summary(now: float | None = None) -> dict[str, Any]:
    """按时间窗 + 按模型 汇总 LLM 调用成本(读 cost_records)。

    窗口:today(本地自然日 0 点起)/ last_7d / last_30d / total。
    ``now`` 可注入用于测试;默认取当前时间。
    """
    import datetime

    _ensure_schema()
    db = Database()
    if now is None:
        now = time.time()
    dt = datetime.datetime.fromtimestamp(now)
    midnight = datetime.datetime(dt.year, dt.month, dt.day).timestamp()
    windows = {
        "today": midnight,
        "last_7d": now - 7 * 86400,
        "last_30d": now - 30 * 86400,
        "total": 0.0,
    }

    # 多次 SELECT 必须在同一 transaction 内, 保证读一致性。
    with db.transaction() as conn:
        def _agg(since: float) -> dict:
            row = conn.execute(
                "SELECT COUNT(*) AS calls, COALESCE(SUM(cost_usd),0) AS cost, "
                "COALESCE(SUM(input_tokens),0) AS inp, COALESCE(SUM(output_tokens),0) AS outp "
                "FROM cost_records WHERE created_at >= ?",
                (since,),
            ).fetchone()
            return {
                "calls": row["calls"] or 0,
                "cost_usd": round(row["cost"] or 0, 4),
                "input_tokens": row["inp"] or 0,
                "output_tokens": row["outp"] or 0,
            }

        by_model = []
        for r in conn.execute(
            "SELECT model, vendor, COUNT(*) AS calls, COALESCE(SUM(cost_usd),0) AS cost, "
            "COALESCE(SUM(input_tokens),0) AS inp, COALESCE(SUM(output_tokens),0) AS outp "
            "FROM cost_records GROUP BY model, vendor ORDER BY cost DESC"
        ).fetchall():
            by_model.append(
                {
                    "model": r["model"],
                    "vendor": r["vendor"],
                    "calls": r["calls"] or 0,
                    "cost_usd": round(r["cost"] or 0, 4),
                    "input_tokens": r["inp"] or 0,
                    "output_tokens": r["outp"] or 0,
                }
            )

        agg_windows = {k: _agg(since) for k, since in windows.items()}

    return {
        "windows": agg_windows,
        "by_model": by_model,
        "as_of": now,
    }


def get_diagnostics_summary() -> dict[str, Any]:
    """汇总诊断统计。"""
    _ensure_schema()
    db = Database()
    # 多次 SELECT 必须在同一 transaction 内, 保证读一致性。
    with db.transaction() as conn:
        # 工具调用统计
        tc_row = conn.execute("SELECT COUNT(*) as total FROM tool_calls").fetchone()
        tc_errors = conn.execute(
            "SELECT COUNT(*) as cnt FROM tool_calls WHERE status != 'ok'"
        ).fetchone()
        tc_avg = conn.execute(
            "SELECT AVG(latency_ms) as avg_lat FROM tool_calls WHERE latency_ms > 0"
        ).fetchone()

        # 成本统计
        cost_row = conn.execute(
            "SELECT COUNT(*) as total, SUM(cost_usd) as total_cost, "
            "SUM(input_tokens) as total_input, SUM(output_tokens) as total_output FROM cost_records"
        ).fetchone()

        # 健康统计
        health_row = conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok_count, "
            "SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_count "
            "FROM source_fetch_logs"
        ).fetchone()

    return {
        "tool_calls": {
            "total": tc_row["total"] if tc_row else 0,
            "errors": tc_errors["cnt"] if tc_errors else 0,
            "avg_latency_ms": round(tc_avg["avg_lat"] or 0, 1) if tc_avg else 0,
        },
        "cost_records": {
            "total": cost_row["total"] if cost_row else 0,
            "total_cost_usd": round(cost_row["total_cost"] or 0, 4) if cost_row else 0,
            "total_input_tokens": cost_row["total_input"] or 0 if cost_row else 0,
            "total_output_tokens": cost_row["total_output"] or 0 if cost_row else 0,
        },
        "health": {
            "total_checks": health_row["total"] if health_row else 0,
            "ok": health_row["ok_count"] if health_row else 0,
            "errors": health_row["error_count"] if health_row else 0,
        },
    }
