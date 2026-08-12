"""MCP Server 测试 / Phase D #1.

覆盖:
1. mcp 路径 (装了): server 创建 / 5 个研究工具注册 / 边界断言通过
2. 降级路径 (强制 _MCP_AVAILABLE=False): is_available False, create_server None
3. 边界守卫: assert_no_forbidden_tools (注册实盘下单工具会抛)
4. 工具描述合规: 禁止工具名列表完整

合规: 测试只校验工具注册与边界, 不调用任何实盘下单能力。
"""

from __future__ import annotations

import pytest

from backend import mcp_server


# ============================================================
# 1. mcp 路径 (装了; 未装整组跳过)
# ============================================================

mcp_real = pytest.importorskip("mcp")


def test_is_available_true():
    assert mcp_server.is_available() is True


def test_create_server_returns_fastmcp_instance():
    server = mcp_server.create_server()
    assert server is not None
    assert getattr(server, "name", None) == "AlphaScope"


def test_five_research_tools_registered():
    """server 应注册 5 个研究语义工具 (不含任何实盘下单)。"""
    names = mcp_server.list_tool_names()
    expected = {
        "get_market_data",
        "search_evidence",
        "list_integrations",
        "get_trading_boundary",
        "is_trading_day",
    }
    assert expected.issubset(set(names)), f"缺失工具: {expected - set(names)}"


def test_no_forbidden_tools_registered():
    """关键边界: server 不得注册任何实盘下单工具。"""
    names = mcp_server.list_tool_names()
    for forbidden in mcp_server.FORBIDDEN_TOOL_NAMES:
        assert forbidden not in names, f"server 错误注册了禁止工具: {forbidden}"


def test_assert_no_forbidden_tools_passes():
    """正常情况下边界守卫不抛 (server 未注册禁止工具)。"""
    mcp_server.assert_no_forbidden_tools()  # 不抛即通过


def test_describe_reports_available():
    info = mcp_server.describe()
    assert info["available"] is True
    assert info["tool_count"] >= 5
    assert "forbidden_tools" in info
    assert "submit_order" in info["forbidden_tools"]


# ============================================================
# 2. 降级路径 (强制 _MCP_AVAILABLE=False)
# ============================================================


@pytest.fixture
def degraded(monkeypatch):
    monkeypatch.setattr(mcp_server, "_MCP_AVAILABLE", False)


def test_degraded_is_available_false(degraded):
    assert mcp_server.is_available() is False


def test_degraded_create_server_returns_none(degraded):
    assert mcp_server.create_server() is None


def test_degraded_describe_reports_unavailable(degraded):
    info = mcp_server.describe()
    assert info["available"] is False
    assert info["tool_count"] == 0


# ============================================================
# 3. 边界守卫单测 (模拟违规)
# ============================================================


def test_assert_no_forbidden_tools_detects_violation(monkeypatch):
    """若 server 注册了禁止工具, 边界守卫必须抛 AssertionError。"""
    # monkeypatch list_tool_names 返回含禁止工具的列表
    monkeypatch.setattr(mcp_server, "list_tool_names", lambda: ["get_market_data", "submit_order"])
    with pytest.raises(AssertionError, match="禁止"):
        mcp_server.assert_no_forbidden_tools()


def test_forbidden_tool_names_complete():
    """禁止工具名表必须覆盖规划 §7 的全部禁止项。"""
    required = {
        "submit_order",
        "place_order",
        "cancel_order",
        "connect_live_broker",
    }
    assert required.issubset(set(mcp_server.FORBIDDEN_TOOL_NAMES))


# ============================================================
# 4. 合规免责
# ============================================================


def test_tool_descriptions_mention_research_semantics():
    """工具描述应体现研究语义 (历史/不预测), 不是下单语义。"""
    # 通过 describe() 的 tools 列表间接确认 (具体描述在装饰器内部, 不易直接读;
    # 这里只验证工具集是研究类: get/search/list/is_*, 没有 buy/sell/submit)
    names = mcp_server.list_tool_names()
    for n in names:
        low = n.lower()
        for tok in ("buy", "sell", "submit", "place_order", "auto_trade", "live"):
            assert tok not in low, f"工具名 {n} 含交易语义 {tok}"


# ============================================================
# 5. search_evidence 工具 (RAG 证据检索; 离线, mock 检索器)
# ============================================================


def _get_search_evidence():
    """取 create_server() 内注册的 search_evidence 函数 (嵌套闭包, 非模块级)。"""
    server = mcp_server.create_server()
    assert server is not None
    return server._tool_manager.get_tool("search_evidence").fn


def test_search_evidence_uses_hybrid_retriever():
    """search_evidence 应经 get_hybrid_retriever().search() 检索, 并按 RetrievalResult 字段映射。"""
    import json
    from unittest.mock import patch

    from backend.rag.hybrid_retriever import RetrievalResult

    fake = RetrievalResult(text="<片段>", source="<来源>", combined_score=0.8)
    search_evidence = _get_search_evidence()

    with patch("backend.rag.hybrid_retriever.get_hybrid_retriever") as m:
        m.return_value.search.return_value = [fake, fake]
        result = search_evidence("茅台", 2)

    m.return_value.search.assert_called_once_with("茅台", n_results=2)
    data = json.loads(result)
    assert data["query"] == "茅台"
    assert "hits" in data
    assert len(data["hits"]) == 2
    assert data["hits"][0]["content"] == "<片段>"
    assert data["hits"][0]["source"] == "<来源>"
    assert data["hits"][0]["score"] == 0.8


def test_search_evidence_error_path_returns_json_error():
    """检索器抛异常时, search_evidence 应返回结构化错误而非抛异常。"""
    from unittest.mock import patch

    search_evidence = _get_search_evidence()

    with patch(
        "backend.rag.hybrid_retriever.get_hybrid_retriever",
        side_effect=RuntimeError("boom"),
    ):
        result = search_evidence("茅台", 2)

    assert '"error"' in result
    assert "证据检索失败" in result
