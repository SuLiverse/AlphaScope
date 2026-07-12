"""Paths for source checkouts, frozen builds, and installed wheels.

Repository and frozen builds keep their existing project-local layout. A wheel
uses packaged read-only assets while placing mutable state in the user's data
directory instead of ``site-packages``.
"""

from __future__ import annotations

import os
import shutil
import sys
from importlib.metadata import PackageNotFoundError, files
from pathlib import Path


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name, "").strip()
    return Path(value).expanduser() if value else None


def _installed_asset_root() -> Path:
    """Locate setuptools ``data-files`` regardless of the pip install scheme."""
    try:
        for entry in files("alphascope") or ():
            normalized = str(entry).replace("\\", "/")
            if normalized.endswith("share/alphascope/config/data_sources.yaml"):
                return Path(entry.locate()).resolve().parents[1]
    except (PackageNotFoundError, OSError):
        pass
    return Path(sys.prefix) / "share" / "alphascope"


def _user_root() -> Path:
    override = _env_path("ALPHASCOPE_USER_DIR")
    if override is not None:
        return override
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return Path(base).expanduser() / "AlphaScope" if base else Path.home() / "AppData/Local/AlphaScope"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/AlphaScope"
    base = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(base).expanduser() if base else Path.home() / ".local/share") / "alphascope"


def _prepare_user_config(default_dir: Path, user_dir: Path) -> Path:
    """Seed writable user config once without overwriting local customizations."""
    try:
        if default_dir.is_dir():
            for source in default_dir.rglob("*"):
                if not source.is_file():
                    continue
                target = user_dir / source.relative_to(default_dir)
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        if user_dir.is_dir():
            return user_dir
    except OSError:
        pass
    return default_dir


_MODULE_DIR = Path(__file__).resolve().parent
_SOURCE_ROOT = _MODULE_DIR.parent
_SOURCE_CHECKOUT = (_SOURCE_ROOT / "pyproject.toml").is_file() and (_SOURCE_ROOT / "config").is_dir()
_ROOT_OVERRIDE = _env_path("ALPHASCOPE_PROJECT_ROOT")

if getattr(sys, "frozen", False):
    PROJECT_ROOT = _ROOT_OVERRIDE or Path(sys.executable).resolve().parent
    _PROJECT_LOCAL = True
elif _ROOT_OVERRIDE is not None:
    PROJECT_ROOT = _ROOT_OVERRIDE
    _PROJECT_LOCAL = True
elif _SOURCE_CHECKOUT:
    PROJECT_ROOT = _SOURCE_ROOT
    _PROJECT_LOCAL = True
else:
    PROJECT_ROOT = _installed_asset_root()
    _PROJECT_LOCAL = False

BACKEND_DIR = _MODULE_DIR
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
SEED_DIR = PROJECT_ROOT / "seed"

_USER_ROOT = _user_root()
if _PROJECT_LOCAL:
    CONFIG_DIR = _env_path("ALPHASCOPE_CONFIG_DIR") or DEFAULT_CONFIG_DIR
    DATA_DIR = _env_path("ALPHASCOPE_DATA_DIR") or PROJECT_ROOT / "data"
    ENV_FILE = _env_path("ALPHASCOPE_ENV_FILE") or PROJECT_ROOT / ".env"
    CUSTOM_PROVIDERS_DIR = PROJECT_ROOT / "custom_providers"
else:
    requested_config = _env_path("ALPHASCOPE_CONFIG_DIR")
    CONFIG_DIR = requested_config or _prepare_user_config(DEFAULT_CONFIG_DIR, _USER_ROOT / "config")
    DATA_DIR = _env_path("ALPHASCOPE_DATA_DIR") or _USER_ROOT / "data"
    ENV_FILE = _env_path("ALPHASCOPE_ENV_FILE") or _USER_ROOT / ".env"
    CUSTOM_PROVIDERS_DIR = _USER_ROOT / "custom_providers"

DB_DIR = DATA_DIR / "db"
CACHE_DIR = DATA_DIR / "cache"
REPORTS_DIR = DATA_DIR / "reports"
UPLOADS_DIR = DATA_DIR / "uploads"
LOGS_DIR = DATA_DIR / "logs"
