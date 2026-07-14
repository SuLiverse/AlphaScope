"""Task model router tests."""

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
