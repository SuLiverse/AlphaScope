"""源码启动 local API token 自动引导。"""

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
    # 使用 setenv 而非 delenv，便于 teardown 精确还原，避免污染后续用例的进程环境
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
        # ensure 会写 os.environ；先清掉 setenv 的空串以便走生成分支
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
    finally:
        # 强制回到「测试开放 API」态，防止 401 传染其它模块
        os.environ.pop("ALPHASCOPE_LOCAL_API_TOKEN", None)
        os.environ["ALPHASCOPE_ALLOW_OPEN_API"] = "1"
