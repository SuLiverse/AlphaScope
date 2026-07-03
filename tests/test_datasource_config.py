"""datasource_config.get_active_key 测试 — provider 从 credential 表取 key(审计 C6)。"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_get_active_key_from_credential(monkeypatch):
    """表有 key → 直接返回, 不查 env。"""
    monkeypatch.setattr(
        "backend.datasource_config.get_credential",
        lambda n: {"api_key": "sk-from-table"} if n == "tushare" else None,
    )
    from backend.datasource_config import get_active_key

    assert get_active_key("tushare", "TUSHARE_TOKEN") == "sk-from-table"


def test_get_active_key_fallback_env(monkeypatch):
    """表无 key → 回退 os.environ(.env 自填兼容)。"""
    monkeypatch.setattr("backend.datasource_config.get_credential", lambda n: None)
    monkeypatch.setenv("TUSHARE_TOKEN", "sk-from-env")
    from backend.datasource_config import get_active_key

    assert get_active_key("tushare", "TUSHARE_TOKEN") == "sk-from-env"


def test_get_active_key_empty(monkeypatch):
    """表无 + env 无 → 空串。"""
    monkeypatch.setattr("backend.datasource_config.get_credential", lambda n: None)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    from backend.datasource_config import get_active_key

    assert get_active_key("tushare", "TUSHARE_TOKEN") == ""


def test_tushare_provider_gets_key_from_table(monkeypatch):
    """TushareProvider __init__ 从 get_active_key 取 key(不再 os.getenv)。"""
    monkeypatch.setattr(
        "backend.datasource_config.get_credential",
        lambda n: {"api_key": "sk-tushare-table"} if n == "tushare" else None,
    )
    from backend.providers.tushare_provider import TushareProvider

    p = TushareProvider()
    assert p._token == "sk-tushare-table"


def test_choice_provider_gets_key_from_table(monkeypatch):
    """ChoiceProvider __init__ 从 get_active_key 取 key。"""
    monkeypatch.setattr(
        "backend.datasource_config.get_credential",
        lambda n: {"api_key": "sk-choice-table"} if n == "choice" else None,
    )
    from backend.providers.commercial.choice_provider import ChoiceProvider

    p = ChoiceProvider()
    assert p._api_key == "sk-choice-table"


def test_provider_falls_back_to_env(monkeypatch):
    """表无 key 时, provider 经 fallback_env 读 .env 自填。"""
    monkeypatch.setattr("backend.datasource_config.get_credential", lambda n: None)
    monkeypatch.setenv("CHOICE_API_KEY", "sk-choice-env")
    from backend.providers.commercial.choice_provider import ChoiceProvider

    p = ChoiceProvider()
    assert p._api_key == "sk-choice-env"
