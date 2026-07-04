"""股票身份解析：把用户输入统一成代码、名称和交易所。"""

from __future__ import annotations

import json
import logging
import queue
import re
import threading
from typing import Any

from backend.price_store import get_market, normalize_symbol
from backend.project_paths import CACHE_DIR

logger = logging.getLogger(__name__)

A_SHARE_NAME_FETCH_TIMEOUT_SECONDS = 2.0
HK_STOCK_NAME_FETCH_TIMEOUT_SECONDS = 3.0
STOCK_NAME_CACHE_FILE = CACHE_DIR / "stock_names_a_share.json"
HK_STOCK_NAME_CACHE_FILE = CACHE_DIR / "stock_names_hk.json"
_A_SHARE_NAME_CACHE: dict[str, str] | None = None
_A_SHARE_NAME_CACHE_LOCK = threading.Lock()
_HK_NAME_CACHE: dict[str, str] | None = None
_HK_NAME_CACHE_LOCK = threading.Lock()

FALLBACK_STOCKS: dict[str, dict[str, str]] = {
    "600519": {"name": "贵州茅台", "exchange": "SH", "market": "CN"},
    "600036": {"name": "招商银行", "exchange": "SH", "market": "CN"},
    "300750": {"name": "宁德时代", "exchange": "SZ", "market": "CN"},
    "600837": {"name": "海通证券", "exchange": "SH", "market": "CN"},
    "301666": {"name": "大普微-UW", "exchange": "SZ", "market": "CN"},
    "00700": {"name": "腾讯控股", "exchange": "HK", "market": "HK"},
}


