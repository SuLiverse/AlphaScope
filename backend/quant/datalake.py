"""DuckDB / Parquet 数据湖 — 把行情统一物化为列存, 支撑跨标的批量扫描 / 选股 / 因子(v1.9.20)。

动机
----
三份战略报告都点名「DuckDB/Parquet 数据湖」:把零散的逐标的行情沉淀成**列式数据湖**,
就能用一条 SQL 跨上千标的批量扫描(批量选股、因子计算的底座), 而不必逐个取数。

设计
----
- **零硬依赖、失败安全降级**:`duckdb` 用 import-guard 包裹。**没装 duckdb 整个应用照常运行**,
  数据湖能力只是报告 `available=False`(与项目「诚实降级、绝不伪造成功」一致), 装上即生效。
- **纯函数可单测**:bar 规范化、选股 SQL 构造(字段/操作符白名单防注入)、只读 SQL 守卫
  都是纯函数, 不依赖 duckdb 即可测;真正的 parquet 往返用 `importorskip("duckdb")` 按需测。
- **列存物化**:每个标的写一个 `data/datalake/prices/<symbol>.parquet`;读取用 `read_parquet(glob)`
  联合扫描。写入只在显式「入湖」时发生。
- **只读查询守卫**:对外暴露的 SQL 查询只允许 SELECT/WITH, 拒绝任何 DDL/DML, 防误写/注入。
- **合规**:数据湖只是历史行情的列式副本 + 批量历史筛选, 描述「过去满足条件的标的」,
  既不预测也不构成选股建议;筛选结果均附免责。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 选股/查询可用的列白名单(防 SQL 注入:只允许这些标识符出现)。
_NUMERIC_COLUMNS = ("open", "high", "low", "close", "volume", "amount")
_ALL_COLUMNS = ("symbol", "date") + _NUMERIC_COLUMNS
_OPERATORS = {">", "<", ">=", "<=", "=", "==", "!=", "<>"}
_OP_ALIASES = {"==": "=", "!=": "<>"}

# 禁止出现在只读查询里的关键字(子串匹配;词边界敏感的关键字见 _FORBIDDEN_KW_RE)。
_FORBIDDEN_SQL = (
    "insert",
    "update",
    "delete",
    "drop",
    "create",
    "alter",
    "attach",
    "detach",
    "copy",
    "pragma",
    "export",
    "import",
    "install",
    "load",
    "call",
)

# 需要词边界精确匹配的关键字:裸 "set " 带空格会被 tab/换行绕过, 也易误判列名/别名。
_FORBIDDEN_KW_RE = re.compile(r"\b(set)\b", re.IGNORECASE)

# DuckDB 文件读取表函数 —— 防止用户 SQL 用 read_csv_auto('C:/...') 等读取服务器任意文件
# (代码内部受控的 read_parquet 调用在 query() 建视图, 不经过 is_select_only, 不受影响)。
_FORBIDDEN_FUNC_RE = re.compile(
    r"\b(read_csv_auto|read_csv|read_json_auto|read_json|read_parquet"
    r"|read_blob_auto|read_blob|read_text_auto|read_text)\s*\(",
    re.IGNORECASE,
)


# ----------------------------- 纯函数(无需 duckdb, 可单测) -----------------------------


def _to_float(value: Any) -> float:
    try:
        f = float(str(value).replace(",", "").strip())
        return f if f == f else 0.0
    except (TypeError, ValueError):
        return 0.0


def normalize_bars(bars: List[Dict[str, Any]], symbol: str) -> List[Dict[str, Any]]:
    """把任意来源的 bar 规范成统一列(symbol/date/OHLCV/amount), 去重(按日期保后者)升序。纯函数。"""
    by_date: Dict[str, Dict[str, Any]] = {}
    for b in bars or []:
        if not isinstance(b, dict):
            continue
        date = str(b.get("date") or "").strip()[:10]
        if not date:
            continue
        close = _to_float(b.get("close"))
        if close <= 0:
            continue
        by_date[date] = {
            "symbol": str(b.get("symbol") or symbol or "").strip(),
            "date": date,
            "open": _to_float(b.get("open")),
            "high": _to_float(b.get("high")),
            "low": _to_float(b.get("low")),
            "close": close,
            "volume": _to_float(b.get("volume")),
            "amount": _to_float(b.get("amount")),
        }
    return [by_date[d] for d in sorted(by_date)]


def _norm_op(op: str) -> Optional[str]:
    op = str(op or "").strip()
    if op not in _OPERATORS:
        return None
    return _OP_ALIASES.get(op, op)


def build_screen_sql(filters: List[Dict[str, Any]]) -> Tuple[str, List[Any]]:
    """从筛选规格构造 **WHERE 子句 + 参数**(纯函数, 字段/操作符白名单防注入)。

    ``filters`` = [{field, op, value}, ...]。非法字段/操作符的条目被跳过。
    无有效条件返回 ("1=1", [])。值用占位符 ? 绑定, 不拼进 SQL。
    """
    clauses: List[str] = []
    params: List[Any] = []
    for f in filters or []:
        if not isinstance(f, dict):
            continue
        field = str(f.get("field") or "").strip().lower()
        op = _norm_op(f.get("op"))
        if field not in _NUMERIC_COLUMNS or op is None:
            continue
        try:
            value = float(f.get("value"))
        except (TypeError, ValueError):
            continue
        clauses.append(f"{field} {op} ?")
        params.append(value)
    if not clauses:
        return "1=1", []
    return " AND ".join(clauses), params


def is_select_only(sql: str) -> bool:
    """只读守卫:仅允许单条 SELECT/WITH 查询, 拒绝任何 DDL/DML 与多语句。

    额外拦截 DuckDB 文件读取表函数(read_csv_auto/read_parquet 等), 防止用户 SQL 读取服务器任意文件。
    纯函数。
    """
    s = str(sql or "").strip().rstrip(";").strip()
    if not s:
        return False
    low = s.lower()
    if not (low.startswith("select") or low.startswith("with")):
        return False
    if ";" in s:  # 去掉尾分号后仍有 → 多语句
        return False
    if any(kw in low for kw in _FORBIDDEN_SQL):
        return False
    if _FORBIDDEN_KW_RE.search(s):
        return False
    if _FORBIDDEN_FUNC_RE.search(s):
        return False
    return True


# ----------------------------- 目录 / duckdb 网关 -----------------------------


def is_available() -> bool:
    """duckdb 是否可用(未安装则数据湖能力优雅降级)。"""
    try:
        import duckdb  # noqa: F401

        return True
    except Exception:
        return False


def _lake_dir() -> Path:
    try:
        from backend.project_paths import DATA_DIR

        d = DATA_DIR / "datalake" / "prices"
    except Exception:
        d = Path("data/datalake/prices")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _parquet_path(symbol: str) -> Path:
    safe = "".join(ch for ch in str(symbol).strip() if ch.isalnum() or ch in ("_", ".", "-"))
    return _lake_dir() / f"{safe or 'unknown'}.parquet"


def _parquet_files() -> List[Path]:
    return sorted(_lake_dir().glob("*.parquet"))


def _glob_str() -> str:
    return str(_lake_dir() / "*.parquet").replace("\\", "/")


def _degraded(reason: str = "duckdb 未安装") -> Dict[str, Any]:
    return {"ok": False, "available": False, "degraded": True, "reason": reason}


# ----------------------------- 入湖 / 查询(duckdb-gated, 失败安全) -----------------------------


def ingest_prices(symbol: str, bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把某标的的 bars 规范化后写入列存 parquet(每标的一个文件, 覆盖式)。失败安全。"""
    if not is_available():
        return _degraded()
    rows = normalize_bars(bars, symbol)
    if not rows:
        return {"ok": False, "symbol": symbol, "rows": 0, "reason": "无有效行情"}
    try:
        import duckdb
        import pandas as pd

        df = pd.DataFrame(rows)
        path = str(_parquet_path(symbol)).replace("\\", "/")
        con = duckdb.connect()
        try:
            con.register("df", df)
            con.execute(f"COPY (SELECT * FROM df ORDER BY date) TO '{path}' (FORMAT PARQUET)")
        finally:
            con.close()
        return {"ok": True, "symbol": str(symbol), "rows": len(rows), "path": path}
    except Exception as e:  # noqa: BLE001 - 失败安全
        logger.warning("[datalake] 入湖失败 %s: %s", symbol, e)
        return {"ok": False, "symbol": symbol, "rows": 0, "reason": str(e)}


