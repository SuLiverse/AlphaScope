"""Degradation Tests — 无 ChromaDB / 无 API Key 时的优雅降级"""

from __future__ import annotations

from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
def reset_vectorstore():
    """重置 VectorStore 单例，测试后恢复"""
    from backend.rag.vector_store import VectorStore

    original = VectorStore._instance
    VectorStore._instance = None
    yield
    VectorStore._instance = original


@pytest.mark.anyio
async def test_no_chromadb_app_starts(client, reset_vectorstore):
    """无 ChromaDB 时应用正常启动，health 端点正常"""
    from backend.rag.vector_store import VectorStore

    vs = VectorStore()
    with patch.object(vs, "_get_client", return_value=None):
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["success"] is True

        resp = await client.get("/")
        assert resp.status_code == 200


@pytest.mark.anyio
async def test_no_chromadb_vector_search_fails_clearly(reset_vectorstore):
    """无 ChromaDB 时向量搜索抛出明确 RuntimeError"""
    from backend.rag.vector_store import VectorStore

    vs = VectorStore()
    with patch.object(vs, "_get_client", return_value=None):
        with pytest.raises(RuntimeError, match="chromadb"):
            vs.get_collection("test")


def test_no_api_keys_create_client_fails_clearly():
    """无 API Key 时 create_client 抛出明确错误"""
    from backend.models.provider_gateway import create_client

    empty_vendors = {
        "deepseek": {"api_key": None, "base_url": "https://api.deepseek.com/v1"},
        "claude": {"api_key": None, "base_url": "https://api.anthropic.com"},
    }

    with patch("backend.models.provider_gateway.VENDORS", empty_vendors):
        with pytest.raises(RuntimeError, match="未配置完整"):
            create_client("deepseek")


def test_get_configured_provider_prefers_available_vendor(monkeypatch):
    """默认 LLM 路由应跳过未配置 key 的 DeepSeek，使用可用 provider。"""
    from backend.models import provider_gateway

    monkeypatch.setattr(provider_gateway, "_sync_persisted_providers_once", lambda: None)
    monkeypatch.delenv("AI_CHAT_PROVIDER", raising=False)
    monkeypatch.delenv("DEFAULT_LLM_PROVIDER", raising=False)
    monkeypatch.setattr(
        provider_gateway,
        "VENDORS",
        {
            "deepseek": {"api_key": "", "base_url": "https://api.deepseek.com/v1"},
            "sensenova": {
                "api_key": "sk-test",
                "base_url": "https://sensenova.example/v1",
            },
        },
    )

    assert provider_gateway.get_configured_provider() == (
        "sensenova",
        "deepseek-v4-flash",
    )


def test_get_configured_provider_respects_configured_preference(monkeypatch):
    """显式 provider 已配置时应优先使用显式配置。"""
    from backend.models import provider_gateway

    monkeypatch.setattr(provider_gateway, "_sync_persisted_providers_once", lambda: None)
    monkeypatch.setattr(
        provider_gateway,
        "VENDORS",
        {
            "deepseek": {"api_key": "", "base_url": "https://api.deepseek.com/v1"},
            "sensenova": {
                "api_key": "sk-test",
                "base_url": "https://sensenova.example/v1",
            },
        },
    )

    assert provider_gateway.get_configured_provider("sensenova") == (
        "sensenova",
        "deepseek-v4-flash",
    )


def test_get_configured_provider_prefers_saved_custom_provider(monkeypatch):
    """Saved UI providers should be usable even when their ID is arbitrary."""
    from backend.models import provider_gateway

    monkeypatch.setattr(provider_gateway, "_sync_persisted_providers_once", lambda: None)
    monkeypatch.delenv("AI_CHAT_PROVIDER", raising=False)
    monkeypatch.delenv("DEFAULT_LLM_PROVIDER", raising=False)
    monkeypatch.setattr(
        provider_gateway,
        "VENDORS",
        {
            "deepseek": {"api_key": "", "base_url": "https://api.deepseek.com/v1"},
            "1223": {
                "api_key": "sk-test",
                "base_url": "https://token.sensenova.cn/v1",
                "label": "商汤",
                "config_json": '{"models":["sensenova-6.7-flash-lite","deepseek-v4-flash"]}',
            },
        },
    )

    assert provider_gateway.get_configured_provider() == (
        "1223",
        "deepseek-v4-flash",
    )


def test_get_configured_provider_infers_sensenova_model_for_custom_url(monkeypatch):
    """Custom SenseNova-compatible endpoints should not fall back to deepseek-chat."""
    from backend.models import provider_gateway

    monkeypatch.setattr(provider_gateway, "_sync_persisted_providers_once", lambda: None)
    monkeypatch.setattr(
        provider_gateway,
        "VENDORS",
        {
            "deepseek": {"api_key": "", "base_url": "https://api.deepseek.com/v1"},
            "custom": {
                "api_key": "sk-test",
                "base_url": "https://token.sensenova.cn/v1",
                "label": "商汤",
            },
        },
    )

    assert provider_gateway.get_configured_provider() == (
        "custom",
        "deepseek-v4-flash",
    )


@pytest.mark.anyio
async def test_no_api_keys_app_starts(client):
    """无 API Key 时应用正常启动，health 端点正常"""
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
