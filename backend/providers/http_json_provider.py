"""TickFlow HTTP/JSON 自定义数据表 — 用户配置外部 JSON 行情接口, 拉取 + 字段映射入查询面(v1.9.19)。

动机
----
v1.9.4 的 [[csv_provider]] 让用户**上传文件**自带行情;但很多用户的数据在一个 **HTTP/JSON 接口**
后面(自建行情服务、券商开放接口、第三方 K 线 API)。本模块补上这条:用户配置一个 JSON 源
(URL + 记录路径 + 字段映射), 点「拉取」即把远端 JSON 映射成标准 OHLCV、**物化到本地缓存**,
此后像 csv_upload 一样被 registry 选中、进入价格查询与回测面板。

设计(对齐 csv_provider 的「显式导入 → 离线可查」哲学)
----
- **网络只发生在显式「拉取」时**:`refresh_source()` 抓一次远端、映射、写本地缓存文件。
  热路径 `get_prices()` 只读**已物化的本地缓存**, 完全离线、确定性。
- **映射/抽取是纯函数**(`extract_records` / `apply_field_map` / `infer_field_map`), 给定 JSON +
  字段映射即可单测, 不触网。
- **失败安全**:抓取超时/报错/JSON 不合预期 → 返回结构化错误(标 `last_status=error`), 绝不抛出;
  既有物化缓存保留(降级可用), 不会因一次抓取失败而清空数据。
- **诚实标注**:数据带 `source="http_json"` / `user_provided=True`, 绝不冒充内置在线源。
- **零新依赖**:抓取优先用已有的 `requests`, 缺失时回退 stdlib `urllib`。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .base import BaseProvider
from .csv_provider import _norm_symbol, _to_float, discover_schema

logger = logging.getLogger(__name__)

_REQUIRED_FIELDS = ("date", "open", "high", "low", "close")
_OPTIONAL_FIELDS = ("volume", "amount", "symbol")
_ALL_FIELDS = _REQUIRED_FIELDS + _OPTIONAL_FIELDS


# ----------------------------- 目录 / 存储 -----------------------------


def _root_dir() -> Path:
    """TickFlow 根目录 data/uploads/tickflow/, 惰性创建。"""
    try:
        from backend.project_paths import UPLOADS_DIR

        d = UPLOADS_DIR / "tickflow"
    except Exception:
        d = Path("data/uploads/tickflow")
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "data").mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _sources_file() -> Path:
    return _root_dir() / "sources.json"


def _data_file(symbol: str) -> Path:
    return _root_dir() / "data" / f"{_norm_symbol(symbol) or 'unknown'}.json"


# ----------------------------- 纯函数(可单测) -----------------------------


def _slugify(text: str) -> str:
    s = re.sub(r"[^0-9a-zA-Z一-鿿]+", "-", str(text or "").strip()).strip("-")
    return s.lower()[:48] or "source"


def extract_records(payload: Any, records_path: str = "") -> List[Dict[str, Any]]:
    """从 JSON 载荷里按点路径定位到**记录数组**(纯函数)。

    - ``records_path=""``:载荷本身应是数组。
    - ``records_path="data.klines"``:逐段下钻;数字段名表示列表索引。
    返回 list[dict];定位不到或非数组返回 []。
    """
    node = payload
    if records_path:
        for seg in str(records_path).split("."):
            seg = seg.strip()
            if seg == "":
                continue
            try:
                if isinstance(node, list) and seg.lstrip("-").isdigit():
                    node = node[int(seg)]
                elif isinstance(node, dict):
                    node = node.get(seg)
                else:
                    return []
            except (IndexError, KeyError, TypeError):
                return []
            if node is None:
                return []
    if not isinstance(node, list):
        return []
    # 记录可能是 dict(键值对)或 list(位置数组, 如 [t,o,h,l,c,v]);后者交由 apply_field_map 处理
    return [r for r in node if isinstance(r, (dict, list))]


def _record_get(record: Any, key: Any) -> Any:
    """从一条记录(dict 或 list)取字段:dict 按键, list 按整数下标。"""
    if isinstance(record, dict):
        return record.get(key)
    if isinstance(record, list):
        try:
            return record[int(key)]
        except (ValueError, TypeError, IndexError):
            return None
    return None


def _norm_date(value: Any) -> str:
    """把日期值规范化为 YYYY-MM-DD;支持毫秒/秒级时间戳与字符串。"""
    if value is None:
        return ""
    # 纯数字 → 时间戳(>1e12 视为毫秒)
    try:
        if isinstance(value, (int, float)) or (
            isinstance(value, str) and value.strip().isdigit()
        ):
            ts = float(value)
            if ts > 1e12:
                ts /= 1000.0
            if ts > 1e8:  # 合理的秒级时间戳下限(1973+)
                return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (ValueError, OSError, OverflowError):
        pass
    return str(value).strip()[:10]


def apply_field_map(
    records: List[Any],
    field_map: Dict[str, Any],
    symbol: str = "",
    limit: int = 250,
) -> List[Dict[str, Any]]:
    """按字段映射把记录数组解析成标准 OHLCV bars(纯函数, 便于单测)。

    ``field_map`` = {规范字段: 远端字段名/下标}。date+OHLC 缺映射则返回 []。
    """
    field_map = field_map or {}
    if not all(field_map.get(f) not in (None, "") for f in _REQUIRED_FIELDS):
        return []

    bars: List[Dict[str, Any]] = []
    for rec in records or []:
        date_val = _norm_date(_record_get(rec, field_map["date"]))
        if not date_val:
            continue
        close = _to_float(_record_get(rec, field_map["close"]))
        if close <= 0:
            continue  # 跳过无效行, 不伪造
        sym_field = field_map.get("symbol")
        rec_symbol = str(_record_get(rec, sym_field)) if sym_field else ""
        bars.append(
            {
                "symbol": _norm_symbol(rec_symbol or symbol) or "",
                "date": date_val,
                "frequency": "1d",
                "open": _to_float(_record_get(rec, field_map.get("open"))),
                "high": _to_float(_record_get(rec, field_map.get("high"))),
                "low": _to_float(_record_get(rec, field_map.get("low"))),
                "close": close,
                "volume": _to_float(_record_get(rec, field_map.get("volume")))
                if field_map.get("volume")
                else 0.0,
                "amount": _to_float(_record_get(rec, field_map.get("amount")))
                if field_map.get("amount")
                else 0.0,
                "source": "http_json",
                "user_provided": True,
            }
        )
    bars.sort(key=lambda b: b["date"])
    return bars[-limit:] if limit and len(bars) > limit else bars


def infer_field_map(sample: Any) -> Dict[str, Optional[str]]:
    """从一条样本记录(dict)猜测字段映射(复用 csv 的表头发现逻辑, 纯函数)。

    list 型记录无字段名, 无法推断 → 返回空映射(用户手填下标)。
    """
    if isinstance(sample, dict):
        schema = discover_schema(list(sample.keys()))
        return {k: v for k, v in schema.items() if k in _ALL_FIELDS}
    return {k: None for k in _ALL_FIELDS}


def normalize_source(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """校验并规范化一个源配置(纯函数, 失败安全填默认)。"""
    cfg = cfg if isinstance(cfg, dict) else {}
    name = str(cfg.get("name") or cfg.get("id") or "自定义源").strip()
    sid = str(cfg.get("id") or "").strip() or _slugify(name)
    method = str(cfg.get("method") or "GET").upper()
    if method not in ("GET", "POST"):
        method = "GET"
    headers = cfg.get("headers") if isinstance(cfg.get("headers"), dict) else {}
    field_map = cfg.get("field_map") if isinstance(cfg.get("field_map"), dict) else {}
    field_map = {
        k: v for k, v in field_map.items() if k in _ALL_FIELDS and v not in (None, "")
    }
    return {
        "id": sid,
        "name": name,
        "url": str(cfg.get("url") or "").strip(),
        "symbol": _norm_symbol(cfg.get("symbol") or ""),
        "method": method,
        "headers": headers,
        "body": cfg.get("body") if isinstance(cfg.get("body"), (dict, list)) else None,
        "records_path": str(cfg.get("records_path") or "").strip(),
        "field_map": field_map,
        "created_at": str(cfg.get("created_at") or datetime.now().isoformat()),
        "last_refresh": cfg.get("last_refresh"),
        "last_status": cfg.get("last_status"),
        "last_error": cfg.get("last_error"),
        "bar_count": int(cfg.get("bar_count") or 0),
    }


# ----------------------------- 源注册表(本地 JSON) -----------------------------


def list_sources() -> List[Dict[str, Any]]:
    """列出已配置的 HTTP/JSON 源。失败返回 []。"""
    try:
        f = _sources_file()
        if not f.exists():
            return []
        data = json.loads(f.read_text(encoding="utf-8"))
        return [normalize_source(s) for s in data] if isinstance(data, list) else []
    except Exception:
        return []


def _write_sources(sources: List[Dict[str, Any]]) -> bool:
    try:
        _sources_file().write_text(
            json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def save_source(cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """新增或更新一个源(按 id 去重)。失败返回 None。"""
    try:
        norm = normalize_source(cfg)
        sources = list_sources()
        sources = [s for s in sources if s.get("id") != norm["id"]]
        sources.append(norm)
        return norm if _write_sources(sources) else None
    except Exception:
        return None


def get_source(source_id: str) -> Optional[Dict[str, Any]]:
    for s in list_sources():
        if s.get("id") == source_id:
            return s
    return None


def delete_source(source_id: str) -> bool:
    """删除一个源(不删已物化的缓存数据)。失败返回 False。"""
    try:
        sources = list_sources()
        kept = [s for s in sources if s.get("id") != source_id]
        if len(kept) == len(sources):
            return False
        return _write_sources(kept)
    except Exception:
        return False


# ----------------------------- 网络抓取(失败安全) -----------------------------


def fetch_json(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, Any]] = None,
    body: Any = None,
    timeout: float = 12.0,
) -> Dict[str, Any]:
    """抓一次远端 JSON。**失败安全**:任何错误都返回 {ok:False, error:...}, 绝不抛出。

    优先用 requests, 缺失回退 stdlib urllib。仅本函数触网, 供 refresh_source 调用、可注入替身。

    SSRF 防护: 入口与重定向后均用 ``url_guard.validate_public_http_url`` 校验目标主机非内网
    (防 127.0.0.1/10.x/169.254.169.254 等)。本机调试可设 ``ALPHASCOPE_ALLOW_LOCAL_FETCH=1``。
    """
    from backend.security.url_guard import validate_public_http_url

    # 入口校验: 拒非 http(s) 与内网目标
    try:
        safe_url = validate_public_http_url(url)
    except ValueError as e:
        return {"ok": False, "status": 0, "payload": None, "error": f"URL 非法: {e}"}
    headers = headers or {}
    method = (method or "GET").upper()
    try:
        try:
            import requests  # 优先复用项目已有依赖

            resp = requests.request(
                method,
                safe_url,
                headers=headers,
                json=body if (body is not None and method == "POST") else None,
                timeout=timeout,
            )
            # 重定向后复校验最终 URL(防 302→内网绕过)
            try:
                validate_public_http_url(str(resp.url or safe_url))
            except ValueError as e:
                return {
                    "ok": False,
                    "status": resp.status_code,
                    "payload": None,
                    "error": f"重定向到不安全目标: {e}",
                }
            status = resp.status_code
            if status >= 400:
                return {
                    "ok": False,
                    "status": status,
                    "payload": None,
                    "error": f"HTTP {status}",
                }
            return {"ok": True, "status": status, "payload": resp.json(), "error": None}
        except ImportError:
            pass

        import urllib.request

        data = None
        req_headers = dict(headers)
        if body is not None and method == "POST":
            data = json.dumps(body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(safe_url, data=data, headers=req_headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - 入口已 SSRF 校验
            # 重定向后复校验最终 URL
            try:
                validate_public_http_url(r.geturl())
            except ValueError as e:
                return {
                    "ok": False,
                    "status": getattr(r, "status", 200),
                    "payload": None,
                    "error": f"重定向到不安全目标: {e}",
                }
            raw = r.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status": getattr(r, "status", 200),
                "payload": json.loads(raw),
                "error": None,
            }
    except Exception as e:  # noqa: BLE001 - 失败安全
        return {
            "ok": False,
            "status": 0,
            "payload": None,
            "error": f"{type(e).__name__}: {e}",
        }


def _materialize(symbol: str, bars: List[Dict[str, Any]]) -> bool:
    try:
        _data_file(symbol).write_text(
            json.dumps(bars, ensure_ascii=False), encoding="utf-8"
        )
        return True
    except Exception:
        return False


def materialized_bars(symbol: str, limit: int = 250) -> List[Dict[str, Any]]:
    """读已物化的本地缓存 bars(离线、确定性)。失败返回 []。"""
    try:
        f = _data_file(symbol)
        if not f.exists():
            return []
        bars = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(bars, list):
            return []
        return bars[-limit:] if limit and len(bars) > limit else bars
    except Exception:
        return []


def refresh_source(
    source_id: str,
    fetcher: Optional[Callable[..., Dict[str, Any]]] = None,
    limit: int = 1000,
) -> Dict[str, Any]:
    """拉取一次源并物化。**失败安全**, 失败不清空既有缓存。``fetcher`` 可注入(测试不触网)。

    返回 {ok, source_id, symbol, bar_count, date_range, sample, error}。
    """
    src = get_source(source_id)
    if not src:
        return {"ok": False, "source_id": source_id, "error": "源不存在"}

    symbol = src.get("symbol") or ""
    url = src.get("url") or ""
    if "{symbol}" in url:
        url = url.replace("{symbol}", symbol)

    do_fetch = fetcher or fetch_json
    res = do_fetch(
        url=url,
        method=src.get("method", "GET"),
        headers=src.get("headers"),
        body=src.get("body"),
    )
    now_iso = datetime.now().isoformat()

    if not res or not res.get("ok"):
        err = (res or {}).get("error") or "抓取失败"
        _update_source_status(source_id, "error", err)
        return {
            "ok": False,
            "source_id": source_id,
            "symbol": symbol,
            "error": err,
            "bar_count": len(materialized_bars(symbol)),
            "kept_cache": True,
        }

    records = extract_records(res.get("payload"), src.get("records_path", ""))
    if not records:
        _update_source_status(source_id, "error", "记录路径定位不到数组")
        return {
            "ok": False,
            "source_id": source_id,
            "symbol": symbol,
            "error": "记录路径定位不到数组(检查 records_path)",
            "kept_cache": True,
        }

    bars = apply_field_map(
        records, src.get("field_map", {}), symbol=symbol, limit=limit
    )
    if not bars:
        _update_source_status(source_id, "error", "字段映射无有效行(检查 field_map)")
        return {
            "ok": False,
            "source_id": source_id,
            "symbol": symbol,
            "error": "字段映射后无有效行(检查 field_map / 日期/收盘列)",
            "kept_cache": True,
        }

    _materialize(symbol, bars)
    dates = [b["date"] for b in bars]
    _update_source_status(
        source_id, "ok", None, bar_count=len(bars), last_refresh=now_iso
    )
    return {
        "ok": True,
        "source_id": source_id,
        "symbol": symbol,
        "bar_count": len(bars),
        "date_range": [dates[0], dates[-1]] if dates else [],
        "sample": bars[-1] if bars else None,
        "error": None,
    }


def _update_source_status(
    source_id: str,
    status: str,
    error: Optional[str],
    bar_count: Optional[int] = None,
    last_refresh: Optional[str] = None,
) -> None:
    try:
        sources = list_sources()
        for s in sources:
            if s.get("id") == source_id:
                s["last_status"] = status
                s["last_error"] = error
                if bar_count is not None:
                    s["bar_count"] = bar_count
                if last_refresh is not None:
                    s["last_refresh"] = last_refresh
        _write_sources(sources)
    except Exception:
        pass


def preview_fetch(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, Any]] = None,
    body: Any = None,
    records_path: str = "",
    fetcher: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """抓一次并返回**样本记录 + 推断字段映射**, 辅助用户配置(不物化)。失败安全。"""
    do_fetch = fetcher or fetch_json
    res = do_fetch(url=url, method=method, headers=headers, body=body)
    if not res or not res.get("ok"):
        return {"ok": False, "error": (res or {}).get("error") or "抓取失败"}
    records = extract_records(res.get("payload"), records_path)
    if not records:
        keys = (
            list(res["payload"].keys()) if isinstance(res.get("payload"), dict) else []
        )
        return {"ok": False, "error": "记录路径定位不到数组", "top_level_keys": keys}
    sample = records[0]
    return {
        "ok": True,
        "record_count": len(records),
        "sample": sample,
        "sample_keys": list(sample.keys())
        if isinstance(sample, dict)
        else [f"[{i}]" for i in range(len(sample))],
        "inferred_field_map": infer_field_map(sample),
    }


# ----------------------------- Provider -----------------------------


class HttpJsonProvider(BaseProvider):
    """用户配置的 HTTP/JSON 自定义行情源(读已物化的本地缓存, 离线确定性)。"""

    name = "http_json"
    markets = ["CN", "HK", "US", "ALL"]
    data_types = ["prices"]
    priority = 14  # demo_seed(5) < http_json(14) < csv_upload(15) < 真实在线源
    license_level = "user_provided"
    data_class = "price"
    freshness = "on_demand"
    cost_tier = "free"
    rate_limit: dict = {"per_minute": None, "per_day": None}
    requires_key = False

    @classmethod
    def is_available(cls) -> bool:
        """本地能力(读物化缓存), 始终可用。"""
        return True

    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        """返回该代码已物化的 HTTP/JSON 行情, 明确标注 source=http_json。"""
        symbol = str(query.get("symbol", "")).strip()
        if not symbol:
            return []
        limit = int(query.get("limit", 250) or 250)
        return materialized_bars(symbol, limit=limit)
