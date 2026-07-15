"""服务端任务级模型路由 — 便宜/强模型分流。

优先级:
1. 请求显式 global_ai_settings / agent 配置
2. 环境变量 ALPHASCOPE_ROUTE_<TASK>
3. 内置 tier 表 (standard=cheap, deep=strong)
4. config/models.yaml fallback provider

不替换前端路由; 作为后端默认解析器。
"""

from __future__ import annotations

import os
from typing import Any, Optional

# task → (tier, default provider, default model)
_TASK_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "chat": ("cheap", "deepseek", "deepseek-chat"),
    "news": ("cheap", "deepseek", "deepseek-chat"),
    "agent_default": ("cheap", "deepseek", "deepseek-chat"),
    "pre_screen": ("cheap", "deepseek", "deepseek-chat"),
    "standard_agent": ("cheap", "deepseek", "deepseek-chat"),
    "vision_extract": ("strong", "claude", "claude-sonnet-4-5"),
    "vision_reasoning": ("strong", "claude", "claude-sonnet-4-5"),
    "report": ("strong", "claude", "claude-sonnet-4-5"),
    "critic": ("strong", "claude", "claude-sonnet-4-5"),
    "chairman": ("strong", "claude", "claude-opus-4-7"),
    "deep_agent": ("strong", "deepseek", "deepseek-chat"),
}

_LOCAL_PACK_CHEAP = {
    "provider": "ollama",
    "model": "qwen2.5:7b",
    "base_url": "http://127.0.0.1:11434/v1",
}


def list_routing_packs() -> list[dict[str, Any]]:
    """本地/成本路由预设包(前端 Models 页可一键应用)。"""
    return [
        {
            "id": "local_first",
            "name": "本地优先",
            "description": "对话/普通 Agent 走 Ollama; Critic/主席仍建议云端强模型",
            "routes": {
                "chat": {"providerId": "ollama", "modelId": "qwen2.5:7b"},
                "agent_default": {"providerId": "ollama", "modelId": "qwen2.5:7b"},
                "news": {"providerId": "ollama", "modelId": "qwen2.5:7b"},
                "critic": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "chairman": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "report": {"providerId": "deepseek", "modelId": "deepseek-chat"},
            },
            "env_required": ["ALLOW_LOCAL_LLM_BASE_URL=1"],
        },
        {
            "id": "cost_saver",
            "name": "成本优先",
            "description": "全部默认 DeepSeek; 适合高频筛选",
            "routes": {
                "chat": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "agent_default": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "news": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "critic": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "chairman": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "report": {"providerId": "deepseek", "modelId": "deepseek-chat"},
            },
            "env_required": [],
        },
        {
            "id": "quality_first",
            "name": "质量优先",
            "description": "审稿/主席用更强模型(需对应 Key)",
            "routes": {
                "chat": {"providerId": "deepseek", "modelId": "deepseek-chat"},
                "agent_default": {"providerId": "claude", "modelId": "claude-sonnet-4-5"},
                "critic": {"providerId": "claude", "modelId": "claude-sonnet-4-5"},
                "chairman": {"providerId": "claude", "modelId": "claude-opus-4-7"},
                "report": {"providerId": "claude", "modelId": "claude-sonnet-4-5"},
            },
            "env_required": [],
        },
    ]


def resolve_model_for_task(
    task: str,
    *,
    global_ai_settings: Optional[dict[str, Any]] = None,
    force_cheap: bool = False,
) -> dict[str, str]:
    """解析任务模型。返回 {provider, model, tier, source}。"""
    task_key = (task or "agent_default").strip().lower()
    settings = global_ai_settings if isinstance(global_ai_settings, dict) else {}

    # 1) explicit nested settings: settings.routes.chat = {provider, model}
    routes = settings.get("routes") if isinstance(settings.get("routes"), dict) else {}
    if task_key in routes and isinstance(routes[task_key], dict):
        r = routes[task_key]
        prov = str(r.get("provider") or r.get("providerId") or "").strip()
        model = str(r.get("model") or r.get("modelId") or "").strip()
        if prov and model:
            return {"provider": prov, "model": model, "tier": "custom", "source": "settings.routes"}

    # 2) flat keys like settings.chairman = {provider, model}
    flat = settings.get(task_key)
    if isinstance(flat, dict):
        prov = str(flat.get("provider") or flat.get("providerId") or "").strip()
        model = str(flat.get("model") or flat.get("modelId") or "").strip()
        if prov and model:
            return {"provider": prov, "model": model, "tier": "custom", "source": "settings.flat"}

    # 3) env
    env_key = f"ALPHASCOPE_ROUTE_{task_key.upper()}"
    env_val = os.getenv(env_key, "").strip()
    if env_val and "/" in env_val:
        prov, model = env_val.split("/", 1)
        return {
            "provider": prov.strip(),
            "model": model.strip(),
            "tier": "env",
            "source": env_key,
        }

    # 4) defaults + force_cheap
    tier, prov, model = _TASK_DEFAULTS.get(task_key, _TASK_DEFAULTS["agent_default"])
    if force_cheap or tier == "cheap":
        return {"provider": "deepseek", "model": "deepseek-chat", "tier": "cheap", "source": "default"}
    return {"provider": prov, "model": model, "tier": tier, "source": "default"}


def should_force_cheap_by_budget() -> bool:
    """预算吃紧时强制便宜模型。"""
    try:
        from backend.models.model_registry import get_model_registry

        st = get_model_registry().check_budget("global")
        if not st.get("ok", True):
            return True
        # 用量超过日限额 80%
        used = float(st.get("used_ratio") or 0)
        if used >= 0.8:
            return True
    except Exception:
        return False
    return False
