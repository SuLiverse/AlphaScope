"""研究记忆 research_memory — 把每次 Agent 分析的**结论快照**落 SQLite,追踪同一只股票的研究随时间变化。

动机:`/api/analysis/run` 每跑一次都产出一个结论(买入/卖出/观望 + 置信度 + 多空裁决 + 风控 + 数据核验),
但跑完即走、无从回看。本模块把每次分析抽成一份**紧凑结论快照**落到独立表 `research_memory`,
于是同一只股票可以查看「上周看多、本周转观望」这类**结论随时间的变化轨迹**,辅助复盘。

设计(完全对齐 [[experiment_store]] 的风格):
* **自包含**:懒创建自己的表(不改 `db._create_tables`),复用同一 SQLite 连接(单例)。
* **失败安全**:所有读写吞掉异常并返回中性值(None/[]/{}),持久化失败绝不影响分析本身
  ——与项目「诚实降级、绝不伪造成功」一致(写失败就是没存,不假装存了)。
* **纯函数可单测**:快照抽取 / 变化检测 / 历史汇总都是纯函数,DB 层只是薄包装。
* **只增不替**:是分析流程的旁路记录,不改变任何既有返回。

合规:仅**记录与回看历史研究结论的变化**,描述「过去这样判断过」,既不预测未来也不构成任何建议;
所有快照沿用分析当时已带的免责语义。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Optional

_TABLE = "research_memory"
_write_lock = threading.Lock()
_ensured = False

# 每只股票最多保留的快照数(个人工具,够复盘即可)。
_KEEP_PER_SYMBOL = 200

# 信号归一(分析侧已是中文,但兼容英文/近义词,保证变化检测稳定)。
_BUY = {"买入", "buy", "看多", "增持", "bullish", "强烈买入"}
_SELL = {"卖出", "sell", "看空", "减持", "bearish", "强烈卖出"}
_HOLD = {"观望", "持有", "hold", "中性", "neutral", "持有观望"}

# 信号方向序:用于判断「转积极 / 转谨慎」。
_RANK = {"卖出": -1, "观望": 0, "买入": 1}


def _db():
    from backend.storage.db import Database

    return Database()


def _ensure_table() -> None:
    """懒创建研究记忆表 + 索引(幂等)。"""
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
                    snapshot_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT,
                    created_at TEXT NOT NULL,
                    signal TEXT,
                    confidence REAL,
                    buy INTEGER,
                    sell INTEGER,
                    hold INTEGER,
                    consensus TEXT,
                    consensus_score REAL,
                    divergence TEXT,
                    risk_vetoed INTEGER,
                    data_status TEXT,
                    close REAL,
                    mode TEXT,
                    payload TEXT
                )
                """
            )
            conn.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_symbol ON {_TABLE}(symbol, created_at)"
            )
            conn.commit()
        _ensured = True


# ----------------------------- 纯函数(可单测) -----------------------------


def _num(v: Any, default: float = 0.0) -> float:
    """稳健转 float,失败回退默认。"""
    try:
        if v is None:
            return default
        f = float(v)
        return f if f == f else default  # 排除 NaN
    except (TypeError, ValueError):
        return default


def _norm_signal(s: Any) -> str:
    """把任意信号文本归一到 买入/卖出/观望;无法识别保留原文或「未知」。"""
    raw = str(s or "").strip()
    if not raw:
        return "未知"
    low = raw.lower()
    if raw in _BUY or low in _BUY:
        return "买入"
    if raw in _SELL or low in _SELL:
        return "卖出"
    if raw in _HOLD or low in _HOLD:
        return "观望"
    return raw


def _change_direction(a: str, b: str) -> str:
    """两个信号之间的变化方向(纯函数)。"""
    ra, rb = _RANK.get(a), _RANK.get(b)
    if ra is None or rb is None:
        return "调整"
    if rb > ra:
        return "转积极"
    if rb < ra:
        return "转谨慎"
    return "横盘"


