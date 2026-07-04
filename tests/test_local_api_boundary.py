from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from httpx import ASGITransport, AsyncClient


def _reload_api_main(monkeypatch, token: str = "test-runtime-token"):
    monkeypatch.setenv("ALPHASCOPE_LOCAL_API_TOKEN", token)
    import backend.api.main as main

    return importlib.reload(main)


@pytest.mark.anyio
async def test_mutating_api_requires_per_run_local_token(monkeypatch):
    main = _reload_api_main(monkeypatch)
    transport = ASGITransport(app=main.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/settings/preferences",
            json={"preferences": {"general": {"default_symbol": "000001"}}},
        )

    assert resp.status_code == 401
    data = resp.json()
    assert data["success"] is False
    assert "local API token" in data["error"]


@pytest.mark.anyio
async def test_mutating_api_accepts_matching_per_run_local_token(monkeypatch):
    main = _reload_api_main(monkeypatch, token="expected-token")
    transport = ASGITransport(app=main.app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        with monkeypatch.context() as m:
            m.setattr(
                "backend.settings_store.save_app_preferences",
                lambda preferences: preferences,
            )
            resp = await client.put(
                "/api/settings/preferences",
                headers={"X-AlphaScope-Local-Token": "expected-token"},
                json={"preferences": {"general": {"default_symbol": "000001"}}},
            )

    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_launcher_runtime_config_contains_per_run_local_token(tmp_path, monkeypatch):
    import launcher

    monkeypatch.setattr(launcher, "is_frozen", lambda: True)
    launcher.write_runtime_config(tmp_path, api_port=8123, local_api_token="runtime-secret")

    config_text = (tmp_path / "runtime-config.js").read_text(encoding="utf-8")
    payload = json.loads(config_text.split(" = ", 1)[1].rstrip(";\n"))

    assert payload["apiBaseUrl"] == "http://127.0.0.1:8123"
    assert payload["localApiToken"] == "runtime-secret"
    assert payload["packaged"] is True


def test_launcher_generates_distinct_local_tokens():
    import launcher

    first = launcher.generate_local_api_token()
    second = launcher.generate_local_api_token()

    assert isinstance(first, str)
    assert len(first) >= 32
    assert first != second


@pytest.mark.anyio
async def test_sensitive_get_requires_token(monkeypatch):
    """token 已设时, 敏感 GET 端点(/api/conversations)无 token → 401(审计 C1: GET 不再全放行)。"""
    main = _reload_api_main(monkeypatch)
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/conversations")
    assert resp.status_code == 401
    assert "local API token" in resp.json()["error"]


@pytest.mark.anyio
async def test_sensitive_get_accepts_query_token(monkeypatch):
    """浏览器导航无法加 header, ?local_token= 也应通过认证(审计 C1: query param 兼容)。"""
    token = "nav-token-xyz"
    main = _reload_api_main(monkeypatch, token=token)
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/api/conversations?local_token={token}")
    assert resp.status_code != 401  # 认证通过(后续可能 200/404, 但不该是 401)


@pytest.mark.anyio
async def test_sensitive_get_accepts_header_token(monkeypatch):
    """敏感 GET 带 header token 也通过(确认 header 路径未被 query 回退破坏)。"""
    token = "hdr-token-xyz"
    main = _reload_api_main(monkeypatch, token=token)
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/conversations", headers={"X-AlphaScope-Local-Token": token})
    assert resp.status_code != 401


@pytest.mark.anyio
async def test_nonsensitive_get_passes_without_token(monkeypatch):
    """非敏感 GET(/health)即使 token 设了也不要求 token(保持 SAFE_METHODS 对普通 GET 的豁免)。"""
    main = _reload_api_main(monkeypatch)
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code != 401


@pytest.mark.anyio
async def test_wrong_query_token_rejected(monkeypatch):
    """错误的 query token 仍 401(防猜测)。"""
    main = _reload_api_main(monkeypatch, token="real-token")
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/conversations?local_token=wrong-token")
    assert resp.status_code == 401
