"""本地 API Token 引导：源码启动默认启用鉴权，避免裸奔。

策略
----
1. 已设置 ``ALPHASCOPE_LOCAL_API_TOKEN`` → 沿用。
2. ``ALPHASCOPE_ALLOW_OPEN_API=1`` → 明确允许无 token（仅开发/测试）。
3. 否则自动生成 token，写入环境变量 + 持久化文件 + 前端 runtime-config.js，
   使 Vite 开发态与打包态都能带上 ``X-AlphaScope-Local-Token``。

打包 launcher 仍会覆盖生成自己的 token；本模块负责「裸 uvicorn」场景。
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)

_TOKEN_ENV = "ALPHASCOPE_LOCAL_API_TOKEN"
_OPEN_ENV = "ALPHASCOPE_ALLOW_OPEN_API"
_OPEN_TRUTHY = {"1", "true", "yes", "on"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _token_file() -> Path:
    try:
        from backend.project_paths import DATA_DIR

        d = DATA_DIR / "runtime"
    except Exception:
        d = _repo_root() / "data" / "runtime"
    d.mkdir(parents=True, exist_ok=True)
    return d / "local_api_token.txt"


def _open_api_allowed() -> bool:
    # 空串视为未开启（测试里常用 setenv("", "") 模拟关闭）
    return os.environ.get(_OPEN_ENV, "").strip().lower() in _OPEN_TRUTHY


def _write_frontend_runtime_config(token: str) -> None:
    """把 token 写入 apps/web/public/runtime-config.js（Vite 开发态 index.html 会加载）。"""
    root = _repo_root()
    targets = [
        root / "apps" / "web" / "public" / "runtime-config.js",
        root / "apps" / "web" / "dist" / "runtime-config.js",
    ]
    payload = {
        "apiBaseUrl": os.environ.get("VITE_API_BASE_URL") or "http://localhost:8000",
        "apiKey": os.environ.get("VITE_API_KEY", ""),
        "localApiToken": token,
        "packaged": False,
    }
    body = "window.__ALPHASCOPE_CONFIG__ = " + json.dumps(payload, ensure_ascii=False) + ";\n"
    for path in targets:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
        except OSError as exc:
            logger.debug("skip runtime-config write %s: %s", path, exc)


def ensure_local_api_token() -> str:
    """确保进程内有可用的 local API token（或显式 open）。

    返回当前生效的 token 字符串；open 模式返回空串。
    """
    existing = os.environ.get(_TOKEN_ENV, "").strip()
    if existing:
        return existing

    if _open_api_allowed():
        logger.warning("ALPHASCOPE_ALLOW_OPEN_API 已开启：本地 API 无 token 鉴权。仅用于开发/测试，勿在局域网暴露。")
        return ""

    # 尝试读取上次生成的 token（同机重启保持前端配置可用）
    token_path = _token_file()
    try:
        if token_path.is_file():
            saved = token_path.read_text(encoding="utf-8").strip()
            if saved:
                os.environ[_TOKEN_ENV] = saved
                _write_frontend_runtime_config(saved)
                logger.info(
                    "已加载本地 API token（%s）。前端请使用 public/runtime-config.js 中的 localApiToken。",
                    token_path,
                )
                return saved
    except OSError as exc:
        logger.debug("read saved token failed: %s", exc)

    token = secrets.token_urlsafe(32)
    os.environ[_TOKEN_ENV] = token
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("无法持久化 local API token: %s", exc)

    _write_frontend_runtime_config(token)
    logger.warning(
        "已自动生成 ALPHASCOPE_LOCAL_API_TOKEN（源码启动默认鉴权）。"
        "已写入 %s 与 apps/web/public/runtime-config.js。"
        "若要关闭鉴权，设置 ALPHASCOPE_ALLOW_OPEN_API=1（不推荐）。",
        token_path,
    )
    return token
