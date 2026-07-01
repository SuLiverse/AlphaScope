"""
资金流向数据模块
- 个股每日资金流向（主力/超大单/大单/中单/小单）
- 大盘资金流向（上证/深证 + 主力分布）
"""

import warnings

warnings.filterwarnings("ignore")

import json
import re
import time
from datetime import datetime

import akshare as ak
import pandas as pd
import requests
from typing import Dict, Any, Optional

from backend.project_paths import CACHE_DIR

FUND_FLOW_CACHE_DIR = CACHE_DIR / "fund_flow"
FUND_FLOW_CACHE_TTL_SECONDS = 1800  # 30 分钟 TTL：避免每次冷访问都打 eastmoney（~2.6s）
EASTMONEY_FUND_FLOW_URL = (
    "http://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
)
EASTMONEY_FUND_FLOW_TIMEOUT = (2.0, 6.0)
EASTMONEY_HEADERS = {
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://quote.eastmoney.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
}
FLOW_NUMERIC_COLUMNS = [
    "主力净流入-净额",
    "小单净流入-净额",
    "中单净流入-净额",
    "大单净流入-净额",
    "超大单净流入-净额",
    "主力净流入-净占比",
    "小单净流入-净占比",
    "中单净流入-净占比",
    "大单净流入-净占比",
    "超大单净流入-净占比",
    "收盘价",
    "涨跌幅",
]


def infer_market(symbol: str) -> str:
    """根据股票代码推断市场前缀（用于 stock_individual_fund_flow）"""
    if symbol.startswith(("60", "68", "9")):
        return "sh"
    if symbol.startswith(("00", "30", "20")):
        return "sz"
    if symbol.startswith(("8", "4")):
        return "bj"
    return "sh"