def build_snapshot(
    symbol: str,
    name: str,
    result: dict[str, Any],
    stock_data: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """从一次分析结果抽**紧凑结论快照**(纯函数,失败安全)。

    返回的 dict 既用于落库的结构化列,也整体存进 payload。
    """
    result = result if isinstance(result, dict) else {}
    stock_data = stock_data if isinstance(stock_data, dict) else {}
    now = now or datetime.now()

    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    debate = result.get("debate") if isinstance(result.get("debate"), dict) else {}
    risk_gate = (
        result.get("risk_gate") if isinstance(result.get("risk_gate"), dict) else {}
    )
    dv = (
        result.get("data_verification")
        if isinstance(result.get("data_verification"), dict)
        else {}
    )

    signal = _norm_signal(summary.get("final"))
    sid = f"{symbol}-{now.strftime('%Y%m%d%H%M%S%f')}"
    return {
        "snapshot_id": sid,
        "symbol": str(symbol or ""),
        "name": str(name or ""),
        "created_at": now.isoformat(),
        "signal": signal,
        "confidence": _num(summary.get("avg_confidence")),
        "buy": int(_num(summary.get("buy"))),
        "sell": int(_num(summary.get("sell"))),
        "hold": int(_num(summary.get("hold"))),
        "consensus": str(debate.get("consensus") or ""),
        "consensus_score": _num(debate.get("consensus_score")),
        "divergence": str(debate.get("divergence_level") or ""),
        "risk_vetoed": bool(risk_gate.get("vetoed")),
        "data_status": str(dv.get("overall") or ""),
        "close": _num(stock_data.get("close")),
        "mode": str(result.get("mode") or result.get("mode_name") or ""),
    }


def _is_meaningful(snap: dict[str, Any]) -> bool:
    """是否值得记忆:有信号或有任何 Agent 计数或有裁决,过滤空跑。"""
    if not isinstance(snap, dict):
        return False
    if snap.get("signal") and snap.get("signal") != "未知":
        return True
    if (snap.get("buy") or 0) or (snap.get("sell") or 0) or (snap.get("hold") or 0):
        return True
    return bool(snap.get("consensus"))


def compute_changes(snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给定**按时间升序**的快照,找出 signal 发生变化的转折点(纯函数)。

    每个转折给出 from/to 信号、对应日期、置信度与方向(转积极/转谨慎/横盘/调整)。
    """
    out: list[dict[str, Any]] = []
    prev: Optional[dict[str, Any]] = None
    for s in snapshots or []:
        if not isinstance(s, dict):
            continue
        sig = _norm_signal(s.get("signal"))
        if prev is not None and sig != prev["sig"]:
            out.append(
                {
                    "from": prev["sig"],
                    "to": sig,
                    "from_date": prev["date"],
                    "to_date": str(s.get("created_at") or ""),
                    "confidence_from": _num(prev["conf"]),
                    "confidence_to": _num(s.get("confidence")),
                    "direction": _change_direction(prev["sig"], sig),
                }
            )
        prev = {
            "sig": sig,
            "date": str(s.get("created_at") or ""),
            "conf": s.get("confidence"),
        }
    return out


def summarize_history(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """对一只股票的历史快照(**升序**)做汇总(纯函数):次数/最新信号/分布/置信度/变化数。"""
    snaps = [s for s in (snapshots or []) if isinstance(s, dict)]
    n = len(snaps)
    if n == 0:
        return {
            "count": 0,
            "latest_signal": "",
            "latest_confidence": 0.0,
            "first_date": "",
            "latest_date": "",
            "signal_distribution": {},
            "change_count": 0,
            "avg_confidence": 0.0,
        }
    dist: dict[str, int] = {}
    confs: list[float] = []
    for s in snaps:
        sig = _norm_signal(s.get("signal"))
        dist[sig] = dist.get(sig, 0) + 1
        c = _num(s.get("confidence"))
        if c:
            confs.append(c)
    changes = compute_changes(snaps)
    latest = snaps[-1]
    return {
        "count": n,
        "latest_signal": _norm_signal(latest.get("signal")),
        "latest_confidence": _num(latest.get("confidence")),
        "first_date": str(snaps[0].get("created_at") or ""),
        "latest_date": str(latest.get("created_at") or ""),
        "signal_distribution": dist,
        "change_count": len(changes),
        "avg_confidence": round(sum(confs) / len(confs), 2) if confs else 0.0,
    }


# ----------------------------- DB 操作(失败安全) -----------------------------


def record_snapshot(
    symbol: str,
    name: str,
    result: dict[str, Any],
    stock_data: Optional[dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """记录一次分析的结论快照。失败安全:出错或空跑返回 None,绝不抛出。"""
    try:
        if not symbol:
            return None
        snap = build_snapshot(symbol, name, result, stock_data, now)
        if not _is_meaningful(snap):
            return None
        _ensure_table()
        with _db().transaction() as conn:
            conn.execute(
                f"""INSERT OR REPLACE INTO {_TABLE}
                    (snapshot_id, symbol, name, created_at, signal, confidence,
                     buy, sell, hold, consensus, consensus_score, divergence,
                     risk_vetoed, data_status, close, mode, payload)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snap["snapshot_id"],
                    snap["symbol"],
                    snap["name"],
                    snap["created_at"],
                    snap["signal"],
                    snap["confidence"],
                    snap["buy"],
                    snap["sell"],
                    snap["hold"],
                    snap["consensus"],
                    snap["consensus_score"],
                    snap["divergence"],
                    1 if snap["risk_vetoed"] else 0,
                    snap["data_status"],
                    snap["close"],
                    snap["mode"],
                    json.dumps(snap, ensure_ascii=False),
                ),
            )
            conn.commit()
        # _prune_symbol 会再加锁, 必须在事务外调用(_db_lock 不可重入)。
        _prune_symbol(snap["symbol"])
        return snap["snapshot_id"]
    except Exception:
        return None


