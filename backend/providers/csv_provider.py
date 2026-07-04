"""CSV/Excel 上传数据源 — 用户自带行情数据, 零 Key 入查询面(v1.9.4, compass §7.2)。

动机
----
专业用户常有自己的行情/因子数据(券商导出、自建数据库、回测样本), 却被挡在
「必须配某个数据源 Key」之外。本 Provider 让用户把 CSV/Excel 丢进上传目录, 自动
**发现列 schema**(中英文表头都认), 映射到标准 OHLCV, 即可像内置数据源一样被
registry 选中、进入价格查询与回测面板。

设计
----
- 读取目录: ``data/uploads/csv/``(``UPLOADS_DIR/csv``), 不存在则惰性创建。
- 文件按 ``<代码>.csv`` / ``<代码>.xlsx`` 命名(代码取数字部分匹配 query.symbol)。
- ``discover_schema`` 是纯函数: 把任意表头映射到 date/open/high/low/close/volume/amount。
- ``priority = 15``: 高于 demo_seed(5), 低于真实在线源(akshare=60…), 即「用户本地数据
  优先于演示样本, 但联网真源仍优先」。
- ``requires_key = False``;数据带 ``source="csv_upload"`` / ``user_upload=True`` 明确标注
  来源, 绝不冒充在线行情。
- Excel 走 pandas/openpyxl(惰性导入);缺依赖时优雅跳过该文件, 不影响 CSV。
"""

from __future__ import annotations

import csv
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseProvider

logger = logging.getLogger(__name__)

# 规范字段 → 可识别的表头别名(小写匹配英文, 原样匹配中文)
_COLUMN_ALIASES: Dict[str, List[str]] = {
    "date": [
        "date",
        "datetime",
        "time",
        "trade_date",
        "tradedate",
        "日期",
        "时间",
        "交易日期",
        "交易日",
    ],
    "open": ["open", "o", "open_price", "openprice", "开盘", "开盘价", "今开"],
    "high": ["high", "h", "high_price", "highprice", "最高", "最高价"],
    "low": ["low", "l", "low_price", "lowprice", "最低", "最低价"],
    "close": [
        "close",
        "c",
        "close_price",
        "closeprice",
        "adj_close",
        "adjclose",
        "收盘",
        "收盘价",
        "今收",
        "最新价",
    ],
    "volume": ["volume", "vol", "v", "turnover_volume", "成交量", "总手"],
    "amount": [
        "amount",
        "turnover",
        "turnover_amount",
        "成交额",
        "成交金额",
        "成交额(元)",
    ],
    "symbol": ["symbol", "code", "ticker", "代码", "股票代码", "证券代码"],
}

_REQUIRED_FIELDS = ("date", "open", "high", "low", "close")


def _norm_header(h: Any) -> str:
    """规范化表头: 去空白, 英文转小写(中文原样)。"""
    s = str(h or "").strip()
    # 去掉常见单位后缀如 (元)/(手) 便于匹配
    s = re.sub(r"[\(（].*?[\)）]\s*$", "", s).strip()
    # 英文部分小写; 中文不受影响
    return s.lower()


def discover_schema(headers: List[str]) -> Dict[str, Optional[str]]:
    """从任意表头发现列 schema, 返回 {规范字段: 实际表头 或 None}。

    纯函数, 不读文件——便于单测。同一规范字段命中多个表头时取**首个**。
    """
    # 反向索引: 别名 → 规范字段
    alias_to_canon: Dict[str, str] = {}
    for canon, aliases in _COLUMN_ALIASES.items():
        for a in aliases:
            alias_to_canon[a] = canon

    schema: Dict[str, Optional[str]] = {k: None for k in _COLUMN_ALIASES}
    for raw in headers:
        norm = _norm_header(raw)
        canon = alias_to_canon.get(norm)
        if canon and schema.get(canon) is None:
            schema[canon] = raw  # 保留原始表头, 供后续按原 key 取值
    return schema


def schema_is_valid(schema: Dict[str, Optional[str]]) -> bool:
    """date + OHLC 齐全才算可用价格表(volume/amount/symbol 可缺)。"""
    return all(schema.get(f) is not None for f in _REQUIRED_FIELDS)


def _to_float(value: Any) -> float:
    try:
        f = float(str(value).replace(",", "").strip())
        return f if f == f else 0.0  # NaN → 0
    except (TypeError, ValueError):
        return 0.0


def _norm_symbol(symbol: str) -> str:
    """取股票代码的数字部分(去掉 SH/SZ/.XSHE 等后缀)。"""
    digits = "".join(ch for ch in str(symbol).upper() if ch.isdigit())
    return digits[:6]


def parse_rows(
    rows: List[Dict[str, Any]],
    schema: Dict[str, Optional[str]],
    symbol: str = "",
    limit: int = 250,
) -> List[Dict[str, Any]]:
    """把原始行 + schema 解析为标准 OHLCV bars(纯函数, 便于单测)。

    按日期升序返回, 取最后 ``limit`` 根。
    """
    if not schema_is_valid(schema):
        return []

    bars: List[Dict[str, Any]] = []
    for row in rows:
        date_val = str(row.get(schema["date"], "")).strip()[:10] if schema["date"] else ""
        if not date_val:
            continue
        close = _to_float(row.get(schema["close"])) if schema["close"] else 0.0
        if close <= 0:
            continue  # 跳过无效行, 不伪造
        bar = {
            "symbol": _norm_symbol(symbol) or "",
            "date": date_val,
            "frequency": "1d",
            "open": _to_float(row.get(schema["open"])) if schema["open"] else 0.0,
            "high": _to_float(row.get(schema["high"])) if schema["high"] else 0.0,
            "low": _to_float(row.get(schema["low"])) if schema["low"] else 0.0,
            "close": close,
            "volume": _to_float(row.get(schema["volume"])) if schema["volume"] else 0.0,
            "amount": _to_float(row.get(schema["amount"])) if schema["amount"] else 0.0,
            "source": "csv_upload",
            "user_upload": True,  # 明确标注用户数据来源
        }
        bars.append(bar)

    bars.sort(key=lambda b: b["date"])
    return bars[-limit:] if limit and len(bars) > limit else bars


