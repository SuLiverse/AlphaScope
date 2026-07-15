from __future__ import annotations

import json

from backend.models import model_registry as module
from backend.models.model_registry import ModelRegistry, TokenBudget


def _budget() -> TokenBudget:
    return TokenBudget(daily_limit=1_000, monthly_limit=10_000, cost_limit_usd=10.0)


def test_budget_usage_persists_across_registry_restart(tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    monkeypatch.setenv("ALPHASCOPE_BUDGET_STATE_PATH", str(path))

    first = ModelRegistry()
    first.set_budget("global", _budget(), restore=True)
    first.record_usage("demo", 120, 30, 1.25)

    second = ModelRegistry()
    second.set_budget("global", _budget(), restore=True)
    status = second.check_budget("global")

    assert status["used_today"] == 150
    assert status["cost_today_usd"] == 1.25
    assert json.loads(path.read_text(encoding="utf-8"))["budgets"]["global"]["used_today"] == 150


def test_budget_usage_merges_across_live_registry_instances(tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    monkeypatch.setenv("ALPHASCOPE_BUDGET_STATE_PATH", str(path))

    first = ModelRegistry()
    second = ModelRegistry()
    first.set_budget("global", _budget(), restore=True)
    second.set_budget("global", _budget(), restore=True)

    first.record_usage("first", 60, 40, 0.5)
    second.record_usage("second", 120, 80, 1.0)

    restarted = ModelRegistry()
    restarted.set_budget("global", _budget(), restore=True)
    status = restarted.check_budget("global")
    assert status["used_today"] == 300
    assert status["cost_today_usd"] == 1.5


def test_budget_resets_daily_but_keeps_current_month_usage(tmp_path, monkeypatch):
    path = tmp_path / "budget.json"
    monkeypatch.setenv("ALPHASCOPE_BUDGET_STATE_PATH", str(path))
    monkeypatch.setattr(module, "_today_key", lambda: "2026-07-15")
    monkeypatch.setattr(module, "_month_key", lambda: "2026-07")

    registry = ModelRegistry()
    registry.set_budget("global", _budget(), restore=True)
    registry.record_usage("demo", 80, 20, 2.0)

    monkeypatch.setattr(module, "_today_key", lambda: "2026-07-16")
    status = registry.check_budget("global")

    assert status["used_today"] == 0
    assert status["cost_today_usd"] == 0.0
    assert registry._budgets["global"].used_this_month == 100
