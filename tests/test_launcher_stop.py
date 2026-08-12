from __future__ import annotations

import json
from types import SimpleNamespace


def test_write_pid_file_records_runtime_identity(tmp_path, monkeypatch):
    import launcher

    monkeypatch.setattr(
        launcher,
        "_process_identity",
        lambda pid: {
            "executable": r"C:\Python312\python.exe",
            "process_start_token": "638897123456789012",
        },
    )
    launcher.write_pid_file(tmp_path, api_port=8123, web_port=3123)

    marker = json.loads((tmp_path / ".alphascope_runtime.json").read_text(encoding="utf-8"))
    assert marker["marker"] == launcher.RUNTIME_MARKER
    assert marker["runtime_root"] == str(tmp_path.resolve())
    assert marker["executable"] == r"C:\Python312\python.exe"
    assert marker["process_start_token"] == "638897123456789012"


def test_stop_running_instance_refuses_untrusted_marker(tmp_path, monkeypatch):
    import launcher

    marker = tmp_path / ".alphascope_runtime.json"
    marker.write_text('{"pid": 12345, "runtime_root": "elsewhere"}', encoding="utf-8")
    monkeypatch.setattr(
        launcher,
        "_process_identity",
        lambda pid: {
            "executable": r"C:\Python312\python.exe",
            "process_start_token": "live-token",
        },
    )

    def unexpected_kill(pid):
        raise AssertionError("should not kill untrusted pid")

    monkeypatch.setattr(launcher, "_terminate_process_tree", unexpected_kill)

    assert launcher.stop_running_instance(tmp_path) == 1
    assert not marker.exists()


def test_stop_running_instance_refuses_reused_pid(tmp_path, monkeypatch):
    import launcher

    marker = tmp_path / ".alphascope_runtime.json"
    marker.write_text(
        json.dumps(
            {
                "marker": launcher.RUNTIME_MARKER,
                "pid": 12345,
                "runtime_root": str(tmp_path.resolve()),
                "executable": r"C:\Python312\python.exe",
                "process_start_token": "original-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        launcher,
        "_process_identity",
        lambda pid: {
            "executable": r"C:\Python312\python.exe",
            "process_start_token": "reused-pid-token",
        },
    )

    def unexpected_kill(pid):
        raise AssertionError("should not kill a process that reused the launcher PID")

    monkeypatch.setattr(launcher, "_terminate_process_tree", unexpected_kill)

    assert launcher.stop_running_instance(tmp_path) == 1
    assert not marker.exists()


def test_stop_running_instance_uses_argument_array_for_trusted_marker(tmp_path, monkeypatch):
    import launcher

    marker = tmp_path / ".alphascope_runtime.json"
    marker.write_text(
        json.dumps(
            {
                "marker": launcher.RUNTIME_MARKER,
                "pid": 12345,
                "runtime_root": str(tmp_path.resolve()),
                "executable": r"C:\Python312\python.exe",
                "process_start_token": "same-process-token",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        launcher,
        "_process_identity",
        lambda pid: {
            "executable": r"c:\python312\PYTHON.exe",
            "process_start_token": "same-process-token",
        },
    )
    monkeypatch.setattr(launcher.sys, "platform", "win32")

    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    assert launcher.stop_running_instance(tmp_path) == 0
    assert calls == [["taskkill", "/PID", "12345", "/T", "/F"]]
    assert not marker.exists()
