"""Task model router tests."""

from backend.agents.base import AgentConfig, _resolve_agent_ai_config
from backend.models.task_router import list_routing_packs, resolve_model_for_task


def test_resolve_defaults():
    r = resolve_model_for_task("chat")
    assert r["provider"]
    assert r["model"]


def test_resolve_settings_routes():
    r = resolve_model_for_task(
        "critic",
        global_ai_settings={"routes": {"critic": {"providerId": "claude", "modelId": "claude-sonnet-4-5"}}},
    )
    assert r["provider"] == "claude"
    assert r["model"] == "claude-sonnet-4-5"


def test_force_cheap():
    r = resolve_model_for_task("chairman", force_cheap=True)
    assert r["tier"] == "cheap"


def test_routing_packs():
    packs = list_routing_packs()
    ids = {p["id"] for p in packs}
    assert "local_first" in ids
    assert "cost_saver" in ids


def test_agent_resolution_preserves_opted_out_config_from_agent_default_route():
    cfg = AgentConfig(
        key="technical",
        provider="gpt",
        model="gpt-5.2",
        api_key="gpt-only-key",
        base_url="https://gpt.example/v1",
        inherit_global_key=False,
    )

    provider, model, key, base_url = _resolve_agent_ai_config(
        cfg,
        {
            "routes": {
                "agent_default": {
                    "providerId": "ollama",
                    "modelId": "qwen2.5:7b",
                }
            }
        },
    )

    assert (provider, model) == ("gpt", "gpt-5.2")
    assert (key, base_url) == ("gpt-only-key", "https://gpt.example/v1")


def test_agent_resolution_preserves_opted_out_config_from_force_cheap_fallback():
    cfg = AgentConfig(
        key="technical",
        provider="gpt",
        model="gpt-5.2",
        api_key="gpt-only-key",
        base_url="https://gpt.example/v1",
        inherit_global_key=False,
    )

    assert _resolve_agent_ai_config(cfg, {"_force_cheap": True}) == (
        "gpt",
        "gpt-5.2",
        "gpt-only-key",
        "https://gpt.example/v1",
    )


def test_agent_resolution_uses_agent_default_route_when_inheriting():
    cfg = AgentConfig(key="technical", provider="gpt", model="gpt-5.2")

    provider, model, _key, _base_url = _resolve_agent_ai_config(
        cfg,
        {
            "routes": {
                "agent_default": {
                    "providerId": "ollama",
                    "modelId": "qwen2.5:7b",
                }
            }
        },
    )

    assert (provider, model) == ("ollama", "qwen2.5:7b")


def test_agent_resolution_prefers_per_agent_route():
    cfg = AgentConfig(key="technical", provider="gpt", model="gpt-5.2", inherit_global_key=False)

    provider, model, _key, _base_url = _resolve_agent_ai_config(
        cfg,
        {
            "routes": {
                "agent_default": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "technical": {"providerId": "claude", "modelId": "claude-sonnet-4-5"},
            }
        },
    )

    assert (provider, model) == ("claude", "claude-sonnet-4-5")


def test_agent_resolution_preserves_explicit_config_without_route(monkeypatch):
    monkeypatch.delenv("ALPHASCOPE_ROUTE_AGENT_DEFAULT", raising=False)
    monkeypatch.delenv("ALPHASCOPE_ROUTE_TECHNICAL", raising=False)
    cfg = AgentConfig(key="technical", provider="gpt", model="gpt-5.2", inherit_global_key=False)

    assert _resolve_agent_ai_config(cfg, {})[:2] == ("gpt", "gpt-5.2")
