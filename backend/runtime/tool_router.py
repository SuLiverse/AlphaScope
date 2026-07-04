"""
Tool Router: Agent 工具调用框架。

职责：
- 定义可用工具注册表
- Agent 可在分析过程中调用工具获取数据
- 工具调用审计
- 工具权限控制

架构文档要求：Agent 能在分析过程中调用工具（网页搜索/文件解析/数据库查询）。
"""

import time
import logging
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """工具定义"""

    id: str
    name: str
    description: str
    tool_type: str  # data_source, search, crawler, parser, calculator
    enabled: bool = True
    requires_confirmation: bool = False
    rate_limit: int = 60  # 每分钟最大调用次数
    handler: Optional[Callable] = None


@dataclass
class ToolCallResult:
    """工具调用结果"""

    tool_id: str
    success: bool
    data: Any = None
    error: str = ""
    latency_ms: float = 0
    timestamp: float = 0


class ToolRouter:
    """工具调用路由器"""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._call_log: List[ToolCallResult] = []
        self._call_counts: Dict[str, int] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        """注册默认工具"""
        self.register_tool(
            ToolDefinition(
                id="market_data",
                name="行情数据",
                description="获取实时/历史行情数据（OHLCV、涨跌幅、技术指标）",
                tool_type="data_source",
                handler=self._tool_market_data,
            )
        )
        self.register_tool(
            ToolDefinition(
                id="news_search",
                name="新闻搜索",
                description="搜索财经新闻和公告",
                tool_type="data_source",
                handler=self._tool_news_search,
            )
        )
        self.register_tool(
            ToolDefinition(
                id="fund_flow",
                name="资金流向",
                description="获取主力/散户资金流向数据",
                tool_type="data_source",
                handler=self._tool_fund_flow,
            )
        )
        self.register_tool(
            ToolDefinition(
                id="fundamentals",
                name="基本面数据",
                description="获取财务报表、估值指标、盈利数据",
                tool_type="data_source",
                handler=self._tool_fundamentals,
            )
        )
        self.register_tool(
            ToolDefinition(
                id="web_search",
                name="网页搜索",
                description="搜索互联网获取最新信息",
                tool_type="search",
                handler=self._tool_web_search,
            )
        )
        self.register_tool(
            ToolDefinition(
                id="evidence_search",
                name="证据检索",
                description="从知识库检索相关证据（RAG）",
                tool_type="data_source",
                handler=self._tool_evidence_search,
            )
        )
        # === M4: 量化/基金工具 ===
        self.register_tool(
            ToolDefinition(
                id="quant_backtest",
                name="量化回测",
                description="通过本地量化回测引擎运行策略回测，返回收益率/夏普/回撤等指标",
                tool_type="calculator",
                handler=self._tool_quant_backtest,
            )
        )
        self.register_tool(
            ToolDefinition(
                id="fund_metrics",
                name="基金指标",
                description="获取基金净值序列并计算夏普/回撤/波动率/卡玛等指标",
                tool_type="calculator",
                handler=self._tool_fund_metrics,
            )
        )
        self.register_tool(
            ToolDefinition(
                id="dca_simulate",
                name="定投模拟",
                description="基于历史净值模拟定期定额投资的收益情况",
                tool_type="calculator",
                handler=self._tool_dca_simulate,
            )
        )
        self.register_tool(
            ToolDefinition(
                id="portfolio_rebalance",
                name="组合再平衡",
                description="根据目标权重计算基金组合再平衡交易建议",
                tool_type="calculator",
                handler=self._tool_portfolio_rebalance,
            )
        )

    def register_tool(self, tool: ToolDefinition):
        """注册工具"""
        self._tools[tool.id] = tool

    def get_tool(self, tool_id: str) -> Optional[ToolDefinition]:
        """获取工具定义"""
        return self._tools.get(tool_id)

    def list_tools(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        """列出所有工具"""
        tools = self._tools.values()
        if enabled_only:
            tools = [t for t in tools if t.enabled]
        return [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "type": t.tool_type,
                "requires_confirmation": t.requires_confirmation,
            }
            for t in tools
        ]

    def call_tool(self, tool_id: str, **kwargs) -> ToolCallResult:
        """调用工具"""
        tool = self._tools.get(tool_id)
        if not tool:
            return ToolCallResult(tool_id=tool_id, success=False, error=f"工具不存在: {tool_id}")
        if not tool.enabled:
            return ToolCallResult(tool_id=tool_id, success=False, error=f"工具已禁用: {tool_id}")

        # Rate limiting
        count = self._call_counts.get(tool_id, 0)
        if count >= tool.rate_limit:
            return ToolCallResult(
                tool_id=tool_id,
                success=False,
                error=f"超出频率限制 ({tool.rate_limit}/min)",
            )

        t0 = time.time()
        try:
            result = tool.handler(**kwargs)
            latency = (time.time() - t0) * 1000
            self._call_counts[tool_id] = count + 1

            call_result = ToolCallResult(
                tool_id=tool_id,
                success=True,
                data=result,
                latency_ms=round(latency, 1),
                timestamp=time.time(),
            )
            self._call_log.append(call_result)
            return call_result

        except Exception as e:
            latency = (time.time() - t0) * 1000
            call_result = ToolCallResult(
                tool_id=tool_id,
                success=False,
                error=str(e)[:200],
                latency_ms=round(latency, 1),
                timestamp=time.time(),
            )
            self._call_log.append(call_result)
            return call_result

    def get_call_log(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取调用日志"""
        return [
            {
                "tool_id": r.tool_id,
                "success": r.success,
                "latency_ms": r.latency_ms,
                "error": r.error,
            }
            for r in self._call_log[-limit:]
        ]

    # ============== 默认工具实现 ==============

    def _tool_market_data(self, symbol: str = "", **kwargs) -> Dict[str, Any]:
        """行情数据工具"""
        try:
            from backend.price_fetcher import get_price_range

            data = get_price_range(symbol, days=30)
            return {"symbol": symbol, "data": data}
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}

    def _tool_news_search(self, query: str = "", symbol: str = "", **kwargs) -> Dict[str, Any]:
        """新闻搜索工具"""
        try:
            from backend.news_data import fetch_news

            news = fetch_news(symbol or query, limit=5)
            return {"query": query, "results": news}
        except Exception as e:
            return {"query": query, "error": str(e)}

    def _tool_fund_flow(self, symbol: str = "", **kwargs) -> Dict[str, Any]:
        """资金流向工具"""
        try:
            from backend.fund_flow import get_stock_fund_flow

            data = get_stock_fund_flow(symbol)
            return {"symbol": symbol, "data": data}
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}

    def _tool_fundamentals(self, symbol: str = "", **kwargs) -> Dict[str, Any]:
        """基本面数据工具"""
        try:
            from backend.fundamentals import get_fundamentals

            data = get_fundamentals(symbol)
            return {"symbol": symbol, "data": data}
        except Exception as e:
            return {"symbol": symbol, "error": str(e)}

    def _tool_web_search(self, query: str = "", **kwargs) -> Dict[str, Any]:
        """网页搜索工具"""
        try:
            from backend.providers.web_search_provider import get_web_search_provider

            provider = get_web_search_provider()
            if not provider.is_available():
                return {"query": query, "error": "搜索服务未配置"}
            results = provider.search(query, max_results=5)
            return {
                "query": query,
                "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results],
            }
        except Exception as e:
            return {"query": query, "error": str(e)}

    def _tool_evidence_search(self, query: str = "", symbol: str = "", **kwargs) -> Dict[str, Any]:
        """证据检索工具（RAG）"""
        try:
            from backend.rag.retriever import Retriever

            retriever = Retriever()
            results = retriever.search(query, symbol=symbol, n_results=5)
            return {"query": query, "results": results}
        except Exception as e:
            return {"query": query, "error": str(e)}

    def _tool_quant_backtest(
        self,
        strategy_id: str = "",
        symbol: str = "",
        start_date: str = "",
        end_date: str = "",
        initial_capital: float = 1000000.0,
        **kwargs,
    ) -> Dict[str, Any]:
        """量化回测工具"""
        try:
            from backend.quant.local_runner import run_local_backtest_payload

            result = run_local_backtest_payload(
                strategy_id=strategy_id,
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                params=kwargs.get("params") if isinstance(kwargs.get("params"), dict) else None,
            )
            return {
                "run_id": result.get("run_id"),
                "strategy_id": result.get("strategy_id"),
                "symbol": result.get("symbol"),
                "status": result.get("status"),
                "metrics": result.get("metrics"),
                "data_source": result.get("data_source"),
                "source_status": result.get("source_status"),
            }
        except Exception as e:
            return {"error": str(e), "strategy_id": strategy_id, "symbol": symbol}

    def _tool_fund_metrics(self, fund_code: str = "", **kwargs) -> Dict[str, Any]:
        """基金指标工具"""
        try:
            import asyncio

            from backend.funds.metrics import calc_fund_metrics
            from backend.funds.providers import get_provider

            provider = get_provider()
            records = asyncio.run(provider.get_nav_history(fund_code))
            if not records:
                return {"fund_code": fund_code, "error": "无净值数据"}

            navs = [r["nav"] for r in records]
            metrics = calc_fund_metrics(navs)
            return {"fund_code": fund_code, "metrics": metrics}
        except Exception as e:
            return {"fund_code": fund_code, "error": str(e)}

    def _tool_dca_simulate(
        self,
        fund_code: str = "",
        amount: float = 1000,
        frequency: str = "monthly",
        start_date: str = "",
        end_date: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """定投模拟工具"""
        try:
            import asyncio

            from backend.funds.dca import DCASimulator
            from backend.funds.providers import get_provider
            from backend.schemas.funds import DCAFrequency

            provider = get_provider()
            records = asyncio.run(provider.get_nav_history(fund_code, start_date, end_date))
            if not records:
                return {"fund_code": fund_code, "error": "无净值数据"}

            freq_map = {
                "weekly": DCAFrequency.WEEKLY,
                "biweekly": DCAFrequency.BIWEEKLY,
                "monthly": DCAFrequency.MONTHLY,
                "quarterly": DCAFrequency.QUARTERLY,
            }
            simulator = DCASimulator()
            result = simulator.simulate(
                nav_records=records,
                amount=amount,
                frequency=freq_map.get(frequency, DCAFrequency.MONTHLY),
                start_date=start_date,
                end_date=end_date,
            )
            return {
                "fund_code": fund_code,
                "total_invested": result.total_invested,
                "final_value": result.final_value,
                "total_return": result.total_return,
                "annualized_return": result.annualized_return,
                "max_drawdown": result.max_drawdown,
                "investment_count": result.investment_count,
            }
        except Exception as e:
            return {"fund_code": fund_code, "error": str(e)}

    def _tool_portfolio_rebalance(
        self,
        holdings: list = None,
        target_weights: dict = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """组合再平衡工具"""
        try:
            holdings = holdings or []
            target_weights = target_weights or {}

            total_target = sum(target_weights.values())
            if total_target <= 0:
                return {"error": "目标权重总和必须大于 0"}

            normalized = {k: v / total_target for k, v in target_weights.items()}
            trades = []

            for fund_code, target_weight in normalized.items():
                current_weight = 0.0
                for h in holdings:
                    if h.get("fund_code") == fund_code:
                        current_weight = h.get("weight", 0.0)
                        break
                diff = target_weight - current_weight
                if abs(diff) > 0.001:
                    trades.append(
                        {
                            "fund_code": fund_code,
                            "action": "buy" if diff > 0 else "sell",
                            "weight_change": round(diff, 4),
                        }
                    )

            return {"trades": trades}
        except Exception as e:
            return {"error": str(e)}


# 单例
_router: Optional[ToolRouter] = None


def get_tool_router() -> ToolRouter:
    """获取全局工具路由器"""
    global _router
    if _router is None:
        _router = ToolRouter()
    return _router
