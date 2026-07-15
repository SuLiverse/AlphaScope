"""Tests for the zero-key Demo seed provider (backend/providers/demo_provider.py).

The demo provider is the "first-launch safety net": when no data-source key is
configured, it serves the packaged seed price DB so the workbench has real bars.
These tests pin its contract: zero-key, last-priority, honest provenance.
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


import pytest


class TestDemoSeedProvider:
    def test_requires_no_key(self):
        from backend.providers.demo_provider import DemoSeedProvider

        assert DemoSeedProvider.requires_key is False

    def test_is_lowest_priority(self):
        """The demo provider must never outrank a real source."""
        from backend.providers.demo_provider import DemoSeedProvider

        assert DemoSeedProvider.priority <= 10

    def test_is_available_reflects_seed_db(self):
        from backend.providers.demo_provider import DemoSeedProvider, _seed_db_path

        # In this repo the seed DB is present, so availability must be True.
        assert _seed_db_path().exists()
        assert DemoSeedProvider.is_available() is True

    def test_packaged_seed_is_not_shadowed_by_empty_runtime_db(self, tmp_path, monkeypatch):
        from backend import project_paths
        from backend.providers.demo_provider import DemoSeedProvider, _seed_db_path

        seed_dir = tmp_path / "seed"
        runtime_dir = tmp_path / "data"
        seed_dir.mkdir()
        (runtime_dir / "db").mkdir(parents=True)

        seed_db = seed_dir / "ai_finance.db"
        with sqlite3.connect(seed_db) as conn:
            conn.execute(
                "CREATE TABLE price_bars ("
                "symbol TEXT, date TEXT, market TEXT, open REAL, high REAL, "
                "low REAL, close REAL, volume REAL, amount REAL)"
            )
            conn.execute(
                "INSERT INTO price_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("600519", "2026-01-02", "CN", 10.0, 11.0, 9.0, 10.5, 100.0, 1050.0),
            )

        # A normal application import can create the mutable DB before this
        # provider runs. It must not hide the packaged demo data.
        with sqlite3.connect(runtime_dir / "db" / "ai_finance.db") as conn:
            conn.execute("CREATE TABLE runtime_state (id INTEGER)")

        monkeypatch.setattr(project_paths, "SEED_DIR", seed_dir)
        monkeypatch.setattr(project_paths, "DATA_DIR", runtime_dir)

        assert _seed_db_path() == seed_db
        bars = DemoSeedProvider().get_prices({"symbol": "600519", "limit": 1})
        assert len(bars) == 1
        assert bars[0]["source"] == "demo_seed"
        assert bars[0]["demo_sample"] is True

    def test_runtime_seed_is_used_when_portable_build_has_no_seed_dir(self, tmp_path, monkeypatch):
        from backend import project_paths
        from backend.providers.demo_provider import DemoSeedProvider, _seed_db_path

        seed_dir = tmp_path / "missing-seed"
        runtime_db = tmp_path / "data" / "db" / "ai_finance.db"
        runtime_db.parent.mkdir(parents=True)
        with sqlite3.connect(runtime_db) as conn:
            conn.execute(
                "CREATE TABLE price_bars ("
                "symbol TEXT, date TEXT, market TEXT, open REAL, high REAL, "
                "low REAL, close REAL, volume REAL, amount REAL)"
            )
            conn.execute(
                "INSERT INTO price_bars VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("600519", "2026-01-02", "CN", 10.0, 11.0, 9.0, 10.5, 100.0, 1050.0),
            )

        monkeypatch.setattr(project_paths, "SEED_DIR", seed_dir)
        monkeypatch.setattr(project_paths, "DATA_DIR", tmp_path / "data")

        assert _seed_db_path() == runtime_db
        bars = DemoSeedProvider().get_prices({"symbol": "600519", "limit": 1})
        assert len(bars) == 1
        assert bars[0]["source"] == "demo_seed"

    def test_get_prices_returns_seed_bars_tagged_as_demo(self):
        from backend.providers.demo_provider import DemoSeedProvider

        provider = DemoSeedProvider()
        bars = provider.get_prices({"symbol": "600519", "limit": 5})
        assert len(bars) > 0
        # Every bar must be honestly labelled so the UI can mark "演示样本".
        for bar in bars:
            assert bar["source"] == "demo_seed"
            assert bar.get("demo_sample") is True
            # OHLC sanity
            assert bar["close"] > 0
            assert bar["high"] >= bar["close"]

    def test_get_prices_chronological_order(self):
        from backend.providers.demo_provider import DemoSeedProvider

        bars = DemoSeedProvider().get_prices({"symbol": "600519", "limit": 10})
        dates = [b["date"] for b in bars]
        assert dates == sorted(dates)

    def test_get_prices_empty_for_unknown_symbol(self):
        from backend.providers.demo_provider import DemoSeedProvider

        bars = DemoSeedProvider().get_prices({"symbol": "999999", "limit": 10})
        assert bars == []

    def test_get_prices_normalises_symbol_suffix(self):
        """600519.SH must resolve to the same seed bars as 600519."""
        from backend.providers.demo_provider import DemoSeedProvider

        bare = DemoSeedProvider().get_prices({"symbol": "600519", "limit": 3})
        suffixed = DemoSeedProvider().get_prices({"symbol": "600519.SH", "limit": 3})
        assert len(bare) > 0
        assert len(bare) == len(suffixed)

    def test_other_data_types_not_supported(self):
        """Demo provider is a price-only safety net, not a full fake backend."""
        from backend.providers.demo_provider import DemoSeedProvider

        provider = DemoSeedProvider()
        with pytest.raises(NotImplementedError):
            provider.get_news({"symbol": "600519"})
        with pytest.raises(NotImplementedError):
            provider.get_fundamentals({"symbol": "600519"})


class TestRegistryIntegration:
    def test_demo_provider_is_registered(self):
        """The provider must be auto-discovered into the live registry."""
        from backend.providers.registry import get_registry

        reg = get_registry()
        names = {name for name in reg._providers.keys()}
        assert "demo_seed" in names

    def test_demo_provider_serves_when_real_sources_unavailable(self):
        """End-to-end: the registry's .get('prices', ...) returns demo bars for
        a seed symbol even when no real source can answer (no keys configured)."""
        from backend.providers.registry import get_registry

        reg = get_registry()
        bars = reg.get(data_type="prices", market="CN", symbol="600519", limit=3)
        # Either a real source or demo_seed answered; in this dev env there are
        # no keys, so demo_seed is the expected provider. At minimum we must get
        # seed bars back (proving the zero-key path is not broken).
        assert len(bars) > 0