def _cache_key(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", str(value or "").strip()) or "unknown"

from backend.utils import safe_call as _safe


def _cache_path(kind: str, key: str):
    return FUND_FLOW_CACHE_DIR / f"{kind}_{_cache_key(key)}.json"


def _symbol_code(symbol: str) -> str:
    match = re.search(r"\d{6}", str(symbol or ""))
    return match.group(0) if match else str(symbol or "").strip()


def _normalize_flow_frame(df: pd.DataFrame, days: int) -> pd.DataFrame:
    df = df.copy()
    if "日期" in df.columns:
        df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
        df = df.sort_values("日期")
    return df.tail(days).reset_index(drop=True)


def _write_flow_cache(kind: str, key: str, df: pd.DataFrame) -> None:
    if df is None or len(df) == 0:
        return
    try:
        out = df.copy()
        for col in out.columns:
            if pd.api.types.is_datetime64_any_dtype(out[col]):
                out[col] = out[col].dt.strftime("%Y-%m-%d")
        out = out.astype(object).where(pd.notnull(out), None)
        payload = {
            "saved_at": datetime.now().isoformat(),
            "source": getattr(df, "attrs", {}).get("source")
            or ("akshare" if kind == "market" else "eastmoney"),
            "columns": list(out.columns),
            "records": out.to_dict(orient="records"),
        }
        FUND_FLOW_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(kind, key).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _read_flow_cache(
    kind: str,
    key: str,
    days: int,
    *,
    fresh_only: bool = False,
) -> Optional[pd.DataFrame]:
    """读取资金流缓存。

    fresh_only=True 时只返回未过期的缓存（用于正常路径的 TTL 命中）；
    fresh_only=False 时返回任意存在的缓存（降级路径兜底，即使过期也用）。
    """
    try:
        path = _cache_path(kind, key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records") or []
        if not records:
            return None
        if fresh_only:
            try:
                saved_at = datetime.fromisoformat(payload["saved_at"])
            except (KeyError, ValueError):
                return None
            if (
                datetime.now() - saved_at
            ).total_seconds() > FUND_FLOW_CACHE_TTL_SECONDS:
                return None
        df = pd.DataFrame(records, columns=payload.get("columns") or None)
        df = _normalize_flow_frame(df, days)
        df.attrs["source"] = payload.get("source") or "cache"
        df.attrs["degraded"] = fresh_only  # TTL 命中视为新鲜，不算降级
        df.attrs["source_status"] = "cache" if not fresh_only else "cache"
        df.attrs["error"] = (
            "" if fresh_only else "Using cached fund-flow data; provider unavailable"
        )
        df.attrs["cached_at"] = payload.get("saved_at", "")
        return df
    except Exception:
        return None


def _eastmoney_get(url: str, params: dict[str, str]):
    with requests.Session() as session:
        session.trust_env = False
        return session.get(
            url,
            params=params,
            headers=EASTMONEY_HEADERS,
            timeout=EASTMONEY_FUND_FLOW_TIMEOUT,
        )


def _fetch_individual_fund_flow_eastmoney(symbol: str) -> Optional[pd.DataFrame]:
    """Fetch individual fund flow directly from Eastmoney with bounded network time."""

    code = _symbol_code(symbol)
    market = infer_market(code)
    market_map = {"sh": "1", "sz": "0", "bj": "0"}
    params = {
        "lmt": "0",
        "klt": "101",
        "secid": f"{market_map.get(market, '1')}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "_": str(int(time.time() * 1000)),
    }
    resp = _eastmoney_get(EASTMONEY_FUND_FLOW_URL, params)
    resp.raise_for_status()
    payload = resp.json()
    klines = (payload.get("data") or {}).get("klines") or []
    if not klines:
        return None

    rows = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 13:
            continue
        rows.append(
            {
                "日期": parts[0],
                "主力净流入-净额": parts[1],
                "小单净流入-净额": parts[2],
                "中单净流入-净额": parts[3],
                "大单净流入-净额": parts[4],
                "超大单净流入-净额": parts[5],
                "主力净流入-净占比": parts[6],
                "小单净流入-净占比": parts[7],
                "中单净流入-净占比": parts[8],
                "大单净流入-净占比": parts[9],
                "超大单净流入-净占比": parts[10],
                "收盘价": parts[11],
                "涨跌幅": parts[12],
            }
        )
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["日期"] = pd.to_datetime(df["日期"], errors="coerce")
    for col in FLOW_NUMERIC_COLUMNS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["日期"])
    if len(df) == 0:
        return None
    df.attrs["source"] = "eastmoney"
    return df


def fetch_individual_fund_flow(symbol: str, days: int = 30) -> Optional[pd.DataFrame]:
    """个股每日资金流向（先查 TTL 缓存，再打东方财富 HTTP 源，最后兜底过期缓存）"""
    code = _symbol_code(symbol)
    # 1) TTL 未过期 -> 直接命中，跳过网络
    cached = _read_flow_cache("individual", code, days, fresh_only=True)
    if cached is not None:
        return cached
    # 2) 打网络源
    df = _safe(_fetch_individual_fund_flow_eastmoney, code)
    if df is None or len(df) == 0:
        # 3) 网络失败 -> 兜底用过期缓存
        return _read_flow_cache("individual", code, days)
    df = _normalize_flow_frame(df, days)
    df.attrs["source"] = getattr(df, "attrs", {}).get("source") or "eastmoney"
    _write_flow_cache("individual", code, df)
    return df


def fetch_market_fund_flow(days: int = 30) -> Optional[pd.DataFrame]:
    """大盘资金流向（先查 TTL 缓存，再打 akshare，最后兜底过期缓存）"""
    cached = _read_flow_cache("market", "overview", days, fresh_only=True)
    if cached is not None:
        return cached
    df = _safe(ak.stock_market_fund_flow)
    if df is None or len(df) == 0:
        return _read_flow_cache("market", "overview", days)
    df = _normalize_flow_frame(df, days)
    df.attrs["source"] = getattr(df, "attrs", {}).get("source") or "akshare"
    _write_flow_cache("market", "overview", df)
    return df


def summarize_fund_flow(df: pd.DataFrame, recent_days: int = 5) -> Dict[str, Any]:
    """汇总最近 N 日资金流向（用于卡片+LLM）"""
    if df is None or len(df) == 0:
        return {}
    recent = df.tail(recent_days)

    def to_yi(x):
        return float(x) / 1e8

    last = df.iloc[-1]

    return {
        "recent_days": recent_days,
        "main_total_yi": to_yi(recent["主力净流入-净额"].sum()),
        "super_total_yi": to_yi(recent["超大单净流入-净额"].sum()),
        "large_total_yi": to_yi(recent["大单净流入-净额"].sum()),
        "medium_total_yi": to_yi(recent["中单净流入-净额"].sum()),
        "small_total_yi": to_yi(recent["小单净流入-净额"].sum()),
        "last_date": str(last["日期"].date())
        if hasattr(last["日期"], "date")
        else str(last["日期"]),
        "last_main_yi": to_yi(last["主力净流入-净额"]),
        "last_main_pct": float(last["主力净流入-净占比"]),
        "inflow_days": int((recent["主力净流入-净额"] > 0).sum()),
        "outflow_days": int((recent["主力净流入-净额"] < 0).sum()),
    }


def build_fund_flow_brief_for_llm(summary: Dict[str, Any], kind: str = "个股") -> str:
    """构造给 LLM 看的资金流向简报（红涨绿跌，正数=流入=利好）"""
    if not summary:
        return ""

    days = summary.get("recent_days", 5)
    main = summary.get("main_total_yi", 0)
    super_ = summary.get("super_total_yi", 0)
    large = summary.get("large_total_yi", 0)
    medium = summary.get("medium_total_yi", 0)
    small = summary.get("small_total_yi", 0)
    inflow_days = summary.get("inflow_days", 0)
    outflow_days = summary.get("outflow_days", 0)
    last_main = summary.get("last_main_yi", 0)
    last_pct = summary.get("last_main_pct", 0)

    direction = "净流入" if main > 0 else "净流出"

    return f"""【{kind}近{days}日资金流向】
- 主力合计{direction}: {main:+.2f}亿元（流入{inflow_days}天/流出{outflow_days}天）
- 超大单: {super_:+.2f}亿 | 大单: {large:+.2f}亿
- 中单: {medium:+.2f}亿 | 小单: {small:+.2f}亿（散户）
- 最新交易日（{summary.get("last_date", "")}）: 主力{last_main:+.2f}亿（占比 {last_pct:+.2f}%）"""


if __name__ == "__main__":
    print("=" * 70)
    print("个股资金流向 (600519, 近 10 日)")
    print("=" * 70)
    df = fetch_individual_fund_flow("600519", days=10)
    if df is not None:
        print(
            df[
                ["日期", "收盘价", "涨跌幅", "主力净流入-净额", "主力净流入-净占比"]
            ].to_string()
        )
        s = summarize_fund_flow(df, recent_days=5)
        print("\n--- 5 日汇总 ---")
        for k, v in s.items():
            print(f"  {k}: {v}")
        print("\n--- LLM brief ---")
        print(build_fund_flow_brief_for_llm(s, kind="贵州茅台"))

    print("\n" + "=" * 70)
    print("大盘资金流向 (近 5 日)")
    print("=" * 70)
    df_m = fetch_market_fund_flow(days=10)
    if df_m is not None:
        s_m = summarize_fund_flow(df_m, recent_days=5)
        print(build_fund_flow_brief_for_llm(s_m, kind="大盘"))
