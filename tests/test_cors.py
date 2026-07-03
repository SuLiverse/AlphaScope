"""CORS 配置测试 — _cors_middleware_options 三分支 + allow_credentials 默认收紧。"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from backend.api import main


class TestCorsOptions:
    def test_allow_all_cors_branch(self, monkeypatch):
        monkeypatch.setenv("ALPHASCOPE_ALLOW_ALL_CORS", "1")
        opts = main._cors_middleware_options()
        assert opts["allow_origins"] == ["*"]
        assert opts["allow_origin_regex"] is None
        assert opts["allow_credentials"] is True

    def test_default_branch(self, monkeypatch):
        monkeypatch.delenv("ALPHASCOPE_ALLOW_ALL_CORS", raising=False)
        monkeypatch.delenv("ALPHASCOPE_CORS_ORIGINS", raising=False)
        opts = main._cors_middleware_options()
        assert opts["allow_origins"] == []
        assert "localhost" in opts["allow_origin_regex"]
        assert opts["allow_credentials"] is False  # 默认不带凭证(审计 C2)

    def test_explicit_origins_branch(self, monkeypatch):
        monkeypatch.delenv("ALPHASCOPE_ALLOW_ALL_CORS", raising=False)
        monkeypatch.setenv("ALPHASCOPE_CORS_ORIGINS", "https://a.com, https://b.com")
        opts = main._cors_middleware_options()
        assert opts["allow_origins"] == ["https://a.com", "https://b.com"]
        assert opts["allow_credentials"] is True  # 显式源时带凭证

    def test_custom_regex_without_origins(self, monkeypatch):
        monkeypatch.delenv("ALPHASCOPE_ALLOW_ALL_CORS", raising=False)
        monkeypatch.delenv("ALPHASCOPE_CORS_ORIGINS", raising=False)
        monkeypatch.setenv("ALPHASCOPE_CORS_ORIGIN_REGEX", r"^https://app\.example\.com$")
        opts = main._cors_middleware_options()
        assert opts["allow_origin_regex"] == r"^https://app\.example\.com$"
        assert opts["allow_credentials"] is False  # 无显式源, 仍不带凭证
