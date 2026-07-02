"""因子注册中心 / 研究流水线 — 统一注册因子、确定性计算技术因子、缓存、批量因子矩阵(v1.9.21)。

动机
----
项目已有 [[factors.generator]] 的 5 个「软因子」(舆情/事件/评级/资金流/动量, 触网),
但缺一个**统一的因子目录**:每个因子的类别/方向/口径散落各处, 也没有把**确定性技术因子**
(纯 OHLCV 算出)纳入统一框架, 更没有「一次算一篮子标的」的批量研究流水线。

本模块补齐三件事(对标 Qlib 的 factor/alpha 研究流程, 但保持本项目「确定性·失败安全·不触网」基线):
1. **注册(catalog)**:`FactorDef` 描述每个因子的 id/名称/类别/方向/口径/来源, 统一可查、可配置。
2. **确定性技术因子**:从 OHLCV **纯函数**算出动量/波动/均线乖离/RSI/回撤/量比/距高点等, 失败安全。
3. **研究流水线**:`compute_for_symbol`(单标的因子向量)+ `compute_matrix`(跨标的因子矩阵),
   配 **SQLite 缓存**(自包含懒建表, 仿 [[experiment_store]]), 跨会话可调阅。

合规:因子是对**历史**量价结构的确定性度量, 方向(direction)只是口径标注(越大越偏多/偏空/中性),
**不据此给买卖指令、不预测、不构成选股建议**;批量矩阵仅描述「过去的横截面特征」, 均附免责。
"""

from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

_TABLE = "factor_vectors"
_write_lock = threading.Lock()
_ensured = False
_KEEP = 2000  # 缓存因子向量上限(个人工具)


# ----------------------------- 因子定义 / 注册表 -----------------------------


@dataclass(frozen=True)
class FactorDef:
    id: str
    name: str
    category: str  # technical | sentiment | event | analyst | flow
    direction: int  # +1 越大越偏多 / -1 越大越偏空 / 0 中性·需结合
    description: str
    source: str  # price(确定性技术因子) | soft(来自 FactorGenerator)
    unit: str = ""


# 确定性技术因子(本模块直接从 OHLCV 算)+ 已有软因子(登记入目录, 计算仍走 FactorGenerator)。
_REGISTRY: Dict[str, FactorDef] = {}


def _register(defn: FactorDef) -> None:
    _REGISTRY[defn.id] = defn


for _d in [
    FactorDef(
        "mom_20", "20日动量", "technical", 1, "近 20 个交易日收盘涨跌幅", "price", "%"
    ),
    FactorDef(
        "mom_60", "60日动量", "technical", 1, "近 60 个交易日收盘涨跌幅", "price", "%"
    ),
    FactorDef(
        "vol_20",
        "20日波动率",
        "technical",
        -1,
        "近 20 日日收益年化标准差",
        "price",
        "%",
    ),
    FactorDef(
        "ma20_gap", "MA20乖离", "technical", 1, "收盘相对 20 日均线的偏离", "price", "%"
    ),
    FactorDef(
        "ma60_gap", "MA60乖离", "technical", 1, "收盘相对 60 日均线的偏离", "price", "%"
    ),
    FactorDef(
        "rsi_14", "RSI(14)", "technical", 0, "14 日相对强弱指标(50 为中性)", "price", ""
    ),
    FactorDef(
        "max_dd_60",
        "60日最大回撤",
        "technical",
        1,
        "近 60 日最大回撤(越接近 0 越稳)",
        "price",
        "%",
    ),
    FactorDef(
        "vol_ratio",
        "量比(5/20)",
        "technical",
        1,
        "近 5 日均量 / 近 20 日均量",
        "price",
        "x",
    ),
    FactorDef(
        "dist_high_60",
        "距60日高点",
        "technical",
        1,
        "收盘距近 60 日最高价的距离(≤0)",
        "price",
        "%",
    ),
    FactorDef(
        "range_pos_60",
        "60日区间位置",
        "technical",
        1,
        "收盘在近 60 日高低区间的相对位置(0-1)",
        "price",
        "",
    ),
    # 已有软因子(登记入统一目录;具体数值由 FactorGenerator 计算)。
    FactorDef(
        "news_sentiment", "新闻情绪", "sentiment", 1, "新闻舆情情绪得分", "soft", ""
    ),
    FactorDef(
        "event_signal", "事件信号", "event", 1, "公告/事件方向性得分", "soft", ""
    ),
    FactorDef(
        "analyst_rating", "分析师评级", "analyst", 1, "卖方评级倾向得分", "soft", ""
    ),
    FactorDef("fund_flow", "资金流", "flow", 1, "主力资金流向得分", "soft", ""),
    FactorDef(
        "momentum",
        "综合动量(软)",
        "technical",
        1,
        "FactorGenerator 的动量因子",
        "soft",
        "",
    ),
    # 替代因子(另类数据): 来自 FRED 宏观 / Finnhub 情绪等 provider,
    # 原 provider 注册了但无消费链路;此处登记入因子目录, 数值由 alternative_factors 模块计算。
    FactorDef(
        "macro_risk_appetite",
        "宏观风险偏好",
        "macro",
        1,
        "FRED 利率/利差/就业等宏观指标合成的风险偏好(另类因子)",
        "alternative",
        "",
    ),
    FactorDef(
        "us_sentiment",
        "美股情绪(另类)",
        "sentiment",
        1,
        "Finnhub 个股情绪/内部人交易合成的情绪得分(另类因子, 仅美股)",
        "alternative",
        "",
    ),
]:
    _register(_d)

