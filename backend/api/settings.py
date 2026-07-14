"""设置 API - 模型 Provider 管理端点"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - optional dependency in tests
    OpenAI = None

from backend.models.provider_gateway import validate_custom_base_url
from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/settings", tags=["settings"])
MODEL_LIST_TIMEOUT_SECONDS = 15.0
MODEL_LIST_WAIT_TIMEOUT_SECONDS = 17.0


# ============== Request/Response Models ==============


class ProviderSaveRequest(BaseModel):
    id: str = Field(description="Provider ID，如 deepseek、claude")
    name: str = Field(description="显示名称")
    base_url: str = Field(description="API Base URL")
    api_key: str = Field(default="", description="API Key（留空则不更新）")
    enabled: bool = Field(default=True, description="是否启用")
    config_json: str | None = Field(default=None, description="Provider 扩展配置")


class ImportRequest(BaseModel):
    version: str = Field(default="1.0")
    providers: list[dict[str, Any]] = Field(default_factory=list)
    preferences: dict[str, Any] | None = Field(default=None)


class PreferencesSaveRequest(BaseModel):
    preferences: dict[str, Any] = Field(default_factory=dict)


def _public_provider(provider: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in provider.items() if key != "api_key"}


def _model_capabilities(model_id: str) -> dict[str, bool]:
    model = model_id.lower()
    embedding = any(
        token in model
        for token in (
            "embedding",
            "embed",
            "bge-",
            "bge_",
            "gte-",
            "gte_",
            "jina-embeddings",
            "text-embedding",
            "text_embedding",
        )
    )
    vision = any(
        token in model
        for token in (
            "vision",
            "visual",
            "multimodal",
            "multi-modal",
            "mimo",
            "omni",
            "vl",
            "llava",
            "qwen-vl",
            "gpt-4o",
            "gpt-4.1",
            "claude-3",
            "claude-sonnet",
            "claude-opus",
            "gemini",
        )
    )
    return {"vision": bool(vision and not embedding), "embedding": bool(embedding)}


def _public_model(model: Any) -> dict[str, Any]:
    model_id = str(getattr(model, "id", "") or "").strip()
    return {
        "id": model_id,
        "owned_by": str(getattr(model, "owned_by", "") or "").strip(),
        "capabilities": _model_capabilities(model_id),
    }


async def _list_provider_models_async(provider: dict[str, Any]) -> list[dict[str, Any]]:
    if OpenAI is None:
        raise RuntimeError("OpenAI client unavailable")

    def _load_models() -> list[dict[str, Any]]:
        client = OpenAI(
            api_key=provider["api_key"],
            base_url=validate_custom_base_url(provider["base_url"]),
            timeout=MODEL_LIST_TIMEOUT_SECONDS,
        )
        models = client.models.list()
        return [_public_model(m) for m in (getattr(models, "data", None) or []) if getattr(m, "id", "")]

    return await asyncio.wait_for(asyncio.to_thread(_load_models), timeout=MODEL_LIST_WAIT_TIMEOUT_SECONDS)


# ============== Endpoints ==============


@router.get("/providers")
async def list_providers():
    """列出所有 provider"""
    from backend.settings_store import list_providers as _list

    return ApiResponse(success=True, data={"providers": _list()})


@router.get("/local-llm-presets")
async def local_llm_presets():
    """本地模型预设 (Ollama / LM Studio / vLLM), 供设置页一键填入。"""
    from backend.models.local_presets import list_local_presets

    return ApiResponse(success=True, data={"presets": list_local_presets()})


class LocalProbeRequest(BaseModel):
    base_url: str = Field(description="本机 OpenAI 兼容 base_url")


@router.post("/local-llm-presets/probe")
async def probe_local_llm(req: LocalProbeRequest):
    """探测本机推理服务是否可达(短超时, 失败安全)。"""
    from backend.models.local_presets import probe_local_endpoint
    from backend.models.provider_gateway import validate_custom_base_url

    try:
        # 若未放行本地 base_url, 仍允许探测但标注 env 要求
        try:
            validate_custom_base_url(req.base_url)
            url_ok = True
            url_error = ""
        except ValueError as exc:
            url_ok = False
            url_error = str(exc)
        result = await asyncio.to_thread(probe_local_endpoint, req.base_url)
        result["url_validation_ok"] = url_ok
        if not url_ok:
            result["url_validation_error"] = url_error
        return ApiResponse(success=True, data=result)
    except Exception as e:  # noqa: BLE001
        return ApiResponse(success=False, error=str(e))


@router.get("/preferences")
async def get_preferences():
    """读取前端系统偏好设置"""
    from backend.settings_store import get_app_preferences

    return ApiResponse(success=True, data={"preferences": get_app_preferences()})


@router.put("/preferences")
async def save_preferences(req: PreferencesSaveRequest):
    """保存前端系统偏好设置"""
    from backend.settings_store import save_app_preferences

    preferences = save_app_preferences(req.preferences)
    return ApiResponse(success=True, data={"preferences": preferences})


@router.post("/providers")
async def save_provider(req: ProviderSaveRequest):
    """添加或更新 provider"""
    from backend.settings_store import save_provider as _save

    try:
        result = _save(
            provider_id=req.id,
            name=req.name,
            base_url=req.base_url,
            api_key=req.api_key,
            enabled=req.enabled,
            config_json=req.config_json,
        )
        return ApiResponse(success=True, data=_public_provider(result))
    except ValueError as exc:
        return ApiResponse(success=False, error=str(exc))
    except RuntimeError as exc:
        if "AI_FINANCE_MASTER_KEY" in str(exc):
            return ApiResponse(success=False, error=str(exc))
        raise


@router.delete("/providers/{provider_id}")
async def delete_provider(provider_id: str):
    """删除 provider"""
    from backend.settings_store import delete_provider as _delete

    deleted = _delete(provider_id)
    if not deleted:
        return ApiResponse(success=False, error="Provider 不存在")
    return ApiResponse(success=True, data={"deleted": provider_id})


@router.post("/providers/{provider_id}/test")
async def test_provider_connection(provider_id: str):
    """测试 provider 连接"""
    from backend.settings_store import test_connection as _test

    result = _test(provider_id)
    return ApiResponse(success=result["success"], data=result)


@router.get("/providers/{provider_id}/models")
async def list_provider_models(provider_id: str):
    """列出 provider 的模型"""
    from backend.settings_store import get_provider

    provider = get_provider(provider_id)
    if not provider:
        return ApiResponse(success=False, error="Provider 不存在")

    if not provider["api_key"] or not provider["base_url"]:
        return ApiResponse(success=False, error="Provider 未配置完整")
    try:
        safe_base_url = validate_custom_base_url(provider["base_url"])
    except ValueError as exc:
        return ApiResponse(success=False, error=str(exc))

    try:
        model_list = await _list_provider_models_async({**provider, "base_url": safe_base_url})
        return ApiResponse(success=True, data={"models": model_list})
    except asyncio.TimeoutError:
        return ApiResponse(success=False, error="获取模型列表超时")
    except Exception:
        return ApiResponse(success=False, error="获取模型列表失败")


@router.get("/export")
async def export_settings():
    """导出设置（脱敏）"""
    from backend.settings_store import export_settings as _export

    return ApiResponse(success=True, data=_export())


@router.post("/import")
async def import_settings(req: ImportRequest):
    """导入设置"""
    from backend.settings_store import import_settings as _import

    payload: dict[str, Any] = {"version": req.version, "providers": req.providers}
    if req.preferences is not None:
        payload["preferences"] = req.preferences
    result = _import(payload)
    return ApiResponse(success=True, data=result)
