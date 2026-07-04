"""Tests for dynamic provider discovery"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from backend.providers.base import BaseProvider
from backend.providers.akshare_provider import AkShareProvider
from backend.providers.registry import (
    ProviderRegistry,
    _scan_directory,
    _discover_and_register,
)


class TestScanDirectory:
    """Test the _scan_directory helper function."""

    def test_finds_provider_classes(self, tmp_path):
        """A module with a valid BaseProvider subclass should be discovered."""
        # Create a temporary package
        pkg = tmp_path / "test_pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        provider_module = pkg / "my_provider.py"
        provider_module.write_text(
            "from backend.providers.base import BaseProvider\n"
            "\n"
            "class MyTestProvider(BaseProvider):\n"
            '    name = "test_discovery"\n'
            '    markets = ["CN"]\n'
            '    data_types = ["news"]\n'
            "    priority = 50\n"
        )

        # We need to make the temp dir importable
        sys.path.insert(0, str(tmp_path))
        try:
            classes = _scan_directory(pkg, "test_pkg")
            assert len(classes) == 1
            assert classes[0].name == "test_discovery"
        finally:
            sys.path.remove(str(tmp_path))

    def test_skips_private_modules(self, tmp_path):
        """Modules starting with _ should be skipped."""
        pkg = tmp_path / "test_pkg2"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        # This should be skipped (starts with _)
        (pkg / "_template.py").write_text(
            "from backend.providers.base import BaseProvider\n"
            "class TemplateProvider(BaseProvider):\n"
            '    name = "template"\n'
            '    markets = ["CN"]\n'
            '    data_types = ["news"]\n'
        )

        # This should also be skipped
        (pkg / "__init__.py").write_text("")

        sys.path.insert(0, str(tmp_path))
        try:
            classes = _scan_directory(pkg, "test_pkg2")
            assert len(classes) == 0
        finally:
            sys.path.remove(str(tmp_path))

    def test_handles_import_error(self, tmp_path):
        """A module with import errors should be skipped, not crash."""
        pkg = tmp_path / "test_pkg3"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        (pkg / "broken.py").write_text("import nonexistent_module_that_does_not_exist\n")

        sys.path.insert(0, str(tmp_path))
        try:
            classes = _scan_directory(pkg, "test_pkg3")
            assert len(classes) == 0
        finally:
            sys.path.remove(str(tmp_path))

    def test_only_finds_baseprovider_subclasses(self, tmp_path):
        """Regular classes (not BaseProvider subclasses) should be ignored."""
        pkg = tmp_path / "test_pkg4"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")

        (pkg / "not_a_provider.py").write_text('class JustAClass:\n    name = "not_a_provider"\n')

        sys.path.insert(0, str(tmp_path))
        try:
            classes = _scan_directory(pkg, "test_pkg4")
            assert len(classes) == 0
        finally:
            sys.path.remove(str(tmp_path))

    def test_nonexistent_directory(self):
        """Scanning a non-existent directory should return empty list."""
        classes = _scan_directory(Path("/nonexistent/path"), "fake.package")
        assert classes == []


class TestDiscoverAndRegister:
    """Test the full discovery and registration flow."""

    def test_discovers_all_builtin_providers(self):
        """Should discover all built-in providers that have dependencies available."""
        registry = ProviderRegistry()
        _discover_and_register(registry)
        providers = registry.list_providers()
        names = {p["name"] for p in providers}

        # These should always be found (no external deps for import)
        expected = {"akshare", "baostock", "cls", "cninfo", "eastmoney", "tushare"}
        assert expected.issubset(names), f"Missing providers: {expected - names}"

    def test_discovers_commercial_stubs(self):
        """Commercial provider stubs should be discovered."""
        registry = ProviderRegistry()
        _discover_and_register(registry)
        providers = registry.list_providers()
        names = {p["name"] for p in providers}

        # At least some commercial stubs should be found
        commercial = {"wind", "ifind", "choice", "jy"}
        found_commercial = commercial & names
        assert len(found_commercial) > 0, "No commercial providers found"

    def test_origin_tracking(self):
        """Providers should have correct origin (builtin/custom)."""
        registry = ProviderRegistry()
        _discover_and_register(registry)
        providers = registry.list_providers()

        for p in providers:
            assert p["origin"] in ("builtin", "custom"), f"Invalid origin for {p['name']}: {p['origin']}"

        # All current providers should be builtin
        builtins = [p for p in providers if p["origin"] == "builtin"]
        assert len(builtins) > 0


class TestProviderRegistry:
    """Test ProviderRegistry methods."""

    def test_register_collision_warning(self):
        """Registering a provider with an existing name should log a warning."""
        registry = ProviderRegistry()

        class ProviderA(BaseProvider):
            name = "collision_test"
            markets = ["CN"]
            data_types = ["news"]
            priority = 50

        class ProviderB(BaseProvider):
            name = "collision_test"
            markets = ["CN"]
            data_types = ["news"]
            priority = 60

        registry.register(ProviderA())
        assert registry.get_provider("collision_test") is not None

        # Registering with same name should overwrite
        registry.register(ProviderB())
        p = registry.get_provider("collision_test")
        assert p.priority == 60

    def test_reload(self):
        """reload() should clear and re-discover all providers."""
        registry = ProviderRegistry()
        _discover_and_register(registry)
        initial_count = len(registry.list_providers())

        registry.reload()
        reloaded_count = len(registry.list_providers())

        assert reloaded_count == initial_count
        assert reloaded_count > 0

    def test_list_providers_includes_metadata(self):
        """list_providers() should include origin, cost_tier, freshness, requires_key."""
        registry = ProviderRegistry()
        _discover_and_register(registry)
        providers = registry.list_providers()

        assert len(providers) > 0
        p = providers[0]
        assert "origin" in p
        assert "cost_tier" in p
        assert "freshness" in p
        assert "requires_key" in p

    @pytest.mark.network
    def test_get_failover_still_works(self):
        """The get() method should still work with priority-based failover.

        Marked ``network``: ``registry.get("news", ...)`` performs a live
        provider fetch (no mock), which hangs/flakes without internet — so it
        is excluded in CI via ``-m "not network"``.
        """
        registry = ProviderRegistry()
        _discover_and_register(registry)

        # Should return a list (may be empty if no actual data fetching)
        result = registry.get("news", market="CN")
        assert isinstance(result, list)


def test_akshare_prices_fall_back_to_tencent_when_primary_empty():
    """AkShare 主行情接口为空时应使用 Tencent 历史行情兜底。"""
    provider = AkShareProvider()
    tx_df = pd.DataFrame(
        [
            {
                "date": "2026-05-22",
                "open": 1280.0,
                "high": 1290.0,
                "low": 1275.0,
                "close": 1285.0,
                "amount": 12850000.0,
            }
        ]
    )

    with (
        patch(
            "backend.providers.akshare_provider.ak.stock_zh_a_hist",
            return_value=pd.DataFrame(),
        ) as primary,
        # EastMoney sits between the primary feed and the Tencent fallback in the
        # chain (primary -> eastmoney -> tencent). Stub it empty so this test
        # deterministically exercises the Tencent leg instead of hitting the
        # live EastMoney endpoint.
        patch.object(provider, "_get_prices_from_eastmoney", return_value=[]),
        patch(
            "backend.providers.akshare_provider.ak.stock_zh_a_hist_tx",
            return_value=tx_df,
        ) as fallback,
    ):
        result = provider.get_prices({"symbol": "600519", "limit": 1})

    primary.assert_called_once()
    fallback.assert_called_once()
    assert result[0]["symbol"] == "600519"
    assert result[0]["date"] == "2026-05-22"
    assert result[0]["close"] == 1285.0
    assert result[0]["adjust"] == ""
    assert result[0]["source"] == "tencent"
