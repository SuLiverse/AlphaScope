"""源码启动 local API token 自动引导 + runtime-config 共享写入。"""

from __future__ import annotations

import json
import os


def test_ensure_token_open_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHASCOPE_ALLOW_OPEN_API", "1")
    monkeypatch.delenv("ALPHASCOPE_LOCAL_API_TOKEN", raising=False)
    from backend.security import local_token as lt

    monkeypatch.setattr(lt, "_repo_root", lambda: tmp_path)
    monkeypatch.setattr(lt, "_token_file", lambda: tmp_path / "tok.txt")
    assert lt.ensure_local_api_token() == ""


def test_ensure_token_auto_generates_and_writes_runtime_config(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHASCOPE_ALLOW_OPEN_API", "")
    monkeypatch.setenv("ALPHASCOPE_LOCAL_API_TOKEN", "")
    from backend.security import local_token as lt

    public = tmp_path / "apps" / "web" / "public"
    public.mkdir(parents=True)
    monkeypatch.setattr(lt, "_repo_root", lambda: tmp_path)
    token_path = tmp_path / "data" / "runtime" / "local_api_token.txt"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(lt, "_token_file", lambda: token_path)

    try:
        os.environ.pop("ALPHASCOPE_LOCAL_API_TOKEN", None)
        os.environ.pop("ALPHASCOPE_ALLOW_OPEN_API", None)
        token = lt.ensure_local_api_token()
        assert len(token) >= 32
        assert os.environ.get("ALPHASCOPE_LOCAL_API_TOKEN") == token
        assert token_path.read_text(encoding="utf-8").strip() == token
        cfg_path = public / "runtime-config.js"
        assert cfg_path.is_file()
        text = cfg_path.read_text(encoding="utf-8")
        payload = json.loads(text.split(" = ", 1)[1].rstrip(";\n"))
        assert payload["localApiToken"] == token
        assert payload["packaged"] is False
    finally:
        os.environ.pop("ALPHASCOPE_LOCAL_API_TOKEN", None)
        os.environ["ALPHASCOPE_ALLOW_OPEN_API"] = "1"


def test_launcher_write_runtime_config_uses_shared_helper(tmp_path, monkeypatch):
    import launcher
    from backend.security.runtime_config import format_runtime_config_js, runtime_config_payload

    monkeypatch.setattr(launcher, "is_frozen", lambda: False)
    launcher.write_runtime_config(tmp_path, api_port=8123, local_api_token="shared-secret")
    text = (tmp_path / "runtime-config.js").read_text(encoding="utf-8")
    expected = format_runtime_config_js(
        runtime_config_payload(
            api_base_url="http://127.0.0.1:8123",
            local_api_token="shared-secret",
            packaged=False,
        )
    )
    assert text == expected