def ingest_from_provider(
    symbols: List[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """从本地价格面取数并入湖(逐标的失败安全, 单只失败不影响其余)。"""
    if not is_available():
        return _degraded()
    try:
        from backend.price_store import get_prices, normalize_symbol
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": f"价格面不可用: {e}", "results": []}

    results: List[Dict[str, Any]] = []
    for raw_sym in symbols or []:
        sym = str(raw_sym).strip()
        if not sym:
            continue
        try:
            norm = normalize_symbol(sym) or sym
            bars = (
                get_prices(
                    norm,
                    start_date=start_date,
                    end_date=end_date,
                    limit=limit,
                    include_incompatible=True,
                )
                or []
            )
            results.append(ingest_prices(norm, bars))
        except Exception as e:  # noqa: BLE001
            results.append({"ok": False, "symbol": sym, "rows": 0, "reason": str(e)})
    ok = sum(1 for r in results if r.get("ok"))
    return {"ok": ok > 0, "ingested": ok, "requested": len(results), "results": results}


def query(sql: str, limit: int = 500) -> Dict[str, Any]:
    """对数据湖跑**只读** SQL(表名用 `prices`)。失败安全, 非 SELECT 拒绝。"""
    if not is_available():
        return _degraded()
    if not is_select_only(sql):
        return {"ok": False, "reason": "仅允许单条 SELECT/WITH 只读查询"}
    if not _parquet_files():
        return {
            "ok": True,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "note": "数据湖为空, 请先入湖",
        }
    try:
        import duckdb

        con = duckdb.connect()
        try:
            con.execute(f"CREATE VIEW prices AS SELECT * FROM read_parquet('{_glob_str()}')")
            lim = max(1, min(5000, int(limit) if limit else 500))
            cur = con.execute(f"SELECT * FROM ({sql.rstrip(';')}) AS _q LIMIT {lim}")
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()
        return {"ok": True, "columns": cols, "rows": rows, "row_count": len(rows)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)}


def _latest_cte() -> str:
    """构造「每标的最新一根 bar」的 CTE(读 parquet glob)。"""
    return (
        f"WITH ranked AS (SELECT *, row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS _rn "
        f"FROM read_parquet('{_glob_str()}')) "
    )


def screen(
    filters: List[Dict[str, Any]],
    order_by: str = "close",
    descending: bool = True,
    limit: int = 100,
) -> Dict[str, Any]:
    """跨标的批量筛选:对每只「最新一根 bar」套用筛选条件, 返回命中标的。失败安全。

    纯历史筛选(描述过去满足条件的标的), 不预测、不构成选股建议。
    """
    if not is_available():
        return _degraded()
    if not _parquet_files():
        return {"ok": True, "matched": 0, "rows": [], "note": "数据湖为空, 请先入湖"}
    where, params = build_screen_sql(filters)
    order_col = order_by if order_by in _ALL_COLUMNS else "close"
    direction = "DESC" if descending else "ASC"
    lim = max(1, min(2000, int(limit) if limit else 100))
    try:
        import duckdb

        con = duckdb.connect()
        try:
            sql = (
                f"{_latest_cte()}"
                f"SELECT symbol, date, open, high, low, close, volume, amount "
                f"FROM ranked WHERE _rn = 1 AND ({where}) "
                f"ORDER BY {order_col} {direction} LIMIT {lim}"
            )
            cur = con.execute(sql, params)
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()
        return {
            "ok": True,
            "matched": len(rows),
            "rows": rows,
            "filters": filters,
            "disclaimer": "仅基于历史行情的批量筛选, 描述过去满足条件的标的, 不预测未来、不构成选股建议。",
        }
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)}


