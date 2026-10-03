"""MCP Server 测试 / Phase D #1.

覆盖:
1. mcp 路径 (装了): server 创建 / 5 个研究工具注册 / 边界断言通过
2. 降级路径 (强制 _MCP_AVAILABLE=False): is_available False, create_server None
3. 边界守卫: assert_no_forbidden_tools (注册实盘下单工具会抛)
4. 工具描述合规: 禁止工具名列表完整
5. 工具调用级回归: 调用工具本体 (依赖入口 monkeypatch 桩掉, 全离线),
   校验返回为合法 JSON / 错误路径为稳定文案且不泄漏异常与路径细节

合规: 测试只校验研究语义工具与边界, 不调用任何实盘下单能力。
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
    return _get_tool_fn("search_evidence")


def _get_tool_fn(name: str):
    """取 create_server() 内注册的工具原函数 (@server.tool() 不替换函数对象, .fn 即本体)。"""
    server = mcp_server.create_server()
    assert server is not None
    return server._tool_manager.get_tool(name).fn


# 稳定错误不得携带的内部细节 (异常类型名 / 文件路径 / 堆栈字样)
_LEAK_TOKENS = ("ImportError", "TypeError", "RuntimeError", "Traceback", ".py", "\\", "C:")


def _assert_error_sanitized(result: str, expected_error: str) -> None:
    """错误返回应为稳定 JSON: 恰为 {"error": 固定文案}, 不含异常类型/路径等内部细节。"""
    import json

    assert json.loads(result) == {"error": expected_error}
    for token in _LEAK_TOKENS:
        assert token not in result, f"错误返回泄漏内部细节: {token!r} 出现在 {result!r}"


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
    """检索器抛异常时, search_evidence 应返回稳定错误, 不泄漏异常/路径细节。"""
    from unittest.mock import patch

    search_evidence = _get_search_evidence()

    with patch(
        "backend.rag.hybrid_retriever.get_hybrid_retriever",
        side_effect=RuntimeError("boom C:\\proj\\backend\\rag\\hybrid_retriever.py"),
    ):
        result = search_evidence("茅台", 2)

    _assert_error_sanitized(result, "证据检索暂不可用")


# ============================================================
# 6. 工具调用级回归 (调用工具本体; 依赖入口全部 monkeypatch 桩掉, 离线)
# ============================================================


def test_get_market_data_calls_get_recent_bars(monkeypatch):
    """get_market_data 应调 get_recent_bars(symbol, count=30) 并只返回最近 10 日。"""
    import json

    from backend import price_fetcher

    calls = []

    def fake_bars(symbol, count=5):
        calls.append((symbol, count))
        return [
            {"date": f"2024-01-{i:02d}", "close": 100.0 + i, "volume": float(i * 100)}
            for i in range(1, 13)  # 12 根 bar → 工具应截取最近 10 根
        ]

    monkeypatch.setattr(price_fetcher, "get_recent_bars", fake_bars)
    result = _get_tool_fn("get_market_data")("600519")

    assert calls == [("600519", 30)]
    data = json.loads(result)
    assert data["symbol"] == "600519"
    assert len(data["bars"]) == 10
    assert data["bars"][0] == {"date": "2024-01-03", "close": 103.0, "volume": 300.0}
    assert data["bars"][-1] == {"date": "2024-01-12", "close": 112.0, "volume": 1200.0}


def test_get_market_data_empty_bars_returns_structured_error(monkeypatch):
    """无数据 (空列表) 时返回结构化错误 — 非异常路径, 结构保持不变。"""
    import json

    from backend import price_fetcher

    monkeypatch.setattr(price_fetcher, "get_recent_bars", lambda symbol, count=5: [])
    result = _get_tool_fn("get_market_data")("600519")

    assert json.loads(result) == {"error": "无 600519 行情数据"}


def test_get_market_data_error_path_sanitized(monkeypatch):
    """数据入口抛 ImportError 时返回稳定错误, 不泄漏异常类型/文件路径。"""
    from backend import price_fetcher

    def boom(symbol, count=5):
        raise ImportError("No module named 'backend.price_fetcher' (C:\\proj\\backend\\price_fetcher.py)")

    monkeypatch.setattr(price_fetcher, "get_recent_bars", boom)
    result = _get_tool_fn("get_market_data")("600519")

    _assert_error_sanitized(result, "行情数据暂不可用")


def test_list_integrations_calls_registry(monkeypatch):
    """list_integrations 应调 get_registry().all_metadata() 并返回结构化 JSON。"""
    import json
    from types import SimpleNamespace

    from backend.integrations import registry as registry_mod

    meta = SimpleNamespace(
        name="vectorbt",
        category=SimpleNamespace(value="backtest"),
        display_name="VectorBT",
        license_safety=SimpleNamespace(value="safe"),
        allow_live_order=False,
    )
    fake_registry = SimpleNamespace(all_metadata=lambda: [meta])
    monkeypatch.setattr(registry_mod, "get_registry", lambda: fake_registry)

    data = json.loads(_get_tool_fn("list_integrations")())

    assert data["count"] == 1
    assert data["integrations"][0] == {
        "name": "vectorbt",
        "category": "backtest",
        "display_name": "VectorBT",
        "license_safety": "safe",
        "allow_live_order": False,
    }


def test_list_integrations_error_path_sanitized(monkeypatch):
    """注册中心抛错时返回稳定错误, 不泄漏异常/路径细节。"""
    from backend.integrations import registry as registry_mod

    def boom():
        raise ImportError("backend/integrations/registry.py missing")

    monkeypatch.setattr(registry_mod, "get_registry", boom)
    result = _get_tool_fn("list_integrations")()

    _assert_error_sanitized(result, "集成中心暂不可用")


def test_get_trading_boundary_calls_describe_capabilities(monkeypatch):
    """get_trading_boundary 应调 describe_capabilities() 并透传为 JSON。"""
    import json

    from backend.security import trading_boundary as tb

    monkeypatch.setattr(
        tb,
        "describe_capabilities",
        lambda: {"live_order_blocked": True, "tools": ["get_market_data"]},
    )
    data = json.loads(_get_tool_fn("get_trading_boundary")())

    assert data == {"live_order_blocked": True, "tools": ["get_market_data"]}


def test_get_trading_boundary_error_path_sanitized(monkeypatch):
    """边界查询抛错时返回稳定错误, 不泄漏异常/路径细节。"""
    from backend.security import trading_boundary as tb

    def boom():
        raise TypeError("trading_boundary.py: bad payload")

    monkeypatch.setattr(tb, "describe_capabilities", boom)
    result = _get_tool_fn("get_trading_boundary")()

    _assert_error_sanitized(result, "边界信息暂不可用")


def test_is_trading_day_calls_calendar(monkeypatch):
    """is_trading_day 应调 backend.trading_calendar.is_trading_day(date, market)。"""
    import json

    from backend import trading_calendar

    calls = []

    def fake_isd(date, market="XSHG"):
        calls.append((date, market))
        return True

    monkeypatch.setattr(trading_calendar, "is_trading_day", fake_isd)
    data = json.loads(_get_tool_fn("is_trading_day")("2024-01-02", "XSHG"))

    assert calls == [("2024-01-02", "XSHG")]
    assert data == {"date": "2024-01-02", "market": "XSHG", "is_trading_day": True}


def test_is_trading_day_error_path_sanitized(monkeypatch):
    """日历查询抛错时返回稳定错误, 不泄漏异常/路径细节。"""
    from backend import trading_calendar

    def boom(date, market="XSHG"):
        raise ValueError("trading_calendar.py: bad date")

    monkeypatch.setattr(trading_calendar, "is_trading_day", boom)
    result = _get_tool_fn("is_trading_day")("not-a-date", "XSHG")

    _assert_error_sanitized(result, "交易日历暂不可用")
