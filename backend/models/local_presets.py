"""本地 LLM 预设 (Ollama / LM Studio / 兼容 OpenAI 端点)。

桌面用户一键拿到可填的 base_url + 模型名; 真正启用需:
1. 本机已启动 Ollama/LM Studio
2. 环境变量 ALLOW_LOCAL_LLM_BASE_URL=1 (SSRF 防护显式放行)
3. 在设置页保存为 custom provider

纯数据 + 健康探测(可选),失败安全。
"""

from __future__ import annotations

import os
from typing import Any

from backend.models.provider_gateway import create_ssrf_safe_http_client, validate_local_llm_base_url

LOCAL_PRESETS: list[dict[str, Any]] = [
    {
        "id": "ollama",
        "name": "Ollama (本地)",
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key_placeholder": "ollama",
        "default_model": "qwen2.5:7b",
        "models": ["qwen2.5:7b", "qwen2.5:14b", "llama3.1:8b", "deepseek-r1:8b"],
        "notes": "需本机安装并运行 Ollama; 设置 ALLOW_LOCAL_LLM_BASE_URL=1",
    },
    {
        "id": "lmstudio",
        "name": "LM Studio (本地)",
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key_placeholder": "lm-studio",
        "default_model": "local-model",
        "models": ["local-model"],
        "notes": "在 LM Studio 开启本地 server (默认 1234); 设置 ALLOW_LOCAL_LLM_BASE_URL=1",
    },
    {
        "id": "vllm",
        "name": "vLLM / OpenAI 兼容",
        "base_url": "http://127.0.0.1:8001/v1",
        "api_key_placeholder": "EMPTY",
        "default_model": "default",
        "models": ["default"],
        "notes": "任意 OpenAI-compatible 本地推理服务",
    },
]


def list_local_presets() -> list[dict[str, Any]]:
    allow = os.getenv("ALLOW_LOCAL_LLM_BASE_URL", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return [
        {
            **p,
            "local_base_url_allowed": allow,
            "env_hint": "ALLOW_LOCAL_LLM_BASE_URL=1" if not allow else "local base URL allowed",
        }
        for p in LOCAL_PRESETS
    ]


def probe_local_endpoint(base_url: str, timeout: float = 1.5) -> dict[str, Any]:
    """Probe ``/models`` on an explicitly enabled loopback endpoint."""
    try:
        safe_base_url = validate_local_llm_base_url(base_url)
    except ValueError:
        return {"available": False, "error": "url_not_allowed"}

    url = safe_base_url.rstrip("/") + "/models"
    try:
        bounded_timeout = max(0.1, min(float(timeout), 5.0))
        with create_ssrf_safe_http_client(safe_base_url, timeout=bounded_timeout, local_only=True) as client:
            with client.stream("GET", url, headers={"User-Agent": "AlphaScope-local-probe"}) as resp:
                if 300 <= resp.status_code < 400:
                    return {"available": False, "error": "redirect_not_allowed"}
                # Do not read the body: probes expose only reachability and status.
                status_code = resp.status_code
                if not 200 <= status_code < 300:
                    return {
                        "available": False,
                        "error": "probe_failed",
                        "status_code": status_code,
                    }
            return {
                "available": True,
                "status_code": status_code,
            }
    except Exception:  # noqa: BLE001
        return {"available": False, "error": "probe_failed"}
