"""Tests for runtime config token hygiene — docker 共享卷副本不得携带 token。"""

from __future__ import annotations

import json
import re

from backend.security.runtime_config import write_dev_runtime_configs


def _load_payload(path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"window\.__ALPHASCOPE_CONFIG__ = (\{.*\});", text, re.DOTALL)
    assert match is not None, f"unexpected runtime-config format in {path}"
    return json.loads(match.group(1))


def test_all_static_runtime_configs_omit_token(tmp_path, monkeypatch):
    """public/dist/shared are web assets and must never carry the local token."""
    monkeypatch.setenv("ALPHASCOPE_RUNTIME_CONFIG_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("VITE_API_BASE_URL", "http://localhost:8000")
    token = "dev-token-abc-123"

    write_dev_runtime_configs(repo_root=tmp_path / "repo", local_api_token=token)

    public_file = tmp_path / "repo" / "apps/web/public/runtime-config.js"
    dist_file = tmp_path / "repo" / "apps/web/dist/runtime-config.js"
    shared_file = tmp_path / "shared" / "runtime-config.js"

    assert public_file.exists()
    assert dist_file.exists()
    assert shared_file.exists()

    assert _load_payload(public_file)["localApiToken"] == ""
    assert _load_payload(dist_file)["localApiToken"] == ""
    assert _load_payload(shared_file)["localApiToken"] == ""


def test_shared_copy_still_carries_api_base_url(tmp_path, monkeypatch):
    """置空的只是 token；共享副本其余字段（apiBaseUrl 等）保持完整。"""
    monkeypatch.setenv("ALPHASCOPE_RUNTIME_CONFIG_DIR", str(tmp_path / "shared"))
    monkeypatch.setenv("VITE_API_BASE_URL", "http://192.168.1.10:8000")

    write_dev_runtime_configs(repo_root=tmp_path / "repo", local_api_token="tok-1")

    shared_payload = _load_payload(tmp_path / "shared" / "runtime-config.js")
    assert shared_payload["apiBaseUrl"] == "http://192.168.1.10:8000"
    assert shared_payload["localApiToken"] == ""
    assert shared_payload["packaged"] is False


def test_without_shared_dir_no_shared_copy_written(tmp_path, monkeypatch):
    """No shared target is created and local static targets still omit token."""
    monkeypatch.delenv("ALPHASCOPE_RUNTIME_CONFIG_DIR", raising=False)

    write_dev_runtime_configs(repo_root=tmp_path / "repo", local_api_token="tok-2")

    assert not (tmp_path / "shared").exists()
    assert _load_payload(tmp_path / "repo" / "apps/web/public/runtime-config.js")["localApiToken"] == ""
    assert _load_payload(tmp_path / "repo" / "apps/web/dist/runtime-config.js")["localApiToken"] == ""