def infer_exchange(symbol: str) -> str:
    """根据代码推断交易所缩写。"""
    code = normalize_symbol(symbol)
    if not code:
        return ""
    if len(code) == 5:
        return "HK"
    if code.startswith(("60", "68", "90")):
        return "SH"
    if code.startswith(("00", "30", "20")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return get_market(code)


def _clean_query(query: str) -> str:
    return (query or "").strip().upper().replace(" ", "")


def _coerce_a_share_code(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    if len(digits) <= 6:
        return digits.zfill(6)
    return digits[:6]


def _coerce_hk_code(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if raw.endswith(".0"):
        raw = raw[:-2]
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    return digits[:5].zfill(5)


def _clean_name(value: Any) -> str:
    name = str(value or "").strip()
    if name.lower() in {"nan", "none", "null"}:
        return ""
    return name


def _fetch_a_share_code_name():
    import akshare as ak

    return ak.stock_info_a_code_name()


def _load_persisted_a_share_name_map() -> dict[str, str]:
    try:
        if not STOCK_NAME_CACHE_FILE.exists():
            return {}
        raw = json.loads(STOCK_NAME_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {
            _coerce_a_share_code(code): _clean_name(name)
            for code, name in raw.items()
            if _coerce_a_share_code(code) and _clean_name(name)
        }
    except Exception as exc:
        logger.warning("failed to load persisted stock name cache: %s", exc)
        return {}


def _load_persisted_hk_name_map() -> dict[str, str]:
    try:
        if not HK_STOCK_NAME_CACHE_FILE.exists():
            return {}
        raw = json.loads(HK_STOCK_NAME_CACHE_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {
            _coerce_hk_code(code): _clean_name(name)
            for code, name in raw.items()
            if _coerce_hk_code(code) and _clean_name(name)
        }
    except Exception as exc:
        logger.warning("failed to load persisted HK stock name cache: %s", exc)
        return {}


def _save_persisted_a_share_name_map(name_map: dict[str, str]) -> None:
    if not name_map:
        return
    try:
        STOCK_NAME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STOCK_NAME_CACHE_FILE.write_text(
            json.dumps(name_map, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("failed to persist stock name cache: %s", exc)


def _save_persisted_hk_name_map(name_map: dict[str, str]) -> None:
    if not name_map:
        return
    try:
        HK_STOCK_NAME_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        HK_STOCK_NAME_CACHE_FILE.write_text(
            json.dumps(name_map, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("failed to persist HK stock name cache: %s", exc)


def _fetch_a_share_code_name_with_timeout(
    timeout: float = A_SHARE_NAME_FETCH_TIMEOUT_SECONDS,
):
    """Fetch AkShare's code-name table without letting UI requests hang indefinitely."""

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put((True, _fetch_a_share_code_name()), block=False)
        except Exception as exc:
            try:
                result_queue.put((False, exc), block=False)
            except queue.Full:
                pass

    thread = threading.Thread(target=worker, name="stock-name-resolver", daemon=True)
    thread.start()
    try:
        ok, payload = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError("stock_info_a_code_name timed out") from exc
    if ok:
        return payload
    raise payload


def _call_with_timeout(fn, timeout: float, name: str):
    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put((True, fn()), block=False)
        except Exception as exc:
            try:
                result_queue.put((False, exc), block=False)
            except queue.Full:
                pass

    thread = threading.Thread(target=worker, name=name, daemon=True)
    thread.start()
    try:
        ok, payload = result_queue.get(timeout=timeout)
    except queue.Empty as exc:
        raise TimeoutError(f"{name} timed out") from exc
    if ok:
        return payload
    raise payload


def _find_column(columns: list[Any], candidates: tuple[str, ...]) -> Any | None:
    normalized = {str(col).strip().lower(): col for col in columns}
    for candidate in candidates:
        key = candidate.strip().lower()
        if key in normalized:
            return normalized[key]
    for col in columns:
        text = str(col).strip().lower()
        if any(candidate.strip().lower() in text for candidate in candidates):
            return col
    return None


def _a_share_name_map() -> dict[str, str]:
    """读取 AkShare A 股代码名称表，并只缓存成功结果。"""
    global _A_SHARE_NAME_CACHE

    if _A_SHARE_NAME_CACHE is not None:
        return _A_SHARE_NAME_CACHE

    with _A_SHARE_NAME_CACHE_LOCK:
        if _A_SHARE_NAME_CACHE is not None:
            return _A_SHARE_NAME_CACHE

        loaded = _load_a_share_name_map()
        if loaded:
            _A_SHARE_NAME_CACHE = loaded
            _save_persisted_a_share_name_map(loaded)
            return loaded
        return _load_persisted_a_share_name_map()


def _hk_name_map() -> dict[str, str]:
    """读取港股代码名称表，失败时保留本地缓存以免 UI 回到伪名称。"""
    global _HK_NAME_CACHE

    if _HK_NAME_CACHE is not None:
        return _HK_NAME_CACHE

    with _HK_NAME_CACHE_LOCK:
        if _HK_NAME_CACHE is not None:
            return _HK_NAME_CACHE

        loaded = _load_hk_name_map()
        if loaded:
            _HK_NAME_CACHE = loaded
            _save_persisted_hk_name_map(loaded)
            return loaded
        return _load_persisted_hk_name_map()


def _process_a_share_name_map() -> dict[str, str]:
    return _A_SHARE_NAME_CACHE or {}


def _process_hk_name_map() -> dict[str, str]:
    return _HK_NAME_CACHE or {}


def _resolved_a_share_result(
    raw_query: str,
    code: str,
    name: str,
    source: str,
) -> dict[str, Any]:
    return {
        "query": raw_query,
        "symbol": code,
        "name": name,
        "market": "CN",
        "exchange": infer_exchange(code),
        "resolved": True,
        "source": source,
    }


def _resolved_hk_result(raw_query: str, code: str, name: str, source: str) -> dict[str, Any]:
    return {
        "query": raw_query,
        "symbol": code,
        "name": name,
        "market": "HK",
        "exchange": "HK",
        "resolved": True,
        "source": source,
    }


def _load_a_share_name_map() -> dict[str, str]:
    try:
        df = _fetch_a_share_code_name_with_timeout()
    except Exception as exc:
        logger.warning("stock_info_a_code_name failed: %s", exc)
        return {}

    if df is None or len(df) == 0:
        return {}

    code_col = _find_column(list(df.columns), ("code", "代码", "股票代码"))
    name_col = _find_column(list(df.columns), ("name", "名称", "股票名称", "股票简称"))
    if code_col is None or name_col is None:
        logger.warning("unexpected stock_info_a_code_name columns: %s", list(df.columns))
        return {}

    out: dict[str, str] = {}
    for _, row in df.iterrows():
        code = _coerce_a_share_code(row.get(code_col))
        name = _clean_name(row.get(name_col))
        if code and name:
            out[code] = name
    return out


def _extract_first_name(df: Any, candidates: tuple[str, ...]) -> str:
    if df is None or len(df) == 0:
        return ""
    col = _find_column(list(df.columns), candidates)
    if col is None:
        return ""
    for _, row in df.iterrows():
        name = _clean_name(row.get(col))
        if name:
            return name
    return ""


def _fetch_hk_profile_name(code: str) -> str:
    import akshare as ak

    symbol = _coerce_hk_code(code)
    if not symbol:
        return ""

    for fn_name, columns in (
        ("stock_hk_security_profile_em", ("证券简称", "中文名称", "名称", "name")),
        ("stock_hk_company_profile_em", ("公司名称", "中文名称", "名称", "name")),
    ):
        try:
            df = getattr(ak, fn_name)(symbol=symbol)
            name = _extract_first_name(df, columns)
            if name:
                return name
        except Exception as exc:
            logger.debug("%s failed for %s: %s", fn_name, symbol, exc)
    return ""


def _fetch_hk_profile_name_with_timeout(code: str) -> str:
    return str(
        _call_with_timeout(
            lambda: _fetch_hk_profile_name(code),
            HK_STOCK_NAME_FETCH_TIMEOUT_SECONDS,
            "hk-stock-name-resolver",
        )
        or ""
    )


def _load_hk_name_map() -> dict[str, str]:
    try:
        import akshare as ak

        df = _call_with_timeout(
            ak.stock_hk_spot,
            HK_STOCK_NAME_FETCH_TIMEOUT_SECONDS,
            "hk-stock-spot-name-map",
        )
    except Exception as exc:
        logger.warning("stock_hk_spot failed: %s", exc)
        return {}

    if df is None or len(df) == 0:
        return {}

    code_col = _find_column(list(df.columns), ("代码", "证券代码", "code", "symbol"))
    name_col = _find_column(list(df.columns), ("中文名称", "证券简称", "名称", "name"))
    if code_col is None or name_col is None:
        logger.warning("unexpected stock_hk_spot columns: %s", list(df.columns))
        return {}

    out: dict[str, str] = {}
    for _, row in df.iterrows():
        code = _coerce_hk_code(row.get(code_col))
        name = _clean_name(row.get(name_col))
        if code and name:
            out[code] = name
    return out


def _resolve_hk_name(code: str) -> tuple[str, str]:
    symbol = _coerce_hk_code(code)
    if not symbol:
        return "", ""

    cached_name = _process_hk_name_map().get(symbol)
    if cached_name:
        return cached_name, "akshare_stock_hk_spot"

    persisted = _load_persisted_hk_name_map()
    if persisted.get(symbol):
        return persisted[symbol], "local_hk_stock_name_cache"

    try:
        profile_name = _fetch_hk_profile_name_with_timeout(symbol)
    except Exception as exc:
        logger.warning("HK stock profile name failed for %s: %s", symbol, exc)
        profile_name = ""

    if profile_name:
        merged = {**persisted, symbol: profile_name}
        _save_persisted_hk_name_map(merged)
        return profile_name, "akshare_stock_hk_profile"

    spot_name = _hk_name_map().get(symbol)
    if spot_name:
        return spot_name, "akshare_stock_hk_spot"
    return "", ""


def clear_stock_name_cache() -> None:
    """测试和手动刷新时清空进程内股票名称缓存。"""
    global _A_SHARE_NAME_CACHE, _HK_NAME_CACHE
    with _A_SHARE_NAME_CACHE_LOCK:
        _A_SHARE_NAME_CACHE = None
    with _HK_NAME_CACHE_LOCK:
        _HK_NAME_CACHE = None


def _fallback_result(symbol: str, query: str) -> dict[str, Any]:
    code = normalize_symbol(symbol)
    fallback = FALLBACK_STOCKS.get(code, {})
    return {
        "query": query,
        "symbol": code,
        "name": fallback.get("name") or (f"股票代码 {code}" if code else query.strip()),
        "market": fallback.get("market") or get_market(code),
        "exchange": fallback.get("exchange") or infer_exchange(code),
        "resolved": bool(fallback),
        "source": "fallback_alias" if fallback else "fallback_symbol",
    }


def resolve_stock(query: str) -> dict[str, Any]:
    """解析股票代码或名称，优先返回真实公司名称。"""
    raw_query = query or ""
    cleaned = _clean_query(raw_query)
    code = normalize_symbol(cleaned)

    if code:
        if code in FALLBACK_STOCKS:
            return _fallback_result(code, raw_query)

        result = _fallback_result(code, raw_query)
        market = get_market(code)
        if market == "HK":
            hk_name, source = _resolve_hk_name(code)
            if hk_name:
                return _resolved_hk_result(raw_query, code, hk_name, source)
        if market == "CN":
            cached_name = _process_a_share_name_map().get(code)
            if cached_name:
                return _resolved_a_share_result(
                    raw_query,
                    code,
                    cached_name,
                    "akshare_stock_info_a_code_name",
                )
            persisted_name = _load_persisted_a_share_name_map().get(code)
            if persisted_name:
                return _resolved_a_share_result(
                    raw_query,
                    code,
                    persisted_name,
                    "local_stock_name_cache",
                )
            name = _a_share_name_map().get(code)
            if name:
                return _resolved_a_share_result(
                    raw_query,
                    code,
                    name,
                    "akshare_stock_info_a_code_name",
                )
        return result

    for symbol, item in FALLBACK_STOCKS.items():
        name = item["name"]
        if cleaned and (cleaned in name.upper() or name.upper() in cleaned):
            return {
                "query": raw_query,
                "symbol": symbol,
                "name": name,
                "market": item.get("market") or get_market(symbol),
                "exchange": item.get("exchange") or infer_exchange(symbol),
                "resolved": True,
                "source": "fallback_alias",
            }

    for symbol, name in _process_a_share_name_map().items():
        if cleaned and (cleaned in name.upper() or name.upper() in cleaned):
            return _resolved_a_share_result(
                raw_query,
                symbol,
                name,
                "akshare_stock_info_a_code_name",
            )

    for symbol, name in _load_persisted_a_share_name_map().items():
        if cleaned and (cleaned in name.upper() or name.upper() in cleaned):
            return _resolved_a_share_result(
                raw_query,
                symbol,
                name,
                "local_stock_name_cache",
            )

    for symbol, name in _a_share_name_map().items():
        if cleaned and (cleaned in name.upper() or name.upper() in cleaned):
            return _resolved_a_share_result(
                raw_query,
                symbol,
                name,
                "akshare_stock_info_a_code_name",
            )

    for symbol, name in _process_hk_name_map().items():
        if cleaned and (cleaned in symbol or cleaned in name.upper() or name.upper() in cleaned):
            return _resolved_hk_result(raw_query, symbol, name, "akshare_stock_hk_spot")

    for symbol, name in _load_persisted_hk_name_map().items():
        if cleaned and (cleaned in symbol or cleaned in name.upper() or name.upper() in cleaned):
            return _resolved_hk_result(raw_query, symbol, name, "local_hk_stock_name_cache")

    for symbol, name in _hk_name_map().items():
        if cleaned and (cleaned in symbol or cleaned in name.upper() or name.upper() in cleaned):
            return _resolved_hk_result(raw_query, symbol, name, "akshare_stock_hk_spot")

    return {
        "query": raw_query,
        "symbol": "",
        "name": raw_query.strip(),
        "market": "",
        "exchange": "",
        "resolved": False,
        "source": "unresolved",
    }


def search_stocks(query: str, limit: int = 8) -> dict[str, Any]:
    """搜索股票身份，用于前端输入框的实时建议。"""
    raw_query = query or ""
    cleaned = _clean_query(raw_query)
    max_items = max(1, min(int(limit or 8), 20))
    results: list[dict[str, Any]] = []

    def add(item: dict[str, Any]) -> None:
        symbol = str(item.get("symbol") or "")
        if not symbol:
            return
        if any(existing.get("symbol") == symbol for existing in results):
            return
        results.append(item)

    resolved = resolve_stock(raw_query)
    add(resolved)

    for symbol, item in FALLBACK_STOCKS.items():
        name = item["name"]
        haystack = f"{symbol}{name}{item.get('exchange', '')}".upper()
        if cleaned and cleaned in haystack:
            add(_fallback_result(symbol, raw_query))
        if len(results) >= max_items:
            break

    if len(results) < max_items:
        for source, name_map, market in (
            ("akshare_stock_info_a_code_name", _process_a_share_name_map(), "CN"),
            ("local_stock_name_cache", _load_persisted_a_share_name_map(), "CN"),
            ("akshare_stock_info_a_code_name", _a_share_name_map(), "CN"),
            ("akshare_stock_hk_spot", _process_hk_name_map(), "HK"),
            ("local_hk_stock_name_cache", _load_persisted_hk_name_map(), "HK"),
            ("akshare_stock_hk_spot", _hk_name_map(), "HK"),
        ):
            if len(results) >= max_items:
                break
            for symbol, name in name_map.items():
                haystack = f"{symbol}{name}".upper()
                if cleaned and cleaned in haystack:
                    add(
                        _resolved_hk_result(raw_query, symbol, name, source)
                        if market == "HK"
                        else _resolved_a_share_result(raw_query, symbol, name, source)
                    )
                    if len(results) >= max_items:
                        break

    return {"query": raw_query, "results": results[:max_items], "total": len(results)}
