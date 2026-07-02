"""行情存储层 — 管理 price_bars 表，提供标准化的 K 线 CRUD"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.storage.db import Database


_schema_ensured = False


def _ensure_schema() -> None:
    """建表/补列(幂等)。包进进程级 DB 锁, 避免与后台 ingestion 线程并发写时撞锁。

    首次补齐 fetched_at 列后置 _schema_ensured=True, 后续高频读路径直接跳过 —
    ALTER TABLE 即便 try/except 吞错也占 DB 锁 + DDL 开销, price_store 是最高频读路径。
    """
    global _schema_ensured
    if _schema_ensured:
        return
    db = Database()
    with db.transaction() as conn:
        # 补齐 fetched_at 列
        try:
            conn.execute("ALTER TABLE price_bars ADD COLUMN fetched_at REAL DEFAULT 0")
        except Exception:
            pass
        conn.commit()
    _schema_ensured = True


# ============== Symbol 标准化 ==============


def normalize_symbol(symbol: str) -> str:
    """统一股票代码为纯 6 位数字。

    处理各种格式：
    - 600519 → 600519
    - 600519.SH → 600519
    - sh.600519 → 600519
    - SH600519 → 600519
    - 600519.SHQ → 600519
    """
    if not symbol:
        return ""
    s = symbol.strip().upper()
    # 去除常见后缀
    for suffix in (".SH", ".SZ", ".BJ", ".SS", ".HK", ".US"):
        s = s.replace(suffix, "")
    # 去除前缀（如 SH, SZ）
    s = re.sub(r"^(SH|SZ|BJ)", "", s)
    # 只保留数字
    digits = re.sub(r"\D", "", s)
    # A 股 6 位，港股 5 位，美股可变
    if len(digits) >= 5:
        return digits[:6] if len(digits) >= 6 else digits
    return digits


def get_market(symbol: str) -> str:
    """根据代码推断市场。"""
    code = normalize_symbol(symbol)
    if not code:
        return "CN"
    if len(code) == 5:
        return "HK"  # 港股（5 位数字）
    if code.startswith("6"):
        return "CN"  # 上交所
    if code.startswith(("0", "3")):
        return "CN"  # 深交所
    if code.startswith(("4", "8")):
        return "CN"  # 北交所
    return "US"


# ============== 数据质量校验 ==============


def validate_price_bar(bar: dict) -> tuple[bool, str]:
    """校验 K 线数据质量。

    Returns:
        (is_valid, error_message)
    """
    op = bar.get("open", 0)
    hi = bar.get("high", 0)
    lo = bar.get("low", 0)
    cl = bar.get("close", 0)
    vol = bar.get("volume", 0)

    if op <= 0 or hi <= 0 or lo <= 0 or cl <= 0:
        return False, "OHLC 必须大于 0"
    if hi < lo:
        return False, f"最高价({hi})不能低于最低价({lo})"
    if hi < op or hi < cl:
        return False, f"最高价({hi})不能低于开盘/收盘价"
    if lo > op or lo > cl:
        return False, f"最低价({lo})不能高于开盘/收盘价"
    if vol < 0:
        return False, f"成交量({vol})不能为负"

    return True, ""


# ============== Price Bar CRUD ==============


def save_price_bar(bar: dict) -> None:
    """写入单条 K 线（INSERT OR REPLACE）。"""
    _ensure_schema()
    symbol = normalize_symbol(bar.get("symbol", ""))
    db = Database()
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO price_bars "
            "(symbol, date, market, frequency, open, high, low, close, "
            "volume, amount, turnover, amplitude, change_pct, adjust, source, fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                symbol,
                bar.get("date", ""),
                bar.get("market", get_market(symbol)),
                bar.get("frequency", "1d"),
                bar.get("open", 0),
                bar.get("high", 0),
                bar.get("low", 0),
                bar.get("close", 0),
                bar.get("volume", 0),
                bar.get("amount", 0),
                bar.get("turnover", 0),
                bar.get("amplitude", 0),
                bar.get("change_pct", 0),
                bar.get("adjust", ""),
                bar.get("source", "akshare"),
                bar.get("fetched_at", time.time()),
            ),
        )
        conn.commit()


def save_price_bars(bars: list[dict]) -> int:
    """批量写入 K 线，返回写入数量。"""
    _ensure_schema()
    db = Database()
    count = 0
    with db.transaction() as conn:
        for bar in bars:
            symbol = normalize_symbol(bar.get("symbol", ""))
            conn.execute(
                "INSERT OR REPLACE INTO price_bars "
                "(symbol, date, market, frequency, open, high, low, close, "
                "volume, amount, turnover, amplitude, change_pct, adjust, source, fetched_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    symbol,
                    bar.get("date", ""),
                    bar.get("market", get_market(symbol)),
                    bar.get("frequency", "1d"),
                    bar.get("open", 0),
                    bar.get("high", 0),
                    bar.get("low", 0),
                    bar.get("close", 0),
                    bar.get("volume", 0),
                    bar.get("amount", 0),
                    bar.get("turnover", 0),
                    bar.get("amplitude", 0),
                    bar.get("change_pct", 0),
                    bar.get("adjust", ""),
                    bar.get("source", "akshare"),
                    bar.get("fetched_at", time.time()),
                ),
            )
            count += 1
        conn.commit()
    return count


def get_prices(
    symbol: str,
    frequency: str = "1d",
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 250,
    include_incompatible: bool = False,
) -> list[dict[str, Any]]:
    """查询 K 线数据。"""
    _ensure_schema()
    sym = normalize_symbol(symbol)
    db = Database()
    with db.transaction() as conn:
        conditions = ["symbol=?", "frequency=?"]
        params: list[Any] = [sym, frequency]

        if start_date:
            conditions.append("date>=?")
            params.append(start_date)
        if end_date:
            conditions.append("date<=?")
            params.append(end_date)

        where = " AND ".join(conditions)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM price_bars WHERE {where} ORDER BY date DESC LIMIT ?",
            params,
        ).fetchall()
        bars = [_row_to_bar(r) for r in rows]
    # 过滤是纯函数, 在锁外做不占用 DB 锁
    if include_incompatible or frequency == "intraday":
        return bars

    from backend.price_quality import filter_incompatible_price_bars

    return filter_incompatible_price_bars(bars)


def get_latest_price(symbol: str) -> Optional[dict[str, Any]]:
    """获取最新一条 K 线。"""
    _ensure_schema()
    sym = normalize_symbol(symbol)
    db = Database()
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM price_bars WHERE symbol=? AND frequency='1d' "
            "ORDER BY date DESC LIMIT 20",
            (sym,),
        ).fetchall()
        bars = [_row_to_bar(row) for row in rows]
        if bars:
            from backend.price_quality import filter_incompatible_price_bars

            filtered = filter_incompatible_price_bars(bars)
            if filtered:
                return filtered[0]

        row = conn.execute(
            "SELECT * FROM price_bars WHERE symbol=? ORDER BY date DESC LIMIT 1",
            (sym,),
        ).fetchone()
        return _row_to_bar(row) if row else None


def delete_prices(symbol: str, frequency: Optional[str] = None) -> int:
    """删除 K 线数据。"""
    _ensure_schema()
    sym = normalize_symbol(symbol)
    db = Database()
    with db.transaction() as conn:
        if frequency:
            cursor = conn.execute(
                "DELETE FROM price_bars WHERE symbol=? AND frequency=?",
                (sym, frequency),
            )
        else:
            cursor = conn.execute("DELETE FROM price_bars WHERE symbol=?", (sym,))
        conn.commit()
        return cursor.rowcount


def _row_to_bar(row) -> dict[str, Any]:
    return {
        "symbol": row["symbol"],
        "date": row["date"],
        "market": row["market"] or "CN",
        "frequency": row["frequency"] or "1d",
        "open": row["open"] or 0,
        "high": row["high"] or 0,
        "low": row["low"] or 0,
        "close": row["close"] or 0,
        "volume": row["volume"] or 0,
        "amount": row["amount"] or 0,
        "turnover": row["turnover"] or 0,
        "amplitude": row["amplitude"] or 0,
        "change_pct": row["change_pct"] or 0,
        "adjust": row["adjust"] or "",
        "source": row["source"] or "akshare",
        "fetched_at": row["fetched_at"] or 0,
    }
