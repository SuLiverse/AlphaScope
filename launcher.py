"""Desktop launcher for 研策中枢 AlphaScope.

The packaged app runs as a small local desktop service:
- starts the FastAPI backend on an available localhost port,
- serves the built React frontend from bundled static files,
- writes runtime-config.js so the frontend talks to the selected API port,
- opens the user's default browser.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import tomllib
import webbrowser
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

APP_NAME = "研策中枢 AlphaScope"
DEFAULT_API_PORT = 8000
DEFAULT_WEB_PORT = 3000
RUNTIME_MARKER = "alphascope-launcher-v1"


class AlphaScopeStaticHandler(SimpleHTTPRequestHandler):
    """Quiet static file handler with SPA refresh fallback."""

    def log_message(self, format: str, *args: Any) -> None:
        return

    def copyfile(self, source: Any, outputfile: Any) -> None:
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            return

    def send_head(self) -> Any:
        translated = Path(self.translate_path(self.path))
        route_name = Path(self.path.split("?", 1)[0]).name
        if not translated.exists() and "." not in route_name:
            self.path = "/index.html"
        return super().send_head()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def runtime_root() -> Path:
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def add_import_paths(root: Path, bundled: Path) -> None:
    for candidate in (root, root / "backend", bundled, bundled / "backend"):
        if candidate.exists():
            path = str(candidate)
            if path not in sys.path:
                sys.path.insert(0, path)


def ensure_directories(root: Path) -> None:
    for relative in (
        "data",
        "data/db",
        "data/cache",
        "data/cache/fundamentals",
        "data/cache/chroma_db",
        "data/reports",
        "data/reports/archive",
        "data/uploads",
        "data/logs",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)


def sync_runtime_assets(root: Path, bundled: Path) -> None:
    for relative in ("config", "prompts", "custom_providers"):
        source = bundled / relative
        target = root / relative
        if source.exists() and source.resolve() != target.resolve():
            shutil.copytree(source, target, dirs_exist_ok=True)

    web_source = bundled / "apps" / "web" / "dist"
    web_target = root / "apps" / "web" / "dist"
    if web_source.exists() and web_source.resolve() != web_target.resolve():
        shutil.copytree(web_source, web_target, dirs_exist_ok=True)


def ensure_env_file(root: Path, bundled: Path) -> None:
    env_file = root / ".env"
    if env_file.exists():
        return

    for env_example in (root / ".env.example", bundled / ".env.example"):
        if env_example.exists():
            shutil.copy2(env_example, env_file)
            print(f"[AlphaScope] Created config file: {env_file}")
            return

    env_file.write_text(
        "# AlphaScope API Keys\n"
        "DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_BASE_URL=https://api.deepseek.com\n"
        "OPENAI_API_KEY=\n"
        "CLAUDE_API_KEY=\n"
        "KIMI_API_KEY=\n",
        encoding="utf-8",
    )
    print(f"[AlphaScope] Created config template: {env_file}")


def load_dotenv(root: Path) -> None:
    env_file = root / ".env"
    if not env_file.exists():
        return

    for line in env_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def ensure_master_key(root: Path) -> None:
    """确保存在持久的 AI_FINANCE_MASTER_KEY,用于加密自定义 Provider 的 API Key。

    首次启动若 .env 中没有,则生成随机密钥并追加写入 .env。每台安装独立、持久,
    无需用户手动配置,也避免使用不安全的开发回退密钥。
    """
    if os.environ.get("AI_FINANCE_MASTER_KEY", "").strip():
        return
    key = secrets.token_urlsafe(32)
    os.environ["AI_FINANCE_MASTER_KEY"] = key
    env_file = root / ".env"
    try:
        existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
        with env_file.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(
                f"\n# 自动生成的主密钥(加密自定义 Provider Key 用),请勿改动或泄露\nAI_FINANCE_MASTER_KEY={key}\n"
            )
        print("[AlphaScope] Generated persistent master key in .env")
    except OSError as exc:
        print(f"[AlphaScope] Warning: could not persist master key: {exc}")


def find_free_port(preferred: int) -> int:
    for port in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free localhost port near {preferred}")


def generate_local_api_token() -> str:
    """兼容入口：实现集中在 backend.security.runtime_config。"""
    try:
        from backend.security.runtime_config import generate_local_api_token as _gen

        return _gen()
    except ImportError:
        return secrets.token_urlsafe(32)


def write_runtime_config(web_dir: Path, api_port: int, local_api_token: str) -> None:
    try:
        from backend.security.runtime_config import write_runtime_config_dir

        write_runtime_config_dir(
            web_dir,
            api_port=api_port,
            local_api_token=local_api_token,
            packaged=is_frozen(),
        )
        return
    except ImportError:
        pass
    # 极端环境（无 backend 包）回退
    api_base_url = f"http://127.0.0.1:{api_port}"
    payload = {
        "apiBaseUrl": api_base_url,
        "apiKey": os.environ.get("VITE_API_KEY", ""),
        "localApiToken": local_api_token,
        "packaged": is_frozen(),
    }
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "runtime-config.js").write_text(
        "window.__ALPHASCOPE_CONFIG__ = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )


def start_api(api_port: int) -> threading.Thread:
    import uvicorn

    config = uvicorn.Config(
        "backend.api.main:app",
        host="127.0.0.1",
        port=api_port,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="alphascope-api", daemon=True)
    thread.start()
    return thread


def start_web(web_dir: Path, web_port: int) -> tuple[ThreadingHTTPServer, threading.Thread]:
    if not (web_dir / "index.html").exists():
        raise FileNotFoundError(f"Missing built frontend at {web_dir}. Run npm run build before packaging.")

    handler = partial(AlphaScopeStaticHandler, directory=str(web_dir))
    server = ThreadingHTTPServer(("127.0.0.1", web_port), handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name="alphascope-web",
        daemon=True,
    )
    thread.start()
    return server, thread


def wait_for_http(port: int, path: str = "/", timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    request = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5) as sock:
                sock.sendall(request.encode("ascii"))
                response = sock.recv(64)
            if response.startswith(b"HTTP/1."):
                return True
        except OSError:
            time.sleep(0.4)
    return False


def write_pid_file(root: Path, api_port: int, web_port: int) -> None:
    pid_file = root / ".alphascope_runtime.json"
    resolved_root = root.resolve()
    identity = _process_identity(os.getpid()) or {}
    data: dict[str, Any] = {
        "marker": RUNTIME_MARKER,
        "pid": os.getpid(),
        "api_port": api_port,
        "web_port": web_port,
        "runtime_root": str(resolved_root),
        "executable": identity.get("executable", str(Path(sys.executable).resolve())),
        "process_start_token": identity.get("process_start_token", ""),
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    pid_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def remove_pid_file(root: Path) -> None:
    try:
        (root / ".alphascope_runtime.json").unlink()
    except FileNotFoundError:
        pass


def _process_identity(pid: int) -> dict[str, str] | None:
    if sys.platform.startswith("win"):
        query = (
            f'$p = Get-CimInstance Win32_Process -Filter "ProcessId={pid}"; '
            "if ($null -eq $p) { exit 3 }; "
            "$created = if ($null -ne $p.CreationDate) "
            "{ $p.CreationDate.ToUniversalTime().Ticks.ToString() } else { '' }; "
            "[pscustomobject]@{ "
            "executable = [string]$p.ExecutablePath; "
            "process_start_token = [string]$created "
            "} | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", query],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        try:
            identity = json.loads(result.stdout)
        except (json.JSONDecodeError, TypeError):
            return None
        executable = str(identity.get("executable", "")).strip()
        process_start_token = str(identity.get("process_start_token", "")).strip()
        if not executable or not process_start_token:
            return None
        return {
            "executable": executable,
            "process_start_token": process_start_token,
        }

    proc_dir = Path("/proc") / str(pid)
    try:
        executable = str((proc_dir / "exe").resolve(strict=True))
        stat = (proc_dir / "stat").read_text(encoding="utf-8")
    except OSError:
        return None
    closing_paren = stat.rfind(")")
    fields = stat[closing_paren + 2 :].split() if closing_paren >= 0 else []
    if len(fields) <= 19:
        return None
    return {
        "executable": executable,
        "process_start_token": fields[19],
    }


def _normalized_path(value: str) -> str:
    return os.path.normcase(os.path.abspath(value)).casefold()


def _runtime_marker_trusted(root: Path, data: dict[str, Any], identity: dict[str, str] | None) -> bool:
    if data.get("marker") != RUNTIME_MARKER:
        return False

    try:
        expected_root = _normalized_path(str(root.resolve()))
    except OSError:
        expected_root = _normalized_path(str(root))
    marker_root = _normalized_path(str(data.get("runtime_root", "")))
    if marker_root != expected_root:
        return False

    if not identity:
        return False
    marker_executable = str(data.get("executable", "")).strip()
    marker_token = str(data.get("process_start_token", "")).strip()
    live_executable = str(identity.get("executable", "")).strip()
    live_token = str(identity.get("process_start_token", "")).strip()
    if not all((marker_executable, marker_token, live_executable, live_token)):
        return False
    return _normalized_path(marker_executable) == _normalized_path(live_executable) and secrets.compare_digest(
        marker_token, live_token
    )


def _terminate_process_tree(pid: int) -> bool:
    if sys.platform.startswith("win"):
        command = ["taskkill", "/PID", str(pid), "/T", "/F"]
    else:
        command = ["kill", str(pid)]
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def stop_running_instance(root: Path) -> int:
    pid_file = root / ".alphascope_runtime.json"
    if not pid_file.exists():
        print("[AlphaScope] No running instance marker found.")
        return 0

    try:
        data = json.loads(pid_file.read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
    except Exception:
        pid = 0

    if not pid:
        pid_file.unlink(missing_ok=True)
        print("[AlphaScope] Removed invalid runtime marker.")
        return 0

    if pid == os.getpid():
        print("[AlphaScope] Refusing to stop current process.")
        return 1

    identity = _process_identity(pid)
    if not _runtime_marker_trusted(root, data, identity):
        pid_file.unlink(missing_ok=True)
        print(f"[AlphaScope] Removed stale or untrusted runtime marker for PID {pid}; no process was killed.")
        return 1

    if not _terminate_process_tree(pid):
        print(f"[AlphaScope] Failed to stop PID {pid}.")
        return 1

    pid_file.unlink(missing_ok=True)
    print(f"[AlphaScope] Stop signal sent to PID {pid}.")
    return 0


def _read_project_version() -> str:
    """Read the app version from the bundled (or source) pyproject.toml.

    Kept in sync with backend.api.main._load_api_version so the packaged exe
    never drifts from the declared version. Falls back to "0.0.0" if unreadable.
    """
    for base in (bundle_root(), runtime_root()):
        pyproject = base / "pyproject.toml"
        try:
            with pyproject.open("rb") as file:
                version = tomllib.load(file).get("project", {}).get("version")
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if isinstance(version, str) and version.strip():
            return version.strip()
    return "0.0.0"


def configure_runtime_environment(root: Path) -> None:
    os.environ.setdefault("ALPHASCOPE_PACKAGED", "1" if is_frozen() else "0")
    os.environ.setdefault("ALPHASCOPE_VERSION", _read_project_version())
    os.environ.setdefault("ALPHASCOPE_RUNTIME_ROOT", str(root))
    os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")
    os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")


def run() -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} desktop launcher")
    parser.add_argument("--stop", action="store_true", help="stop a running local instance")
    parser.add_argument("--no-browser", action="store_true", help="do not open browser automatically")
    args = parser.parse_args()

    root = runtime_root()
    bundled = bundle_root()

    if args.stop:
        return stop_running_instance(root)

    add_import_paths(root, bundled)
    configure_runtime_environment(root)
    ensure_directories(root)
    sync_runtime_assets(root, bundled)
    ensure_env_file(root, bundled)
    load_dotenv(root)
    ensure_master_key(root)

    api_port = find_free_port(int(os.environ.get("ALPHASCOPE_API_PORT", DEFAULT_API_PORT)))
    web_port = find_free_port(int(os.environ.get("ALPHASCOPE_WEB_PORT", DEFAULT_WEB_PORT)))
    local_api_token = generate_local_api_token()
    os.environ["ALPHASCOPE_LOCAL_API_TOKEN"] = local_api_token

    web_dir = root / "apps" / "web" / "dist"
    write_runtime_config(web_dir, api_port, local_api_token)
    write_pid_file(root, api_port, web_port)

    print("=" * 58)
    print(f"  {APP_NAME}")
    print("=" * 58)
    print(f"[AlphaScope] Runtime: {root}")
    print(f"[AlphaScope] API:     http://127.0.0.1:{api_port}")
    print(f"[AlphaScope] Web:     http://127.0.0.1:{web_port}")
    print("[AlphaScope] Starting local services...")

    web_server: ThreadingHTTPServer | None = None
    try:
        api_thread = start_api(api_port)
        web_server, _web_thread = start_web(web_dir, web_port)

        api_ready = wait_for_http(api_port, "/health", timeout=45)
        web_ready = wait_for_http(web_port, "/", timeout=15)
        if not api_ready:
            print("[AlphaScope] Warning: backend health check timed out; opening UI anyway.")
        if not web_ready:
            raise RuntimeError("Frontend service did not become ready.")

        url = f"http://127.0.0.1:{web_port}"
        if not args.no_browser:
            webbrowser.open(url)

        print()
        print("[AlphaScope] Started. Keep this window open while using the app.")
        print("[AlphaScope] Press Ctrl+C to stop.")
        while api_thread.is_alive():
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[AlphaScope] Stopping...")
    except Exception as exc:
        print(f"\n[AlphaScope] Startup failed: {exc}")
        input("Press Enter to exit...")
        return 1
    finally:
        if web_server is not None:
            web_server.shutdown()
            web_server.server_close()
        remove_pid_file(root)

    return 0


if __name__ == "__main__":
    raise SystemExit(run())
