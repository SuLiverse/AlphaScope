"""Demo Provider — serves the packaged seed price database with zero API keys.

Purpose
-------
On first launch, before the user has configured any data-source key, the app
would otherwise show empty price charts and a broken workbench. This provider
reads the **bundled seed database** (``seed/ai_finance.db`` → shipped at
``data/db/ai_finance.db``) so that the ~10 blue-chip symbols have real
historical bars out of the box.

Design rules (from the honest-backtest / 不用静态样本伪装后端结果 principle):
- This provider is **always last-priority** (priority = 5) so a configured real
  source (akshare/tushare/eastmoney) always wins. It only answers when nothing
  else is available.
- ``requires_key = False`` and ``is_available()`` checks the seed DB file exists.
- ``get_prices`` returns seed bars tagged ``source="demo_seed"`` and marks
  ``demo_sample=True`` so the frontend can clearly label "演示样本" — it never
  masquerades as live data.
- News / fundamentals / other types raise ``NotImplementedError``: the demo
  provider is a price-only safety net, not a full fake backend.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from .base import BaseProvider

logger = logging.getLogger(__name__)


def _seed_db_path() -> Path:
    """Locate the bundled seed DB without preferring mutable runtime state."""
    try:
        from backend.project_paths import SEED_DIR

        packaged = SEED_DIR / "ai_finance.db"
        if packaged.exists():
            return packaged
    except Exception:
        pass

    # Portable builds copy the seed into the runtime data directory and do not
    # ship a separate seed directory.
    try:
        from backend.project_paths import DATA_DIR

        runtime = DATA_DIR / "db" / "ai_finance.db"
        if runtime.exists():
            return runtime
    except Exception:
        pass
    return Path("data/db/ai_finance.db")


class DemoSeedProvider(BaseProvider):
    """Zero-key fallback provider backed by the packaged seed price DB."""

    name = "demo_seed"
    markets = ["CN", "HK", "ALL"]
    data_types = ["prices"]
    priority = 5  # always below real sources (akshare=60, eastmoney=70, ...)
    license_level = "research_only"
    data_class = "price"
    freshness = "daily"
    cost_tier = "free"
    rate_limit: dict = {"per_minute": 120, "per_day": None}
    requires_key = False

    @classmethod
    def is_available(cls) -> bool:
        """Available only when the seed DB file actually exists on disk."""
        try:
            return _seed_db_path().exists()
        except Exception:
            return False

    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        """Return seed bars for the requested symbol, clearly tagged as demo.

        The seed DB stores A-share / HK daily bars; we read by symbol and honour
        the limit/window kwargs the registry forwards.
        """
        symbol = str(query.get("symbol", "")).strip()
        if not symbol:
            return []
        # Normalise to the 6-digit form the seed table uses.
        try:
            from backend.price_store import normalize_symbol

            sym = normalize_symbol(symbol)
        except Exception:
            # Strip common suffixes if price_store isn't importable for some reason.
            sym = "".join(ch for ch in symbol.upper() if ch.isdigit())[:6]

        limit = int(query.get("limit", 250) or 250)

        db_path = _seed_db_path()
        if not db_path.exists():
            logger.debug("[demo_seed] seed DB missing: %s", db_path)
            return []

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                rows = conn.execute(
                    "SELECT symbol, date, market, open, high, low, close, volume, amount "
                    "FROM price_bars WHERE symbol=? ORDER BY date DESC LIMIT ?",
                    (sym, limit),
                ).fetchall()
            finally:
                conn.close()
        except Exception as e:
            logger.warning("[demo_seed] read failed for %s: %s", sym, e)
            return []

        if not rows:
            return []

        bars: list[dict[str, Any]] = []
        for r in rows:
            bars.append(
                {
                    "symbol": r[0],
                    "date": r[1],
                    "market": r[2] or "CN",
                    "frequency": "1d",
                    "open": float(r[3] or 0),
                    "high": float(r[4] or 0),
                    "low": float(r[5] or 0),
                    "close": float(r[6] or 0),
                    "volume": float(r[7] or 0),
                    "amount": float(r[8] or 0),
                    "source": "demo_seed",
                    "demo_sample": True,
                    # clearly-labelled provenance for the frontend / report
                }
            )
        # Return chronological order (engine expects ascending by date).
        bars.reverse()
        return bars