# 确定性技术因子 id(本模块可独立计算的那部分)。
TECHNICAL_FACTORS = [d.id for d in _REGISTRY.values() if d.source == "price"]


def list_factors(
    category: Optional[str] = None, source: Optional[str] = None
) -> List[Dict[str, Any]]:
    """列出因子目录(可按类别/来源过滤)。纯函数。"""
    out = []
    for d in _REGISTRY.values():
        if category and d.category != category:
            continue
        if source and d.source != source:
            continue
        out.append(
            {
                "id": d.id,
                "name": d.name,
                "category": d.category,
                "direction": d.direction,
                "description": d.description,
                "source": d.source,
                "unit": d.unit,
            }
        )
    return out


def get_factor(factor_id: str) -> Optional[FactorDef]:
    return _REGISTRY.get(factor_id)


# ----------------------------- 确定性技术因子(纯函数, 可单测) -----------------------------


def _closes(bars: List[Dict[str, Any]]) -> List[float]:
    out = []
    for b in bars or []:
        if not isinstance(b, dict):
            continue
        try:
            c = float(b.get("close"))
            if c > 0 and c == c:
                out.append(c)
        except (TypeError, ValueError):
            continue
    return out


def _series(bars: List[Dict[str, Any]], key: str) -> List[float]:
    out = []
    for b in bars or []:
        if not isinstance(b, dict):
            continue
        try:
            v = float(b.get(key))
            out.append(v if v == v else 0.0)
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def _pct_return(closes: List[float], window: int) -> Optional[float]:
    if len(closes) <= window or closes[-window - 1] <= 0:
        return None
    return round((closes[-1] / closes[-window - 1] - 1.0) * 100.0, 3)


