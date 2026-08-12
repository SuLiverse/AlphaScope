"""前端 runtime-config.js 的唯一写入入口（launcher 与源码启动共用）。"""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def generate_local_api_token() -> str:
    return secrets.token_urlsafe(32)


def runtime_config_payload(
    *,
    api_base_url: str,
    local_api_token: str,
    api_key: str = "",
    packaged: bool = False,
) -> dict[str, Any]:
    return {
        "apiBaseUrl": api_base_url,
        "apiKey": api_key,
        "localApiToken": local_api_token,
        "packaged": packaged,
    }


def format_runtime_config_js(payload: dict[str, Any]) -> str:
    return "window.__ALPHASCOPE_CONFIG__ = " + json.dumps(payload, ensure_ascii=False) + ";\n"


def write_runtime_config_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_runtime_config_js(payload), encoding="utf-8")


def write_runtime_config_dir(
    web_dir: Path,
    *,
    api_port: int | None = None,
    api_base_url: str | None = None,
    local_api_token: str,
    api_key: str | None = None,
    packaged: bool = False,
) -> Path:
    """写入 ``web_dir/runtime-config.js``，返回文件路径。"""
    base = api_base_url or f"http://127.0.0.1:{int(api_port or 8000)}"
    payload = runtime_config_payload(
        api_base_url=base,
        local_api_token=local_api_token,
        api_key=api_key if api_key is not None else os.environ.get("VITE_API_KEY", ""),
        packaged=packaged,
    )
    out = web_dir / "runtime-config.js"
    write_runtime_config_file(out, payload)
    return out


def write_dev_runtime_configs(repo_root: Path, local_api_token: str) -> None:
    """Write source/Docker runtime config without publishing credentials.

    Every target here is a static web asset and may later be served on a
    non-loopback interface. The token stays in ``data/runtime`` (or ``.env``)
    and the browser gate stores user input in sessionStorage. Packaged desktop
    startup uses ``write_runtime_config_dir`` separately on a loopback-only
    server and retains its automatic token bootstrap.
    """
    base = os.environ.get("VITE_API_BASE_URL") or "http://localhost:8000"
    payload = runtime_config_payload(
        api_base_url=base,
        local_api_token="",
        api_key=os.environ.get("VITE_API_KEY", ""),
        packaged=False,
    )
    paths = [
        (repo_root / "apps/web/public/runtime-config.js", payload),
        (repo_root / "apps/web/dist/runtime-config.js", payload),
    ]
    shared_dir = os.environ.get("ALPHASCOPE_RUNTIME_CONFIG_DIR", "").strip()
    if shared_dir:
        paths.append((Path(shared_dir) / "runtime-config.js", payload))

    for path, path_payload in paths:
        try:
            write_runtime_config_file(path, path_payload)
        except OSError as exc:
            logger.debug("skip runtime-config write %s: %s", path, exc)
