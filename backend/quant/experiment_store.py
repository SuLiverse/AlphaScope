"""实验记录持久化 — 把量化运行结果(回测/走查/筹码/策略榜)落 SQLite,跨会话可查可比。

现状:`api/quant.py` 的 `_local_runs` 是内存态,重启即丢。本模块把每次运行的**完整载荷**
落到独立表 `quant_experiments`,提供列举 / 详情 / 删除 / 对比,让历史实验可追溯、可横比。

设计:
* **自包含**:懒创建自己的表(不改 `db._create_tables`),复用同一 SQLite 连接(单例)。
* **失败安全**:所有读写吞掉异常并返回中性值(None/[]/False),持久化失败绝不影响运行本身
  ——与项目「诚实降级、绝不伪造成功」一致(写失败就是没存,不假装存了)。
* **只增不减**:与既有内存态 `_local_runs` 并存,是补充不是替换。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Optional

_TABLE = "quant_experiments"
_write_lock = threading.Lock()
_ensured = False

# 保留最近 N 条实验,避免无限增长(个人工具,够用即可)。
_KEEP = 300


def _db():
    from backend.storage.db import Database

    return Database()


def _ensure_table() -> None:
    """懒创建实验表 + 索引(幂等)。"""
    global _ensured
    if _ensured:
        return
    with _write_lock:
        if _ensured:
            return
        with _db().transaction() as conn:
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE} (
                    run_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    symbol TEXT,
                    strategy_id TEXT,
                    created_at TEXT NOT NULL,
                    summary TEXT,
                    payload TEXT
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_created ON {_TABLE}(created_at)"
            )
            conn.commit()
        _ensured = True


def _summarize(mode: str, payload: dict[str, Any]) -> dict[str, Any]:
    """按运行类型抽一份**紧凑指标摘要**,供列表/对比视图直接用(无需解析完整载荷)。"""
    try:
        if mode == "backtest":
            m = payload.get("metrics", {}) or {}
            return {
                "total_return": m.get("total_return", 0.0),
                "annual_return": m.get("annual_return", 0.0),
                "sharpe_ratio": m.get("sharpe_ratio", 0.0),
                "max_drawdown": m.get("max_drawdown", 0.0),
                "win_rate": m.get("win_rate", 0.0),
                "trade_count": m.get("trade_count", 0),
            }
        if mode == "walk_forward":
            agg = payload.get("aggregate", {}) or {}
            return {
                "n_windows": payload.get("n_windows", 0),
                "scheme": payload.get("scheme", ""),
                "consistency_score": agg.get("consistency_score", 0.0),
                "pct_profitable_windows": agg.get("pct_profitable_windows", 0.0),
                "mean_oos_return": agg.get("mean_oos_return", 0.0),
                "robustness": agg.get("robustness", ""),
            }
        if mode == "chip_distribution":
            return {
                "model": payload.get("model", ""),
                "current_price": payload.get("current_price", 0.0),
                "avg_cost": payload.get("avg_cost", 0.0),
                "profit_ratio": payload.get("profit_ratio", 0.0),
                "concentration_90": payload.get("concentration_90", 0.0),
            }
        if mode == "strategy_compare":
            ranking = payload.get("ranking", []) or []
            top = ranking[0] if ranking else {}
            return {
                "evaluated": payload.get("evaluated", len(ranking)),
                "rank_by": payload.get("rank_by", ""),
                "top_strategy": top.get("strategy_id", ""),
                "top_total_return": top.get("total_return", 0.0),
            }
        if mode == "evolution":
            best = payload.get("best", {}) or {}
            return {
                "fitness_metric": payload.get("fitness_metric", ""),
                "generations": payload.get("generations", 0),
                "population_size": payload.get("population_size", 0),
                "best_fitness": best.get("fitness"),
                "improvement": payload.get("improvement"),
                "evaluations": payload.get("evaluations", 0),
            }
    except Exception:
        return {}
    return {}


def save_experiment(payload: dict[str, Any]) -> Optional[str]:
    """持久化一次运行载荷。失败安全:出错返回 None,绝不抛出。"""
    try:
        if not isinstance(payload, dict):
            return None
        _ensure_table()
        mode = str(payload.get("mode") or "unknown")
        run_id = str(
            payload.get("run_id")
            or f"{mode}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        )
        symbol = str(payload.get("symbol") or "")
        strategy_id = str(
            payload.get("strategy_id") or payload.get("strategy_name") or ""
        )
        created_at = str(
            payload.get("finished_at")
            or payload.get("started_at")
            or datetime.now().isoformat()
        )
        summary = _summarize(mode, payload)
        with _db().transaction() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {_TABLE}
                    (run_id, mode, symbol, strategy_id, created_at, summary, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    mode,
                    symbol,
                    strategy_id,
                    created_at,
                    json.dumps(summary, ensure_ascii=False),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            conn.commit()
        # _prune 会再加锁, 必须在事务外调用(_db_lock 不可重入)。
        _prune()
        return run_id
    except Exception:
        return None


def list_experiments(
    limit: int = 50, mode: Optional[str] = None, symbol: Optional[str] = None
) -> list[dict[str, Any]]:
    """按时间倒序列举实验(可按 mode / symbol 过滤)。失败返回 []。"""
    try:
        _ensure_table()
        sql = f"SELECT run_id, mode, symbol, strategy_id, created_at, summary FROM {_TABLE}"
        clauses: list[str] = []
        params: list[Any] = []
        if mode:
            clauses.append("mode = ?")
            params.append(mode)
        if symbol:
            clauses.append("symbol = ?")
            params.append(symbol)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(500, int(limit) if limit else 50)))
        with _db().transaction() as conn:
            rows = conn.execute(sql, params).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "run_id": r["run_id"],
                    "mode": r["mode"],
                    "symbol": r["symbol"],
                    "strategy_id": r["strategy_id"],
                    "created_at": r["created_at"],
                    "summary": json.loads(r["summary"] or "{}"),
                }
            )
        return out
    except Exception:
        return []


def get_experiment(run_id: str) -> Optional[dict[str, Any]]:
    """取一次实验的**完整载荷**。失败/不存在返回 None。"""
    try:
        _ensure_table()
        with _db().transaction() as conn:
            r = conn.execute(
                f"SELECT payload FROM {_TABLE} WHERE run_id = ?", (run_id,)
            ).fetchone()
        return json.loads(r["payload"]) if r and r["payload"] else None
    except Exception:
        return None


def delete_experiment(run_id: str) -> bool:
    """删除一次实验。失败返回 False。"""
    try:
        _ensure_table()
        with _db().transaction() as conn:
            cur = conn.execute(f"DELETE FROM {_TABLE} WHERE run_id = ?", (run_id,))
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def compare_experiments(run_ids: list[str]) -> list[dict[str, Any]]:
    """取若干实验的摘要并排,供横向对比。跳过取不到的 id;失败返回 []。"""
    try:
        out = []
        for rid in run_ids or []:
            exp = get_experiment(rid)
            if not exp:
                continue
            mode = str(exp.get("mode") or "")
            out.append(
                {
                    "run_id": rid,
                    "mode": mode,
                    "symbol": exp.get("symbol", ""),
                    "strategy_id": exp.get("strategy_id")
                    or exp.get("strategy_name", ""),
                    "created_at": exp.get("finished_at") or exp.get("started_at", ""),
                    "summary": _summarize(mode, exp),
                }
            )
        return out
    except Exception:
        return []


def count_experiments() -> int:
    """实验总数。失败返回 0。"""
    try:
        _ensure_table()
        with _db().transaction() as conn:
            r = conn.execute(f"SELECT COUNT(*) AS c FROM {_TABLE}").fetchone()
        return int(r["c"]) if r else 0
    except Exception:
        return 0


def _prune(keep: int = _KEEP) -> None:
    """只保留最近 keep 条,防止无限增长。失败静默。"""
    try:
        with _db().transaction() as conn:
            conn.execute(
                f"""DELETE FROM {_TABLE} WHERE run_id NOT IN (
                        SELECT run_id FROM {_TABLE} ORDER BY created_at DESC LIMIT ?
                    )""",
                (keep,),
            )
            conn.commit()
    except Exception:
        pass