def _volatility(closes: List[float], window: int = 20) -> Optional[float]:
    if len(closes) <= window:
        return None
    rets = [
        closes[i] / closes[i - 1] - 1.0
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return round(math.sqrt(var) * math.sqrt(252) * 100.0, 3)  # 年化波动率%


def _ma_gap(closes: List[float], window: int) -> Optional[float]:
    if len(closes) < window:
        return None
    ma = sum(closes[-window:]) / window
    if ma <= 0:
        return None
    return round((closes[-1] / ma - 1.0) * 100.0, 3)


def _rsi(closes: List[float], window: int = 14) -> Optional[float]:
    if len(closes) <= window:
        return None
    gains, losses = 0.0, 0.0
    for i in range(len(closes) - window, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains += diff
        else:
            losses -= diff
    if gains + losses == 0:
        return 50.0
    rs = gains / losses if losses > 0 else float("inf")
    return round(100.0 - 100.0 / (1.0 + rs), 2) if losses > 0 else 100.0


def _max_drawdown(closes: List[float], window: int = 60) -> Optional[float]:
    seg = closes[-window:] if len(closes) >= window else closes
    if len(seg) < 2:
        return None
    peak = seg[0]
    mdd = 0.0
    for c in seg:
        if c > peak:
            peak = c
        if peak > 0:
            mdd = min(mdd, c / peak - 1.0)
    return round(mdd * 100.0, 3)


def _vol_ratio(volumes: List[float], short: int = 5, long: int = 20) -> Optional[float]:
    if len(volumes) < long:
        return None
    a = sum(volumes[-short:]) / short
    b = sum(volumes[-long:]) / long
    if b <= 0:
        return None
    return round(a / b, 3)


def _dist_high(
    bars: List[Dict[str, Any]], closes: List[float], window: int = 60
) -> Optional[float]:
    highs = _series(bars, "high")[-window:]
    highs = [h for h in highs if h > 0]
    if not highs or not closes:
        return None
    hh = max(highs)
    if hh <= 0:
        return None
    return round((closes[-1] / hh - 1.0) * 100.0, 3)


def _range_pos(
    bars: List[Dict[str, Any]], closes: List[float], window: int = 60
) -> Optional[float]:
    highs = [h for h in _series(bars, "high")[-window:] if h > 0]
    lows = [lo for lo in _series(bars, "low")[-window:] if lo > 0]
    if not highs or not lows or not closes:
        return None
    hi, lo = max(highs), min(lows)
    if hi <= lo:
        return None
    return round((closes[-1] - lo) / (hi - lo), 3)


def compute_technical_factors(bars: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """从 OHLCV(按日期升序)计算全部确定性技术因子(纯函数, 失败安全, 数据不足→None)。"""
    closes = _closes(bars)
    volumes = _series(bars, "volume")
    return {
        "mom_20": _pct_return(closes, 20),
        "mom_60": _pct_return(closes, 60),
        "vol_20": _volatility(closes, 20),
        "ma20_gap": _ma_gap(closes, 20),
        "ma60_gap": _ma_gap(closes, 60),
        "rsi_14": _rsi(closes, 14),
        "max_dd_60": _max_drawdown(closes, 60),
        "vol_ratio": _vol_ratio(volumes, 5, 20),
        "dist_high_60": _dist_high(bars, closes, 60),
        "range_pos_60": _range_pos(bars, closes, 60),
    }


# ----------------------------- 缓存(自包含 SQLite, 失败安全) -----------------------------


def _db():
    from backend.storage.db import Database

    return Database()


def _ensure_table() -> None:
    global _ensured
    if _ensured:
        return
    with _write_lock:
        if _ensured:
            return
        conn = _db().conn
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_TABLE} (
                symbol TEXT NOT NULL,
                asof TEXT NOT NULL,
                computed_at TEXT NOT NULL,
                vector TEXT,
                PRIMARY KEY (symbol, asof)
            )
            """
        )
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{_TABLE}_sym ON {_TABLE}(symbol)")
        conn.commit()
        _ensured = True


def cache_vector(symbol: str, asof: str, vector: Dict[str, Any]) -> bool:
    """缓存一只标的某截面的因子向量。失败安全。"""
    try:
        _ensure_table()
        with _write_lock:
            conn = _db().conn
            conn.execute(
                f"INSERT OR REPLACE INTO {_TABLE} (symbol, asof, computed_at, vector) VALUES (?, ?, ?, ?)",
                (
                    str(symbol),
                    str(asof),
                    datetime.now().isoformat(),
                    json.dumps(vector, ensure_ascii=False),
                ),
            )
            conn.commit()
        _prune()
        return True
    except Exception:
        return False


def get_cached_vector(
    symbol: str, asof: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """取缓存因子向量(asof 缺省取最新)。失败/不存在返回 None。"""
    try:
        _ensure_table()
        conn = _db().conn
        if asof:
            r = conn.execute(
                f"SELECT vector FROM {_TABLE} WHERE symbol=? AND asof=?", (symbol, asof)
            ).fetchone()
        else:
            r = conn.execute(
                f"SELECT vector FROM {_TABLE} WHERE symbol=? ORDER BY asof DESC LIMIT 1",
                (symbol,),
            ).fetchone()
        return json.loads(r["vector"]) if r and r["vector"] else None
    except Exception:
        return None


def _prune(keep: int = _KEEP) -> None:
    try:
        with _write_lock:
            conn = _db().conn
            conn.execute(
                f"DELETE FROM {_TABLE} WHERE rowid NOT IN (SELECT rowid FROM {_TABLE} ORDER BY computed_at DESC LIMIT ?)",
                (keep,),
            )
            conn.commit()
    except Exception:
        pass


# ----------------------------- 研究流水线 -----------------------------


def _load_bars(symbol: str, days: int = 120) -> List[Dict[str, Any]]:
    """取本地行情(失败安全, 返回升序 bars)。"""
    try:
        from backend.price_store import get_prices, normalize_symbol

        norm = normalize_symbol(symbol) or symbol
        bars = get_prices(norm, limit=max(80, days), include_incompatible=True) or []
        return sorted(bars, key=lambda b: str(b.get("date") or ""))
    except Exception:
        return []


def compute_for_symbol(
    symbol: str,
    bars: Optional[List[Dict[str, Any]]] = None,
    use_cache: bool = True,
    loader: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """计算单标的的技术因子向量(失败安全), 并写缓存。``bars``/``loader`` 可注入(测试不触网)。"""
    if bars is None:
        bars = (loader or _load_bars)(symbol)
    factors = compute_technical_factors(bars)
    asof = (
        str(bars[-1].get("date"))[:10] if bars else datetime.now().strftime("%Y-%m-%d")
    )
    result = {
        "symbol": str(symbol),
        "asof": asof,
        "bar_count": len(bars or []),
        "factors": factors,
        "disclaimer": "因子为对历史量价结构的确定性度量, 不预测、不构成选股建议。",
    }
    if use_cache and bars:
        cache_vector(symbol, asof, factors)
    return result


def compute_matrix(
    symbols: List[str],
    use_cache: bool = True,
    loader: Optional[Callable[[str], List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """跨标的因子矩阵(研究流水线;逐标的失败安全)。返回行 = 每标的因子向量。"""
    rows: List[Dict[str, Any]] = []
    for raw in symbols or []:
        sym = str(raw).strip()
        if not sym:
            continue
        try:
            r = compute_for_symbol(sym, use_cache=use_cache, loader=loader)
            row = {
                "symbol": r["symbol"],
                "asof": r["asof"],
                "bar_count": r["bar_count"],
            }
            row.update(r["factors"])
            rows.append(row)
        except Exception:
            rows.append({"symbol": sym, "asof": "", "bar_count": 0})
    return {
        "factors": TECHNICAL_FACTORS,
        "rows": rows,
        "count": len(rows),
        "disclaimer": "因子矩阵仅描述历史横截面特征, 不预测、不构成选股建议。",
    }
