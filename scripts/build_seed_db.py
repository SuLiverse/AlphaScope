#!/usr/bin/env python3
"""生成种子行情数据库 seed/ai_finance.db。

用东方财富 push2his 日线接口拉取一批常用股票近 ~1 年日线,写入与 backend
(backend/storage/db.py) 完全一致的 price_bars 表,供 build.py 打包进发布版,
让用户开箱即有正确的价格/涨跌幅;首次启动后行情源会自动补到最新交易日。

安全: 本脚本只写公开行情数据(price_bars),绝不写入任何 API key / provider 配置。

用法:
    python scripts/build_seed_db.py
"""

from __future__ import annotations

import json
import sqlite3
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = ROOT / "seed"
SEED_DB = SEED_DIR / "ai_finance.db"

# 常用蓝筹 / 热门股(A股) + 港股龙头
A_SHARES = [
    "600519",
    "000001",
    "000858",
    "600036",
    "601318",
    "600900",
    "000651",
    "002594",
    "300059",
    "300750",
    "688981",
    "601899",
    "600276",
    "000333",
    "002415",
    "600030",
    "601012",
    "300760",
    "688256",
    "688758",
    "300758",
    "301666",
    "600887",
    "000725",
    "002230",
    "600406",
    "601166",
    "000002",
    "600028",
    "601398",
    "601288",
    "600585",
    "002475",
    "300124",
    "600309",
    "601668",
    "600031",
    "000568",
    "002304",
    "600436",
]
HK_SHARES = ["00700", "00100", "00020", "09988", "03690"]

# 与 backend/storage/db.py 的 price_bars 主键、列保持一致(含 _ensure_tables 补的 fetched_at)
PRICE_BARS_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_bars (
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    market TEXT DEFAULT 'CN',
    frequency TEXT DEFAULT '1d',
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL DEFAULT 0,
    amount REAL DEFAULT 0,
    turnover REAL DEFAULT 0,
    amplitude REAL DEFAULT 0,
    change_pct REAL DEFAULT 0,
    adjust TEXT DEFAULT 'hfq',
    source TEXT DEFAULT 'akshare',
    fetched_at REAL DEFAULT 0,
    PRIMARY KEY (symbol, date, frequency)
)
"""


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _digits(sym: str) -> str:
    return "".join(ch for ch in str(sym or "") if ch.isdigit())


def _secid(sym: str) -> str:
    d = _digits(sym)
    if len(d) == 5:
        return f"116.{d}"  # 港股
    if d.startswith("6"):
        return f"1.{d}"  # 沪市
    return f"0.{d}"  # 深市/创业/北交所


def fetch_em_daily(sym: str, beg: str, end: str) -> list:
    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        f"?secid={_secid(sym)}&fields1=f1&fields2=f51,f52,f53,f54,f55,f56,f57"
        f"&klt=101&fqt=1&beg={beg}&end={end}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    return ((payload or {}).get("data") or {}).get("klines") or []


def main() -> int:
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    if SEED_DB.exists():
        SEED_DB.unlink()

    conn = sqlite3.connect(str(SEED_DB))
    conn.execute(PRICE_BARS_SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_bars(symbol)")

    end = time.strftime("%Y%m%d")
    beg = time.strftime("%Y%m%d", time.localtime(time.time() - 400 * 86400))

    syms = A_SHARES + HK_SHARES
    total = 0
    for i, sym in enumerate(syms, 1):
        try:
            klines = fetch_em_daily(sym, beg, end)
        except Exception as exc:  # 单只失败不影响整体
            print(f"  [{i:2}/{len(syms)}] {sym}: FAIL {type(exc).__name__} {str(exc)[:60]}")
            continue
        if not klines:
            print(f"  [{i:2}/{len(syms)}] {sym}: 无数据")
            continue
        market = "HK" if len(_digits(sym)) == 5 else "CN"
        prev = None
        rows = []
        for line in klines:
            p = str(line).split(",")
            if len(p) < 7:
                continue
            o, c, h, low_v = _float(p[1]), _float(p[2]), _float(p[3]), _float(p[4])
            vol, amt = _float(p[5]), _float(p[6])
            base = prev or o or c
            chg = round((c - base) / base * 100, 4) if base else 0.0
            amp = round((h - low_v) / base * 100, 4) if base else 0.0
            rows.append(
                (sym, p[0], market, "1d", o, h, low_v, c, vol, amt, 0.0, amp, chg, "", "eastmoney", time.time())
            )
            prev = c
        conn.executemany(
            "INSERT OR REPLACE INTO price_bars "
            "(symbol,date,market,frequency,open,high,low,close,volume,amount,"
            "turnover,amplitude,change_pct,adjust,source,fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        total += len(rows)
        print(f"  [{i:2}/{len(syms)}] {sym}: {len(rows):>4} 根, 末日={rows[-1][1] if rows else '-'}")
        time.sleep(0.2)  # 轻微限速,避免东财限频

    conn.commit()

    # 安全自检: 种子库绝不含任何 provider / key 表
    tabs = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    assert "model_providers" not in tabs, "种子库不得包含 model_providers 表!"
    nsym = conn.execute("SELECT COUNT(DISTINCT symbol) FROM price_bars").fetchone()[0]
    conn.close()

    print(f"\n[ok] 种子库: {SEED_DB}")
    print(f"     股票 {nsym} 只 / price_bars {total} 行 / 表 {tabs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
