# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 研策中枢 AlphaScope."""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None
ROOT = Path(os.path.abspath(SPEC)).parent

datas = [
    (str(ROOT / "pyproject.toml"), "."),
    (str(ROOT / "backend"), "backend"),
    (str(ROOT / "config"), "config"),
    (str(ROOT / "prompts"), "prompts"),
    (str(ROOT / "apps" / "web" / "dist"), "apps/web/dist"),
]
datas += collect_data_files("akshare")

for optional_dir in ("custom_providers",):
    path = ROOT / optional_dir
    if path.exists():
        datas.append((str(path), optional_dir))

env_example = ROOT / ".env.example"
if env_example.exists():
    datas.append((str(env_example), "."))

hiddenimports = [
    "backend.api.main",
    "dotenv",
    "yaml",
    "sqlite3",
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "anyio",
    "sniffio",
    "h11",
    "pandas",
    "numpy",
    "plotly",
    "akshare",
    "curl_cffi",
    "openai",
    "aiohttp",
    "tenacity",
    "apscheduler",
    "requests",
    "cryptography",
    "cryptography.hazmat.primitives.ciphers.aead",
    "multipart",
]

hiddenimports += collect_submodules("backend")

a = Analysis(
    ["launcher.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tests",
        "test",
        "pytest",
        "ruff",
        "IPython",
        "jupyter",
        "notebook",
        "sphinx",
        "torch",
        "tensorflow",
        "cv2",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AlphaScope",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AlphaScope",
)
