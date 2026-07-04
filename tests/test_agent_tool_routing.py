"""Agent 工具路由测试 — 验证 ToolRouter 注册与调用"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from backend.runtime.tool_router import ToolDefinition, ToolRouter


# ============================================================
# 工具注册
# ============================================================


class TestToolRegistration:
    """工具注册测试"""

    def test_default_tools_registered(self):
        router = ToolRouter()
        tools = router.list_tools()
        ids = {t["id"] for t in tools}
        # 原有 6 个
        assert "market_data" in ids
        assert "news_search" in ids
        assert "fund_flow" in ids
        assert "fundamentals" in ids
        assert "web_search" in ids
        assert "evidence_search" in ids

    def test_m4_tools_registered(self):
        router = ToolRouter()
        tools = router.list_tools()
        ids = {t["id"] for t in tools}
        assert "quant_backtest" in ids
        assert "fund_metrics" in ids
        assert "dca_simulate" in ids
        assert "portfolio_rebalance" in ids

    def test_total_tool_count(self):
        router = ToolRouter()
        tools = router.list_tools()
        assert len(tools) == 10  # 6 原有 + 4 M4

    def test_register_custom_tool(self):
        router = ToolRouter()
        router.register_tool(
            ToolDefinition(
                id="custom_test",
                name="测试工具",
                description="测试",
                tool_type="test",
                handler=lambda: {"ok": True},
            )
        )
        tool = router.get_tool("custom_test")
        assert tool is not None
        assert tool.name == "测试工具"


# ============================================================
# 工具调用
# ============================================================


class TestToolCalls:
    """工具调用测试"""

    def test_call_existing_tool(self):
        router = ToolRouter()
        router.register_tool(
            ToolDefinition(
                id="test_tool",
                name="测试",
                description="测试",
                tool_type="test",
                handler=lambda x=1: {"result": x * 2},
            )
        )
        result = router.call_tool("test_tool", x=5)
        assert result.success is True
        assert result.data["result"] == 10

    def test_call_nonexistent_tool(self):
        router = ToolRouter()
        result = router.call_tool("nonexistent")
        assert result.success is False
        assert "不存在" in result.error

    def test_call_disabled_tool(self):
        router = ToolRouter()
        router.register_tool(
            ToolDefinition(
                id="disabled_tool",
                name="禁用",
                description="测试",
                tool_type="test",
                enabled=False,
                handler=lambda: {"ok": True},
            )
        )
        result = router.call_tool("disabled_tool")
        assert result.success is False
        assert "禁用" in result.error

    def test_call_records_latency(self):
        router = ToolRouter()
        router.register_tool(
            ToolDefinition(
                id="slow_tool",
                name="慢工具",
                description="测试",
                tool_type="test",
                handler=lambda: {"ok": True},
            )
        )
        result = router.call_tool("slow_tool")
        assert result.latency_ms >= 0

    def test_call_logs_errors(self):
        def bad_handler():
            raise ValueError("boom")

        router = ToolRouter()
        router.register_tool(
            ToolDefinition(
                id="bad_tool",
                name="坏工具",
                description="测试",
                tool_type="test",
                handler=bad_handler,
            )
        )
        result = router.call_tool("bad_tool")
        assert result.success is False
        assert "boom" in result.error

    def test_rate_limit(self):
        router = ToolRouter()
        router.register_tool(
            ToolDefinition(
                id="limited",
                name="限速",
                description="测试",
                tool_type="test",
                rate_limit=2,
                handler=lambda: {"ok": True},
            )
        )
        assert router.call_tool("limited").success is True
        assert router.call_tool("limited").success is True
        assert router.call_tool("limited").success is False  # 超限

    def test_call_log(self):
        router = ToolRouter()
        router.register_tool(
            ToolDefinition(
                id="log_tool",
                name="日志",
                description="测试",
                tool_type="test",
                handler=lambda: {"ok": True},
            )
        )
        router.call_tool("log_tool")
        log = router.get_call_log()
        assert len(log) == 1
        assert log[0]["tool_id"] == "log_tool"


# ============================================================
# M4 量化工具路由
# ============================================================


class TestQuantBacktestTool:
    """量化回测工具"""

    def test_backtest_tool_registered(self):
        router = ToolRouter()
        tool = router.get_tool("quant_backtest")
        assert tool is not None
        assert tool.tool_type == "calculator"

    def test_backtest_tool_local_engine_handles_unknown_strategy(self):
        """本地回测工具对未知策略返回清晰错误而非崩溃"""
        router = ToolRouter()
        result = router.call_tool(
            "quant_backtest",
            strategy_id="s1",
            symbol="600519",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert result.data is not None
        assert "error" in result.data

    def test_backtest_tool_runs_local_engine(self):
        """本地回测工具可直接返回回测结果"""
        router = ToolRouter()
        result = router.call_tool(
            "quant_backtest",
            strategy_id="macd_momentum",
            symbol="600519",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert result.data is not None
        assert result.data["status"] == "completed"
        assert result.data["source_status"] == "local"
        assert result.data["run_id"].startswith("local-")


class TestFundMetricsTool:
    """基金指标工具"""

    def test_fund_metrics_registered(self):
        router = ToolRouter()
        tool = router.get_tool("fund_metrics")
        assert tool is not None

    def test_fund_metrics_no_data(self):
        """无数据时返回错误"""
        mock_provider = AsyncMock()
        mock_provider.get_nav_history.return_value = []

        with patch("backend.runtime.tool_router.get_tool_router", return_value=ToolRouter()):
            router = ToolRouter()
            # Patch the handler's provider
            with patch("backend.funds.providers.get_provider", return_value=mock_provider):
                result = router.call_tool("fund_metrics", fund_code="000001")

        assert result.data is not None
        assert "error" in result.data


class TestDCASimulateTool:
    """定投模拟工具"""

    def test_dca_registered(self):
        router = ToolRouter()
        tool = router.get_tool("dca_simulate")
        assert tool is not None

    def test_dca_no_data(self):
        """无净值数据时返回错误"""
        mock_provider = AsyncMock()
        mock_provider.get_nav_history.return_value = []

        router = ToolRouter()
        with patch("backend.funds.providers.get_provider", return_value=mock_provider):
            result = router.call_tool(
                "dca_simulate",
                fund_code="000001",
                amount=1000,
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

        assert "error" in result.data


class TestPortfolioRebalanceTool:
    """组合再平衡工具"""

    def test_rebalance_registered(self):
        router = ToolRouter()
        tool = router.get_tool("portfolio_rebalance")
        assert tool is not None

    def test_rebalance_basic(self):
        router = ToolRouter()
        result = router.call_tool(
            "portfolio_rebalance",
            holdings=[{"fund_code": "A", "weight": 0.3}],
            target_weights={"A": 0.5, "B": 0.5},
        )
        assert result.success is True
        assert "trades" in result.data
        assert len(result.data["trades"]) == 2  # A 需要买，B 需要买

    def test_rebalance_no_change(self):
        router = ToolRouter()
        result = router.call_tool(
            "portfolio_rebalance",
            holdings=[
                {"fund_code": "A", "weight": 0.5},
                {"fund_code": "B", "weight": 0.5},
            ],
            target_weights={"A": 0.5, "B": 0.5},
        )
        assert result.success is True
        assert len(result.data["trades"]) == 0

    def test_rebalance_empty_weights(self):
        router = ToolRouter()
        result = router.call_tool(
            "portfolio_rebalance",
            holdings=[],
            target_weights={},
        )
        assert result.success is True
        assert "error" in result.data


# ============================================================
# 工具列表 API
# ============================================================


class TestToolListAPI:
    """工具列表对外可见"""

    def test_list_tools_format(self):
        router = ToolRouter()
        tools = router.list_tools()
        for t in tools:
            assert "id" in t
            assert "name" in t
            assert "description" in t
            assert "type" in t