def _csv_dir() -> Path:
    """上传目录 data/uploads/csv/, 惰性创建。"""
    try:
        from backend.project_paths import UPLOADS_DIR

        d = UPLOADS_DIR / "csv"
    except Exception:
        d = Path("data/uploads/csv")
    try:
        d.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return d


def _read_table(path: Path) -> List[Dict[str, Any]]:
    """读 CSV/Excel 为 list[dict](表头→值)。Excel 依赖缺失则返回空。"""
    suffix = path.suffix.lower()
    if suffix in (".csv", ".txt"):
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            with open(path, "r", encoding="gbk", newline="") as f:
                return list(csv.DictReader(f))
        except Exception as e:  # noqa: BLE001
            logger.warning("[csv_upload] 读取 CSV 失败 %s: %s", path.name, e)
            return []
    if suffix in (".xlsx", ".xls"):
        try:
            import pandas as pd  # 惰性导入, 避免拖慢 provider 发现

            df = pd.read_excel(path, dtype=str)
            return df.to_dict("records")
        except Exception as e:  # noqa: BLE001 - 缺 openpyxl/pandas 时优雅降级
            logger.warning("[csv_upload] 读取 Excel 失败 %s: %s", path.name, e)
            return []
    return []


def discover_file(path: Path) -> Dict[str, Any]:
    """对单个文件做 schema 发现 + 概览(供「入查询面」展示)。"""
    rows = _read_table(path)
    headers = list(rows[0].keys()) if rows else []
    schema = discover_schema(headers)
    valid = schema_is_valid(schema)
    bars = parse_rows(rows, schema, symbol=path.stem, limit=100000) if valid else []
    dates = [b["date"] for b in bars]
    return {
        "filename": path.name,
        "symbol": _norm_symbol(path.stem),
        "rows": len(rows),
        "valid": valid,
        "schema": schema,
        "mapped": [k for k, v in schema.items() if v is not None],
        "unmapped_columns": [h for h in headers if h not in schema.values()],
        "date_range": [dates[0], dates[-1]] if dates else [],
        "bar_count": len(bars),
    }


def list_datasets() -> List[Dict[str, Any]]:
    """列出上传目录下所有数据集的 schema 概览(用户向查询面)。"""
    out: List[Dict[str, Any]] = []
    for path in sorted(_csv_dir().glob("*")):
        if path.suffix.lower() in (".csv", ".txt", ".xlsx", ".xls"):
            try:
                out.append(discover_file(path))
            except Exception as e:  # noqa: BLE001
                logger.warning("[csv_upload] 概览失败 %s: %s", path.name, e)
    return out


def save_upload(filename: str, content: bytes) -> Dict[str, Any]:
    """保存一个上传文件到 csv 目录并返回 schema 概览。

    文件名只取 basename 并校验扩展名, 防目录穿越。
    """
    safe = Path(filename).name
    suffix = Path(safe).suffix.lower()
    if suffix not in (".csv", ".txt", ".xlsx", ".xls"):
        raise ValueError(f"不支持的文件类型: {suffix}(仅 csv/txt/xlsx/xls)")
    target = _csv_dir() / safe
    target.write_bytes(content)
    logger.info("[csv_upload] 已保存上传文件: %s (%d bytes)", safe, len(content))
    return discover_file(target)


class CsvUploadProvider(BaseProvider):
    """用户上传 CSV/Excel 行情数据源(零 Key, 本地优先于演示样本)。"""

    name = "csv_upload"
    markets = ["CN", "HK", "US", "ALL"]
    data_types = ["prices"]
    priority = 15  # demo_seed(5) < csv_upload(15) < 真实在线源(akshare=60…)
    license_level = "user_provided"
    data_class = "price"
    freshness = "daily"
    cost_tier = "free"
    rate_limit: dict = {"per_minute": None, "per_day": None}
    requires_key = False

    @classmethod
    def is_available(cls) -> bool:
        """本地能力, 始终可用(目录按需创建)。"""
        return True

    def _find_file(self, symbol: str) -> Optional[Path]:
        """按代码匹配上传文件: 文件名数字部分 == query 代码数字部分。"""
        want = _norm_symbol(symbol)
        if not want:
            return None
        for path in sorted(_csv_dir().glob("*")):
            if path.suffix.lower() not in (".csv", ".txt", ".xlsx", ".xls"):
                continue
            if _norm_symbol(path.stem) == want:
                return path
        return None

    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        """返回用户上传文件中该代码的行情, 明确标注 source=csv_upload。"""
        symbol = str(query.get("symbol", "")).strip()
        if not symbol:
            return []
        path = self._find_file(symbol)
        if path is None:
            return []
        rows = self._timed_call(_read_table, path)
        if not rows:
            return []
        headers = list(rows[0].keys())
        schema = discover_schema(headers)
        if not schema_is_valid(schema):
            self._logger.info("[csv_upload] %s 列 schema 不完整(缺 date/OHLC), 跳过", path.name)
            return []
        limit = int(query.get("limit", 250) or 250)
        return parse_rows(rows, schema, symbol=symbol, limit=limit)
