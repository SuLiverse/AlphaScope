"""MCP server 启动入口 — run_server 函数 + console_script + 边界断言测试。

注意:run_server() 会调用 server.run()(stdio 阻塞), 测试不直接调用它,
只验证入口函数可导入、边界断言生效、console_script 路径解析正确。
"""

from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.api.main import app

    return TestClient(app)


def test_run_server_is_callable_entrypoint():
    """run_server 是可调用的函数(供 console_script 与 python -m 调用)。"""
    from backend.mcp_server import run_server

    assert callable(run_server)


def test_run_server_returns_nonzero_when_mcp_missing():
    """mcp 库不可用时 run_server 返回 1 并打印提示,不启动 server。"""
    from backend import mcp_server

    with patch.object(mcp_server, "_MCP_AVAILABLE", False):
        assert mcp_server.run_server() == 1


def test_assert_no_forbidden_tools():
    """边界守卫:已注册工具中不得出现实盘下单工具名。"""
    from backend.mcp_server import assert_no_forbidden_tools

    # 默认 server 不应注册禁止工具(若有则抛)
    assert_no_forbidden_tools()


def test_assert_no_forbidden_tools_detects_violation():
    """构造一个违规场景:若 server 注册了禁止工具,断言应抛。"""
    from backend import mcp_server

    with patch.object(mcp_server, "list_tool_names", return_value=["submit_order", "get_price"]):
        with pytest.raises(AssertionError, match="禁止的工具"):
            mcp_server.assert_no_forbidden_tools()


def test_console_script_importable():
    """pyproject [project.scripts] 的 alphascope-mcp = backend.mcp_server:run_server
    指向的导入路径必须可解析。"""
    mod = importlib.import_module("backend.mcp_server")
    assert hasattr(mod, "run_server")


def test_main_block_exits_via_systemexit():
    """python -m backend.mcp_server 在 mcp 不可用时:run_server 返回 1,
    __main__ 块 SystemExit(1)。验证 run_server(不可用)→1 的退出语义。"""
    from backend import mcp_server

    with patch.object(mcp_server, "_MCP_AVAILABLE", False):
        code = mcp_server.run_server()
    assert code == 1


def test_diagnostics_mcp_endpoint(client):
    """GET /api/diagnostics/mcp 返回能力概览 + 启动命令 + Claude Desktop 配置片段。"""
    r = client.get("/api/diagnostics/mcp")
    assert r.status_code == 200
    data = r.json()["data"]
    assert "available" in data
    assert "tools" in data
    assert "start_command" in data
    assert "claude_desktop_config" in data
    assert "alphascope-mcp" in data["start_command"]
