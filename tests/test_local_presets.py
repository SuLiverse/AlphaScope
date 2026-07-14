"""本地 LLM 预设测试。"""

from __future__ import annotations

from backend.models.local_presets import list_local_presets, probe_local_endpoint


def test_list_presets_contains_ollama_and_lmstudio():
    presets = list_local_presets()
    ids = {p["id"] for p in presets}
    assert "ollama" in ids
    assert "lmstudio" in ids
    for p in presets:
        assert p["base_url"].startswith("http")
        assert "local_base_url_allowed" in p


def test_probe_unreachable_is_safe():
    # 极不可能存在的端口
    r = probe_local_endpoint("http://127.0.0.1:9", timeout=0.3)
    assert r["available"] is False
    assert "error" in r
