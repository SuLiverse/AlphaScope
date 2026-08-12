"""
行情数据获取工具
- 获取股票指定日期后的 N 个交易日收盘价
- 获取股票指定日期后区间收盘价序列(用于回撤/区间收益计算)
"""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


def _normalize_symbol(symbol: str) -> str:
    """将 symbol 转换为 akshare 格式。"""
    symbol = symbol.strip()
    # 如果已经带后缀，直接返回
    if symbol.endswith((".SH", ".SZ", ".BJ")):
        return symbol
    # 根据代码规则判断交易所
    if symbol.startswith("6"):
        return f"{symbol}.SH"
    elif symbol.startswith(("0", "3")):
        return f"{symbol}.SZ"
    elif symbol.startswith(("4", "8")):
        return f"{symbol}.BJ"
    return symbol


def _load_history(symbol: str, base_date: datetime) -> Optional[pd.DataFrame]:
    """加载 base_date 前后约 6 个月的日线行情。

    Returns:
        含 ``date``(YYYY-MM-DD 字符串)、``close``(float) 与 ``volume``(float,缺失补 0)
        列、按日期升序排列的 DataFrame;失败或为空时返回 None。
    """
    try:
        import akshare as ak
    except ImportError:
        return None

    norm_symbol = _normalize_symbol(symbol)
    code = norm_symbol.split(".")[0]

    start_dt = base_date - timedelta(days=180)
    end_dt = base_date + timedelta(days=45)
    start_date = start_dt.strftime("%Y%m%d")
    end_date = end_dt.strftime("%Y%m%d")

    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
    except Exception:
        return None

    if df is None or df.empty:
        return None

    df.columns = [str(c).strip().lower() for c in df.columns]
    date_col = next((c for c in df.columns if "date" in c or "日期" in c), None)
    close_col = next(
        (c for c in df.columns if c in ("close", "收盘", "收盘价", "closeprice")),
        None,
    )
    volume_col = next(
        (c for c in df.columns if c in ("volume", "成交量")),
        None,
    )
    if date_col is None or close_col is None:
        return None

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d"),
            "close": pd.to_numeric(df[close_col], errors="coerce"),
            "volume": pd.to_numeric(df[volume_col], errors="coerce") if volume_col else 0.0,
        }
    )
    out = out.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
    out["volume"] = out["volume"].where(pd.notna(out["volume"]), 0.0)
    return out if not out.empty else None


def get_price_after(symbol: str, date_str: str, days: int) -> float | None:
    """获取某股票在指定日期后 N 个交易日的收盘价。

    Args:
        symbol: 股票代码,如 "600519"
        date_str: 日期字符串,格式 "YYYY-MM-DD"
        days: N 个交易日

    Returns:
        收盘价,如果数据不足返回 None
    """
    if not symbol or not date_str or days <= 0:
        return None

    try:
        base_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None

    df = _load_history(symbol, base_date)
    if df is None:
        return None

    future = df[df["date"] > date_str].head(days)
    if len(future) < days:
        return None
    return float(future.iloc[-1]["close"])


def get_price_range(
    symbol: str,
    date_str: str,
    days: int,
) -> List[Tuple[str, float]]:
    """获取某股票在指定日期后 days 个交易日内的逐日收盘价序列。

    与 :func:`get_price_after` 不同,本函数返回完整序列(供回撤、区间收益等计算使用)。
    若实际可用交易日不足 days,会返回已有的部分;数据完全获取失败时返回空列表。

    Args:
        symbol: 股票代码,如 "600519"
        date_str: 起始日期字符串,格式 "YYYY-MM-DD"(不含当日)
        days: 期望的交易日数量

    Returns:
        [(date_str, close), ...] 按日期升序排列;失败或无数据返回 []
    """
    if not symbol or not date_str or days <= 0:
        return []

    try:
        base_date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return []

    df = _load_history(symbol, base_date)
    if df is None:
        return []

    future = df[df["date"] > date_str].head(days)
    if future.empty:
        return []

    return list(
        zip(
            future["date"].tolist(),
            [float(v) for v in future["close"].tolist()],
        )
    )


def get_recent_bars(symbol: str, count: int = 5) -> List[Dict[str, float | str]]:
    """获取最近 count 个交易日的 [{"date","close","volume"}] 序列(按日期升序)。

    供告警检查/行情工具使用;数据失败或为空返回 []。
    """
    if not symbol or count <= 0:
        return []

    base_date = datetime.now()
    df = _load_history(symbol, base_date)
    if df is None or df.empty:
        return []

    recent = df.tail(count)
    return [
        {
            "date": row["date"],
            "close": float(row["close"]),
            "volume": float(row["volume"]),
        }
        for _, row in recent.iterrows()
    ]


if __name__ == "__main__":
    # 简单自测
    print("Price fetcher loaded.")
    price = get_price_after("600519", "2024-01-02", 5)
    print(f"600519 after 5 trading days from 2024-01-02: {price}")
    series = get_price_range("600519", "2024-01-02", 10)
    print(f"600519 range (10 days): {len(series)} samples, last={series[-1] if series else None}")
