"""Tests for Settings API — 模型 Provider 管理端点"""

from __future__ import annotations

import asyncio
import os
import socket
import sqlite3
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app

MOCK_PROVIDERS = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "type": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "api_key_masked": "sk-a...x9Zz",
        "enabled": True,
        "config_json": "{}",
    },
    {
        "id": "claude",
        "name": "Claude",
        "type": "openai_compatible",
        "base_url": "https://api.anthropic.com",
        "api_key_masked": "sk-a...bcde",
        "enabled": True,
        "config_json": "{}",
    },
]


def _mock_public_dns(monkeypatch):
    def fake_getaddrinfo(host, port=None, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture(autouse=True)
def mock_public_dns_for_settings_tests(monkeypatch):
    """Settings tests use documentation domains; treat them as public and resolvable."""
    _mock_public_dns(monkeypatch)


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


class _MemoryDatabase:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    @property
    def conn(self):
        return self._conn

    def transaction(self):
        # 真实 Database.transaction 是 _db_lock 包裹的上下文管理器; 内存测试 DB 单线程,
        # 无需真锁, 直接 yield 同一连接。
        from contextlib import contextmanager

        @contextmanager
        def _ctx():
            yield self._conn

        return _ctx()


@pytest.mark.anyio
async def test_list_providers(client):
    """GET /api/settings/providers 返回 provider 列表"""
    with patch("backend.settings_store.list_providers", return_value=MOCK_PROVIDERS):
        resp = await client.get("/api/settings/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["providers"]) == 2
    assert data["data"]["providers"][0]["id"] == "deepseek"


@pytest.mark.anyio
async def test_get_preferences(client):
    """GET /api/settings/preferences 返回应用偏好设置"""
    preferences = {
        "general": {"default_symbol": "600519", "refresh_interval": 60},
        "data": {"news_limit": 30},
    }
    with patch("backend.settings_store.get_app_preferences", return_value=preferences):
        resp = await client.get("/api/settings/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["preferences"]["general"]["default_symbol"] == "600519"


@pytest.mark.anyio
async def test_save_preferences(client):
    """PUT /api/settings/preferences 保存应用偏好设置"""
    saved = {
        "general": {"default_symbol": "000001", "refresh_interval": 15},
        "data": {"news_limit": 35},
    }
    with patch("backend.settings_store.save_app_preferences", return_value=saved):
        resp = await client.put(
            "/api/settings/preferences",
            json={
                "preferences": {
                    "general": {"default_symbol": "000001", "refresh_interval": 15}
                }
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["preferences"]["general"]["default_symbol"] == "000001"


@pytest.mark.anyio
async def test_save_provider(client):
    """POST /api/settings/providers 保存 provider"""
    saved = {
        "id": "test-provider",
        "name": "Test",
        "type": "openai_compatible",
        "base_url": "https://api.test.com/v1",
        "api_key": "sk-test123456789",
        "api_key_masked": "sk-t...6789",
        "enabled": True,
        "config_json": "{}",
    }
    with patch("backend.settings_store.save_provider", return_value=saved):
        resp = await client.post(
            "/api/settings/providers",
            json={
                "id": "test-provider",
                "name": "Test",
                "base_url": "https://api.test.com/v1",
                "api_key": "sk-test123456789",
            },
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["id"] == "test-provider"
    assert "api_key" not in data["data"]
    assert data["data"]["api_key_masked"] == "sk-t...6789"


@pytest.mark.anyio
async def test_save_provider_response_does_not_leak_plaintext_key(client):
    """POST /api/settings/providers 响应不回显明文 API Key"""
    saved = {
        "id": "test-provider",
        "name": "Test",
        "type": "openai_compatible",
        "base_url": "https://api.test.com/v1",
        "api_key": "sk-secret-plaintext",
        "api_key_masked": "sk-s...text",
        "enabled": True,
        "config_json": "{}",
    }
    with patch("backend.settings_store.save_provider", return_value=saved):
        resp = await client.post(
            "/api/settings/providers",
            json={
                "id": "test-provider",
                "name": "Test",
                "base_url": "https://api.test.com/v1",
                "api_key": "sk-secret-plaintext",
            },
        )

    data = resp.json()
    assert data["success"] is True
    assert "api_key" not in data["data"]
    assert "sk-secret-plaintext" not in resp.text
    assert data["data"]["api_key_masked"] == "sk-s...text"


@pytest.mark.anyio
async def test_save_provider_without_master_key_returns_actionable_failure(
    client, monkeypatch
):
    """POST save provider must not turn key-vault refusal into an HTTP 500."""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _mock_public_dns(monkeypatch)

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch("backend.settings_store._sync_to_gateway"),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "", "AI_FINANCE_ALLOW_DEV_KEY_FALLBACK": ""},
            clear=False,
        ),
    ):
        resp = await client.post(
            "/api/settings/providers",
            json={
                "id": "needs-vault-key",
                "name": "Needs Vault Key",
                "base_url": "https://api.example.com/v1",
                "api_key": "sk-needs-master-key",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "AI_FINANCE_MASTER_KEY" in data["error"]


@pytest.mark.anyio
async def test_delete_provider(client):
    """DELETE /api/settings/providers/{id} 删除 provider"""
    with patch("backend.settings_store.delete_provider", return_value=True):
        resp = await client.delete("/api/settings/providers/test-provider")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["deleted"] == "test-provider"


@pytest.mark.anyio
async def test_delete_provider_not_found(client):
    """DELETE 不存在的 provider 返回失败"""
    with patch("backend.settings_store.delete_provider", return_value=False):
        resp = await client.delete("/api/settings/providers/nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "不存在" in data["error"]


@pytest.mark.anyio
async def test_test_connection_success(client):
    """POST /api/settings/providers/{id}/test 连接成功"""
    result = {
        "success": True,
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "message": "连接成功",
    }
    with patch("backend.settings_store.test_connection", return_value=result):
        resp = await client.post("/api/settings/providers/deepseek/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "models" in data["data"]


@pytest.mark.anyio
async def test_test_connection_failure(client):
    """POST /api/settings/providers/{id}/test 连接失败"""
    result = {"success": False, "error": "连接失败: Connection refused"}
    with patch("backend.settings_store.test_connection", return_value=result):
        resp = await client.post("/api/settings/providers/deepseek/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "连接失败" in data["data"]["error"]


@pytest.mark.anyio
async def test_masked_key_in_response(client):
    """响应中 API Key 已脱敏"""
    with patch("backend.settings_store.list_providers", return_value=MOCK_PROVIDERS):
        resp = await client.get("/api/settings/providers")
    data = resp.json()
    for p in data["data"]["providers"]:
        assert "api_key_masked" in p
        assert p["api_key_masked"].startswith("sk-")
        assert "..." in p["api_key_masked"]
        # 不应包含完整 key
        assert "api_key" not in p or p.get("api_key", "") == ""


@pytest.mark.anyio
async def test_save_provider_rejects_private_base_url_response(client):
    """POST save provider 对不安全 Base URL 返回业务失败。"""

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch("backend.settings_store._sync_to_gateway"),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        os.environ.pop("ALLOW_LOCAL_LLM_BASE_URL", None)
        resp = await client.post(
            "/api/settings/providers",
            json={
                "id": "unsafe-api",
                "name": "Unsafe API",
                "base_url": "http://127.0.0.1:11434/v1",
                "api_key": "sk-local",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "默认禁止连接" in data["error"]


def test_save_provider_rejects_private_base_url_by_default():
    """保存 provider 时默认拒绝内网/本机 Base URL。"""
    from backend import settings_store

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch("backend.settings_store._sync_to_gateway"),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        os.environ.pop("ALLOW_LOCAL_LLM_BASE_URL", None)
        with pytest.raises(ValueError, match="默认禁止连接"):
            settings_store.save_provider(
                provider_id="unsafe-local",
                name="Unsafe Local",
                base_url="http://127.0.0.1:11434/v1",
                api_key="sk-local",
                enabled=True,
            )


def test_import_settings_skips_private_base_url_by_default():
    """导入设置时默认跳过内网/元数据服务 Base URL。"""
    from backend import settings_store

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch("backend.settings_store._sync_to_gateway"),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        os.environ.pop("ALLOW_LOCAL_LLM_BASE_URL", None)
        result = settings_store.import_settings(
            {
                "providers": [
                    {
                        "id": "metadata",
                        "name": "Metadata",
                        "base_url": "http://169.254.169.254/latest/meta-data",
                    },
                    {
                        "id": "public",
                        "name": "Public",
                        "base_url": "https://api.example.com/v1",
                    },
                ]
            }
        )
        providers = settings_store.list_providers()

    assert result["imported"] == 1
    assert [p["id"] for p in providers] == ["public"]


def test_save_provider_allows_local_base_url_with_explicit_opt_in():
    """显式 opt-in 时允许保存本机 LLM Base URL。"""
    from backend import settings_store

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch("backend.settings_store._sync_to_gateway"),
        patch.dict(
            os.environ,
            {
                "AI_FINANCE_MASTER_KEY": "test-settings-master-key",
                "ALLOW_LOCAL_LLM_BASE_URL": "1",
            },
            clear=False,
        ),
    ):
        provider = settings_store.save_provider(
            provider_id="local-ollama",
            name="Local Ollama",
            base_url="http://localhost:11434/v1",
            api_key="sk-local",
            enabled=True,
        )

    assert provider["base_url"] == "http://localhost:11434/v1"


def test_gateway_startup_sync_skips_private_base_url_by_default():
    """启动加载已存 provider 时默认跳过不安全 Base URL。"""
    from backend import settings_store
    from backend.models import provider_gateway

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        os.environ.pop("ALLOW_LOCAL_LLM_BASE_URL", None)
        settings_store._ensure_schema()
        conn.execute(
            """
            INSERT INTO model_providers
                (id, name, type, base_url, encrypted_api_key, enabled, config_json, created_at, updated_at)
            VALUES (?, ?, 'openai_compatible', ?, ?, 1, '{}', 1, 1)
            """,
            (
                "stored-unsafe",
                "Stored Unsafe",
                "http://10.0.0.8:8000/v1",
                settings_store.encrypt_key("sk-stored"),
            ),
        )
        conn.commit()
        provider_gateway.VENDORS.pop("stored-unsafe", None)
        provider_gateway._PERSISTED_PROVIDERS_SYNCED = False
        provider_gateway._PERSISTED_PROVIDERS_SYNCING = False

        provider_gateway._sync_persisted_providers_once()

    assert "stored-unsafe" not in provider_gateway.VENDORS


def test_save_provider_empty_key_preserves_existing_key():
    """更新已有 provider 时空 API Key 不清空旧密钥"""
    from backend import settings_store

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch("backend.settings_store._sync_to_gateway"),
        patch.dict(os.environ, {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"}),
    ):
        settings_store.save_provider(
            provider_id="keep-key",
            name="Keep Key",
            base_url="https://old.example.com/v1",
            api_key="sk-original-key",
            enabled=True,
        )
        settings_store.save_provider(
            provider_id="keep-key",
            name="Keep Key Updated",
            base_url="https://new.example.com/v1",
            api_key="",
            enabled=True,
        )
        provider = settings_store.get_provider("keep-key")

    assert provider is not None
    assert provider["api_key"] == "sk-original-key"
    assert provider["base_url"] == "https://new.example.com/v1"


def test_provider_names_are_cleaned_before_returning():
    """DB 中的历史乱码 provider 名称不应继续透出给前端或 gateway。"""
    from backend import settings_store

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch("backend.settings_store._sync_to_gateway"),
        patch.dict(os.environ, {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"}),
    ):
        settings_store.save_provider(
            provider_id="sensenova",
            name="ÉÌÌÀ",
            base_url="https://api.sensenova.cn/v1",
            api_key="sk-original-key",
            enabled=True,
        )
        providers = settings_store.list_providers()
        provider = settings_store.get_provider("sensenova")

    assert providers[0]["name"] == "商汤"
    assert provider is not None
    assert provider["name"] == "商汤"


def test_app_preferences_are_persisted_and_sanitized():
    """应用偏好设置应持久化，并对越界数值回落到允许范围。"""
    from backend import settings_store

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)):
        saved = settings_store.save_app_preferences(
            {
                "general": {
                    "default_symbol": "000001",
                    "refresh_interval": 1,
                    "theme": "unknown",
                },
                "data": {"news_limit": 500},
                "ai_models": {
                    "use_unified_model": False,
                    "unified": {"providerId": "mimo", "modelId": "mimo-v2.5"},
                    "routes": {
                        "vision_extract": {
                            "providerId": "mimo",
                            "modelId": "mimo-v2.5",
                        },
                        "report": {
                            "providerId": "deepseek",
                            "modelId": "deepseek-reasoner",
                        },
                    },
                },
                "unknown": {"x": 1},
            }
        )
        loaded = settings_store.get_app_preferences()

    assert saved["general"]["default_symbol"] == "000001"
    assert saved["general"]["refresh_interval"] == 10
    assert saved["general"]["theme"] == "dark"
    assert saved["data"]["news_limit"] == 100
    assert saved["ai_models"]["use_unified_model"] is False
    assert saved["ai_models"]["routes"]["vision_extract"]["modelId"] == "mimo-v2.5"
    assert loaded == saved


def test_mimo_model_is_detected_as_vision_capable():
    from backend.settings_store import _model_capabilities

    assert _model_capabilities("mimo-v2.5")["vision"] is True


def test_sync_to_gateway_removes_deleted_provider_and_cached_client():
    """Deleting a saved provider must remove runtime config and cached client."""
    from backend import settings_store
    from backend.models import provider_gateway

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        settings_store.save_provider(
            provider_id="custom-delete",
            name="Custom Delete",
            base_url="https://delete.example.com/v1",
            api_key="sk-delete",
            enabled=True,
        )
        provider_gateway._client_cache["custom-delete"] = object()

        assert "custom-delete" in provider_gateway.VENDORS
        assert "custom-delete" in provider_gateway._client_cache

        assert settings_store.delete_provider("custom-delete") is True

    assert "custom-delete" not in provider_gateway.VENDORS
    assert "custom-delete" not in provider_gateway._client_cache


def test_sync_to_gateway_disables_provider_and_clears_cached_client():
    """Disabling a provider must make it non-listable and non-callable at runtime."""
    from backend import settings_store
    from backend.models import provider_gateway

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        settings_store.save_provider(
            provider_id="custom-disabled",
            name="Custom Disabled",
            base_url="https://disabled.example.com/v1",
            api_key="sk-disabled",
            enabled=True,
            config_json='{"models":[{"id":"disabled-chat"}],"default_model":"disabled-chat"}',
        )
        provider_gateway._client_cache["custom-disabled"] = object()
        settings_store.save_provider(
            provider_id="custom-disabled",
            name="Custom Disabled",
            base_url="https://disabled.example.com/v1",
            api_key="",
            enabled=False,
        )

    assert "custom-disabled" not in provider_gateway.VENDORS
    assert "custom-disabled" not in provider_gateway._client_cache
    assert all(
        item["id"] != "custom-disabled" for item in provider_gateway.get_provider_list()
    )
    with pytest.raises(RuntimeError, match="未配置完整"):
        provider_gateway.create_client("custom-disabled")


def test_gateway_startup_sync_requires_complete_saved_provider_config():
    """Persisted custom providers with missing key/base_url must not reuse stale runtime config."""
    from backend import settings_store
    from backend.models import provider_gateway

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        settings_store._ensure_schema()
        conn.execute(
            """
            INSERT INTO model_providers
                (id, name, type, base_url, encrypted_api_key, enabled, config_json, created_at, updated_at)
            VALUES (?, ?, 'openai_compatible', ?, ?, 1, '{}', 1, 1)
            """,
            ("incomplete-custom", "Incomplete Custom", "", ""),
        )
        conn.commit()
        provider_gateway.VENDORS["incomplete-custom"] = {
            "api_key": "sk-stale",
            "base_url": "https://stale.example.com/v1",
            "supports_json_mode": True,
            "label": "Stale",
        }
        provider_gateway._PERSISTED_PROVIDERS_SYNCED = False
        provider_gateway._PERSISTED_PROVIDERS_SYNCING = False

        provider_gateway._sync_persisted_providers_once()

    assert "incomplete-custom" not in provider_gateway.VENDORS
    with pytest.raises(RuntimeError, match="未配置完整"):
        provider_gateway.create_client("incomplete-custom")


@pytest.mark.anyio
async def test_legacy_custom_provider_models_come_from_saved_config(client):
    """Legacy provider model endpoint should list saved custom provider models."""
    from backend import settings_store

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        settings_store.save_provider(
            provider_id="custom-models",
            name="Custom Models",
            base_url="https://models.example.com/v1",
            api_key="sk-models",
            enabled=True,
            config_json='{"models":[{"id":"alpha-chat","name":"Alpha Chat","contextWindow":8192}],"default_model":"alpha-chat"}',
        )
        resp = await client.get("/api/models/providers/custom-models/models")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["models"] == [
        {"id": "alpha-chat", "name": "Alpha Chat", "contextWindow": 8192}
    ]


def test_legacy_custom_provider_models_hide_disabled_saved_provider():
    """Disabled saved providers must not be listable through legacy model lookup."""
    from backend import settings_store
    from backend.models import provider_gateway

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    with (
        patch("backend.settings_store.Database", return_value=_MemoryDatabase(conn)),
        patch.dict(
            os.environ,
            {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
            clear=False,
        ),
    ):
        settings_store.save_provider(
            provider_id="disabled-models",
            name="Disabled Models",
            base_url="https://disabled-models.example.com/v1",
            api_key="sk-disabled-models",
            enabled=False,
            config_json='{"models":[{"id":"hidden-chat"}],"default_model":"hidden-chat"}',
        )
        models = provider_gateway.get_provider_models("disabled-models")

    assert models == []


def test_gateway_startup_sync_disabled_known_provider_suppresses_runtime_vendor():
    """Disabled saved known providers must override built-in/env runtime entries on startup."""
    from backend import settings_store
    from backend.models import provider_gateway

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    original = provider_gateway.VENDORS.get("deepseek")
    provider_gateway.VENDORS["deepseek"] = {
        "api_key": "sk-env-deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "supports_json_mode": True,
        "label": "DeepSeek",
    }
    try:
        with (
            patch(
                "backend.settings_store.Database", return_value=_MemoryDatabase(conn)
            ),
            patch.dict(
                os.environ,
                {"AI_FINANCE_MASTER_KEY": "test-settings-master-key"},
                clear=False,
            ),
        ):
            settings_store._ensure_schema()
            conn.execute(
                """
                INSERT INTO model_providers
                    (id, name, type, base_url, encrypted_api_key, enabled, config_json, created_at, updated_at)
                VALUES (?, ?, 'openai_compatible', ?, ?, 0, '{}', 1, 1)
                """,
                (
                    "deepseek",
                    "DeepSeek Disabled",
                    "https://api.deepseek.com/v1",
                    settings_store.encrypt_key("sk-saved-deepseek"),
                ),
            )
            conn.commit()
            provider_gateway._PERSISTED_PROVIDERS_SYNCED = False
            provider_gateway._PERSISTED_PROVIDERS_SYNCING = False

            provider_gateway._sync_persisted_providers_once()

        assert "deepseek" not in provider_gateway.VENDORS
        assert all(
            item["id"] != "deepseek" for item in provider_gateway.get_provider_list()
        )
        with pytest.raises(RuntimeError, match="未配置完整"):
            provider_gateway.create_client("deepseek")
    finally:
        if original is None:
            provider_gateway.VENDORS.pop("deepseek", None)
        else:
            provider_gateway.VENDORS["deepseek"] = original
        provider_gateway.clear_client_cache()


def test_delete_known_provider_override_restores_clean_builtin_and_clears_cache(
    monkeypatch,
):
    """Deleting a saved override for a known provider must remove stale patched key/url/cache."""
    from backend import settings_store
    from backend.models import provider_gateway

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _mock_public_dns(monkeypatch)

    original = provider_gateway.VENDORS.get("deepseek", {}).copy()
    provider_gateway.VENDORS["deepseek"] = {
        "api_key": "sk-env-deepseek",
        "base_url": "https://api.deepseek.com/v1",
        "supports_json_mode": True,
        "label": "DeepSeek",
    }
    try:
        with (
            patch(
                "backend.settings_store.Database", return_value=_MemoryDatabase(conn)
            ),
            patch.dict(
                os.environ,
                {
                    "AI_FINANCE_MASTER_KEY": "test-settings-master-key",
                    "DEEPSEEK_API_KEY": "sk-env-deepseek",
                },
                clear=False,
            ),
        ):
            settings_store.save_provider(
                provider_id="deepseek",
                name="Patched DeepSeek",
                base_url="https://patched.example.com/v1",
                api_key="sk-patched-deepseek",
                enabled=True,
            )
            provider_gateway._client_cache["deepseek"] = object()

            assert (
                provider_gateway.VENDORS["deepseek"]["api_key"] == "sk-patched-deepseek"
            )
            assert (
                provider_gateway.VENDORS["deepseek"]["base_url"]
                == "https://patched.example.com/v1"
            )

            assert settings_store.delete_provider("deepseek") is True

        assert provider_gateway.VENDORS["deepseek"]["api_key"] == "sk-env-deepseek"
        assert (
            provider_gateway.VENDORS["deepseek"]["base_url"]
            == "https://api.deepseek.com/v1"
        )
        assert "deepseek" not in provider_gateway._client_cache
    finally:
        if original:
            provider_gateway.VENDORS["deepseek"] = original
        else:
            provider_gateway.VENDORS.pop("deepseek", None)
        provider_gateway.clear_client_cache()


@pytest.mark.anyio
async def test_list_provider_models_times_out_quickly(client, monkeypatch):
    """Provider model listing should return a bounded timeout instead of blocking the loop."""
    from backend import settings_store

    class SlowModels:
        def list(self):
            import time

            time.sleep(1.0)
            return type("Resp", (), {"data": []})()

    class FakeOpenAI:
        def __init__(self, *args, **kwargs):
            self.models = SlowModels()

    monkeypatch.setattr("backend.api.settings.OpenAI", FakeOpenAI)
    monkeypatch.setattr("backend.api.settings.MODEL_LIST_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr("backend.api.settings.MODEL_LIST_WAIT_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(
        settings_store,
        "get_provider",
        lambda provider_id: {
            "id": provider_id,
            "api_key": "sk-test-secret",
            "base_url": "https://api.example.com/v1",
        },
    )

    resp = await asyncio.wait_for(
        client.get("/api/settings/providers/demo/models"), timeout=0.5
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "超时" in data["error"] or "timeout" in data["error"].lower()
    assert "sk-test-secret" not in resp.text