def _row_to_snapshot(r: Any) -> dict[str, Any]:
    """把一行还原成快照 dict(优先用 payload,缺失时退回结构化列)。"""
    try:
        if r["payload"]:
            return json.loads(r["payload"])
    except Exception:
        pass
    return {
        "snapshot_id": r["snapshot_id"],
        "symbol": r["symbol"],
        "name": r["name"],
        "created_at": r["created_at"],
        "signal": r["signal"],
        "confidence": r["confidence"],
    }


def list_symbols(limit: int = 100) -> list[dict[str, Any]]:
    """列举有研究记忆的股票(按最近一次分析倒序),每只带次数/最新信号/置信度。失败返回 []。"""
    try:
        _ensure_table()
        with _db().transaction() as conn:
            rows = conn.execute(
                f"SELECT symbol, name, created_at, signal, confidence "
                f"FROM {_TABLE} ORDER BY created_at DESC"
            ).fetchall()
        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            sym = r["symbol"]
            if sym not in agg:
                agg[sym] = {
                    "symbol": sym,
                    "name": r["name"] or "",
                    "count": 0,
                    "latest_date": r["created_at"],
                    "latest_signal": _norm_signal(r["signal"]),
                    "latest_confidence": _num(r["confidence"]),
                }
            agg[sym]["count"] += 1
        out = list(agg.values())
        return out[: max(1, min(500, int(limit) if limit else 100))]
    except Exception:
        return []


def get_history(symbol: str, limit: int = 200) -> list[dict[str, Any]]:
    """取某股票的快照(**时间倒序**,新在前),供表格展示。失败返回 []。"""
    try:
        _ensure_table()
        with _db().transaction() as conn:
            rows = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE symbol = ? ORDER BY created_at DESC LIMIT ?",
                (symbol, max(1, min(500, int(limit) if limit else 200))),
            ).fetchall()
        return [_row_to_snapshot(r) for r in rows]
    except Exception:
        return []


def get_timeline(symbol: str, limit: int = 200) -> dict[str, Any]:
    """取某股票的完整时间线:升序快照 + 变化转折 + 汇总。失败返回空结构。"""
    try:
        snaps_desc = get_history(symbol, limit)
        snaps_asc = list(reversed(snaps_desc))
        return {
            "symbol": symbol,
            "name": (snaps_asc[-1].get("name") if snaps_asc else "") or "",
            "snapshots": snaps_asc,
            "changes": compute_changes(snaps_asc),
            "summary": summarize_history(snaps_asc),
        }
    except Exception:
        return {
            "symbol": symbol,
            "name": "",
            "snapshots": [],
            "changes": [],
            "summary": summarize_history([]),
        }


def delete_snapshot(snapshot_id: str) -> bool:
    """删除单条快照。失败返回 False。"""
    try:
        _ensure_table()
        with _db().transaction() as conn:
            cur = conn.execute(
                f"DELETE FROM {_TABLE} WHERE snapshot_id = ?", (snapshot_id,)
            )
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def delete_symbol(symbol: str) -> int:
    """删除某股票的全部记忆,返回删除条数。失败返回 0。"""
    try:
        _ensure_table()
        with _db().transaction() as conn:
            cur = conn.execute(f"DELETE FROM {_TABLE} WHERE symbol = ?", (symbol,))
            conn.commit()
            return int(cur.rowcount or 0)
    except Exception:
        return 0


def count() -> int:
    """快照总数。失败返回 0。"""
    try:
        _ensure_table()
        with _db().transaction() as conn:
            r = conn.execute(f"SELECT COUNT(*) AS c FROM {_TABLE}").fetchone()
        return int(r["c"]) if r else 0
    except Exception:
        return 0


def _prune_symbol(symbol: str, keep: int = _KEEP_PER_SYMBOL) -> None:
    """每只股票只保留最近 keep 条,防止无限增长。失败静默。"""
    try:
        with _db().transaction() as conn:
            conn.execute(
                f"""DELETE FROM {_TABLE} WHERE symbol = ? AND snapshot_id NOT IN (
                        SELECT snapshot_id FROM {_TABLE} WHERE symbol = ?
                        ORDER BY created_at DESC LIMIT ?
                    )""",
                (symbol, symbol, keep),
            )
            conn.commit()
    except Exception:
        pass