def latest_snapshot(limit: int = 500) -> Dict[str, Any]:
    """每标的最新一根 bar 的快照(批量选股的底座视图)。失败安全。"""
    if not is_available():
        return _degraded()
    if not _parquet_files():
        return {"ok": True, "rows": [], "row_count": 0}
    try:
        import duckdb

        con = duckdb.connect()
        try:
            lim = max(1, min(5000, int(limit) if limit else 500))
            cur = con.execute(
                f"{_latest_cte()}SELECT symbol, date, open, high, low, close, volume, amount "
                f"FROM ranked WHERE _rn = 1 ORDER BY symbol LIMIT {lim}"
            )
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            con.close()
        return {"ok": True, "rows": rows, "row_count": len(rows)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "reason": str(e)}


def stats() -> Dict[str, Any]:
    """数据湖概览:可用性 / 标的数 / 行数 / 日期范围 / 占用字节。失败安全。"""
    available = is_available()
    files = _parquet_files()
    size = 0
    for f in files:
        try:
            size += f.stat().st_size
        except OSError:
            pass
    base = {
        "available": available,
        "symbol_count": len(files),
        "size_bytes": size,
        "row_count": 0,
        "date_range": [],
        "disclaimer": "数据湖为历史行情的列式副本, 仅供批量历史查询/筛选, 不预测不构成建议。",
    }
    if not available or not files:
        return base
    try:
        import duckdb

        con = duckdb.connect()
        try:
            r = con.execute(
                f"SELECT COUNT(*) AS c, MIN(date) AS lo, MAX(date) AS hi FROM read_parquet('{_glob_str()}')"
            ).fetchone()
            base["row_count"] = int(r[0]) if r and r[0] is not None else 0
            base["date_range"] = [r[1], r[2]] if r and r[1] else []
        finally:
            con.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("[datalake] stats 失败: %s", e)
    return base


def list_symbols() -> List[str]:
    """已入湖的标的列表(按文件名)。"""
    return [f.stem for f in _parquet_files()]


def clear_symbol(symbol: str) -> bool:
    """删除某标的的湖文件。失败返回 False。"""
    try:
        p = _parquet_path(symbol)
        if p.exists():
            p.unlink()
            return True
        return False
    except Exception:
        return False


def clear_all() -> int:
    """清空数据湖, 返回删除文件数。失败返回已删数。"""
    n = 0
    for f in _parquet_files():
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n
