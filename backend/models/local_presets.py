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
    """轻量探测 /models; 失败返回 available=False, 不抛。"""
    url = (base_url or "").rstrip("/") + "/models"
    try:
        import urllib.request

        req = urllib.request.Request(url, method="GET", headers={"User-Agent": "AlphaScope-local-probe"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - 用户显式本机探测
            body = resp.read(2000).decode("utf-8", errors="replace")
            return {
                "available": True,
                "status_code": getattr(resp, "status", 200),
                "preview": body[:200],
            }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": type(exc).__name__, "detail": str(exc)[:200]}
