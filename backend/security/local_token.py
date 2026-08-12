"""本地 API Token 引导：源码启动默认启用鉴权，避免裸奔。

策略
----
1. 已设置 ``ALPHASCOPE_LOCAL_API_TOKEN`` → 沿用。
2. ``ALPHASCOPE_ALLOW_OPEN_API=1`` → 明确允许无 token（仅开发/测试）。
3. 否则自动生成 token，写入环境变量 + 持久化文件 + 前端 runtime-config.js。

打包 launcher 使用同一套 ``runtime_config`` / ``generate_local_api_token``。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from backend.security.runtime_config import generate_local_api_token, write_dev_runtime_configs

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
    return os.environ.get(_OPEN_ENV, "").strip().lower() in _OPEN_TRUTHY


def ensure_local_api_token() -> str:
    """确保进程内有可用的 local API token（或显式 open）。

    返回当前生效的 token 字符串；open 模式返回空串。
    宜在 FastAPI lifespan 中调用，避免 import 副作用。
    """
    existing = os.environ.get(_TOKEN_ENV, "").strip()
    if existing:
        write_dev_runtime_configs(_repo_root(), existing)
        return existing

    if _open_api_allowed():
        logger.warning("ALPHASCOPE_ALLOW_OPEN_API 已开启：本地 API 无 token 鉴权。仅用于开发/测试，勿在局域网暴露。")
        write_dev_runtime_configs(_repo_root(), "")
        return ""

    token_path = _token_file()
    try:
        if token_path.is_file():
            saved = token_path.read_text(encoding="utf-8").strip()
            if saved:
                os.environ[_TOKEN_ENV] = saved
                write_dev_runtime_configs(_repo_root(), saved)
                logger.info(
                    "已加载本地 API token（%s）。前端首次连接时需在令牌引导页输入。",
                    token_path,
                )
                return saved
    except OSError as exc:
        logger.debug("read saved token failed: %s", exc)

    token = generate_local_api_token()
    os.environ[_TOKEN_ENV] = token
    try:
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(token + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("无法持久化 local API token: %s", exc)

    write_dev_runtime_configs(_repo_root(), token)
    logger.warning(
        "已自动生成 ALPHASCOPE_LOCAL_API_TOKEN（源码启动默认鉴权）。"
        "已写入 %s；静态 runtime-config.js 不包含该令牌。"
        "若要关闭鉴权，设置 ALPHASCOPE_ALLOW_OPEN_API=1（不推荐）。",
        token_path,
    )
    return token
