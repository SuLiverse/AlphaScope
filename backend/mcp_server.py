"""AlphaScope MCP Server / 插件与工具协议 (Phase D #1, §7).

把 AlphaScope 的研究能力通过 **MCP (Model Context Protocol)** 暴露给外部 LLM 客户端
(Claude Desktop / 其他 MCP client), 让外部 AI 能调用 AlphaScope 的行情/财务/证据/
回测/集成中心能力 (对应战略规划 Phase D 第 1 项「AlphaScope MCP Server」与 §7)。

设计要点 (延续项目「确定性 · 失败安全 · No-Live-Order」基线):
- **可选依赖 + 优雅降级**: ``mcp`` 库用 import-guard 包裹, 没装不影响其余功能
  (``create_server`` 返回 None + ``is_available`` False)。
- **严格遵守交易边界**: MCP server **只暴露研究/数据/回测能力**, 显式**禁止**任何
  实盘下单工具 (submit_order / place_order / connect_live_broker 等)。这与规划 §7
  「禁止项」一致, 并由 trading_boundary 模块背书。
- **失败安全**: 每个 tool 内部 try/except, 单工具失败不影响 server; 返回结构化错误。
- **合规**: 所有 tool 仅研究语义, 输出附免责; 不预测、不荐股、不构成投资建议。

A​PI 已对照 mcp 1.x (FastMCP) 真实源码核对 (非臆测):
- ``from mcp.server.fastmcp import FastMCP``
- ``@mcp.tool()`` 装饰器注册工具 (自动从函数签名+docstring 生成 schema)
- ``mcp.list_tools()`` 列出; ``mcp.run()`` 启动 (stdio 默认)
- 输入参数类型注解 → JSON Schema 自动生成
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: mcp (FastMCP) 缺失时优雅降级 -----
try:
    from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]

    _MCP_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    FastMCP = None  # type: ignore[assignment]
    _MCP_AVAILABLE = False


# 规划 §7 明确禁止的工具名 (任何 MCP server 都不得注册这些)
FORBIDDEN_TOOL_NAMES: tuple[str, ...] = (
    "submit_order",
    "place_order",
    "cancel_order",
    "connect_live_broker",
    "auto_trade",
    "execute_trade",
    "live_gateway",
)

# 本 server 注册的研究语义工具名 (静态, 与 create_server() 内 @server.tool() 一一对应)。
# 用静态常量而非运行时 probe, 避免在 uvicorn 请求处理路径里调 FastMCP.list_tools()
# 触发 py_mini_racer/V8 重复初始化 (partition_address_space fatal 会打死整个进程)。
# 运行时 probe 仅由 list_tool_names() 在独立进程 (console_script 启动守卫 / 测试) 做。
REGISTERED_TOOLS: tuple[str, ...] = (
    "get_market_data",
    "search_evidence",
    "list_integrations",
    "get_trading_boundary",
    "is_trading_day",
)


# ============================================================
# Server 工厂
# ============================================================


def is_available() -> bool:
    """mcp 库是否就绪。"""
    return _MCP_AVAILABLE


def create_server() -> "FastMCP | None":
    """创建并注册 AlphaScope 的 MCP server, 暴露研究语义工具。

    返回 FastMCP 实例 (调用方 .run() 启动); mcp 不可用时返回 None。
    所有 tool 内部失败安全, 严格遵守 No-Live-Order 边界。
    """
    if not _MCP_AVAILABLE:
        return None

    server = FastMCP("AlphaScope")

    # ---------------- 行情/数据类 ----------------

    @server.tool()
    def get_market_data(symbol: str) -> str:
        """获取股票历史行情数据 (OHLCV)。仅返回历史数据, 不预测未来。

        Args:
            symbol: 股票代码, 如 "600519" (贵州茅台) 或 "000001"

        Returns:
            最近若干交易日的 OHLCV 摘要 (JSON 字符串)
        """
        try:
            # 复用 AlphaScope 现有 provider 链 (不触网交易, 只读历史)
            import json

            from backend.price_fetcher import fetch_prices

            bars = fetch_prices(symbol, period="daily", count=30)
            if not bars:
                # json.dumps 而非 f-string — symbol 含双引号会破坏 JSON
                return json.dumps({"error": f"无 {symbol} 行情数据"}, ensure_ascii=False)

            rows = [
                {
                    "date": str(b.get("date", ""))[:10],
                    "close": float(b.get("close", 0)),
                    "volume": float(b.get("volume", 0)),
                }
                for b in bars[-10:]  # 只返回最近 10 日, 控制 token
            ]
            return json.dumps({"symbol": symbol, "bars": rows}, ensure_ascii=False)
        except Exception as e:
            return f'{{"error": "获取行情失败: {str(e)[:100]}"}}'

    @server.tool()
    def search_evidence(query: str, top_k: int = 5) -> str:
        """在证据库 / RAG 中检索研究证据 (财报/新闻/公告片段)。

        Args:
            query: 检索查询, 如 "茅台业绩" 或 "新能源补贴"
            top_k: 返回条数 (默认 5, 上限 20)

        Returns:
            匹配的证据片段列表 (JSON 字符串, 含来源与得分)
        """
        try:
            from backend.rag.hybrid_retriever import retrieve

            import json

            k = max(1, min(int(top_k), 20))
            hits = retrieve(query, top_k=k)
            if not hits:
                # 用 json.dumps 而非 f-string 拼 — query 含双引号会破坏 JSON 结构
                return json.dumps({"query": query, "hits": []}, ensure_ascii=False)
            rows = [
                {
                    "content": str(getattr(h, "content", h.get("content", "")))[:300],
                    "source": str(getattr(h, "source", h.get("source", "")))[:80],
                    "score": float(getattr(h, "score", h.get("score", 0.0))),
                }
                for h in hits
            ]
            return json.dumps({"query": query, "hits": rows}, ensure_ascii=False)
        except Exception as e:
            return f'{{"error": "证据检索失败: {str(e)[:100]}"}}'

    # ---------------- 集成中心 / 边界 ----------------

    @server.tool()
    def list_integrations() -> str:
        """列出 AlphaScope 已注册的外部项目 adapter (vectorBT/OpenBB/Qlib/...) 及健康状态。

        Returns:
            adapter 列表 (JSON 字符串, 含 category/license/health)
        """
        try:
            from backend.integrations.registry import get_registry

            reg = get_registry()
            import json

            items = [
                {
                    "name": m.name,
                    "category": m.category.value,
                    "display_name": m.display_name,
                    "license_safety": m.license_safety.value,
                    "allow_live_order": m.allow_live_order,
                }
                for m in reg.all_metadata()
            ]
            return json.dumps(
                {"integrations": items, "count": len(items)}, ensure_ascii=False
            )
        except Exception as e:
            return f'{{"error": "集成中心查询失败: {str(e)[:100]}"}}'

    @server.tool()
    def get_trading_boundary() -> str:
        """查询 AlphaScope 的交易边界 (No-Live-Order 红线状态)。

        Returns:
            边界标志与 live_order_blocked 状态 (JSON 字符串)
        """
        try:
            from backend.security.trading_boundary import describe_capabilities

            info = describe_capabilities()
            import json

            return json.dumps(info, ensure_ascii=False, default=str)
        except Exception as e:
            return f'{{"error": "边界查询失败: {str(e)[:100]}"}}'

    @server.tool()
    def is_trading_day(date: str, market: str = "XSHG") -> str:
        """判断某日是否为指定市场的交易日 (节假日/周末识别)。

        Args:
            date: 日期, 如 "2024-01-02"
            market: 市场代码, 默认 "XSHG" (上交所); 也支持 XSHE/NYSE 等

        Returns:
            {"date": ..., "is_trading_day": bool, "market": ...}
        """
        try:
            from backend.trading_calendar import is_trading_day as _isd

            result = _isd(date, market)
            import json

            return json.dumps(
                {"date": date, "market": market, "is_trading_day": bool(result)},
                ensure_ascii=False,
            )
        except Exception as e:
            return f'{{"error": "日历查询失败: {str(e)[:100]}"}}'

    return server


def list_tool_names() -> list[str]:
    """返回 server 注册的所有工具名 (运行时 probe)。

    注意: 本函数会在当前进程创建 FastMCP server 并 asyncio.run(list_tools())。
    在已运行事件循环的进程里 (uvicorn / 已有 loop) 多次调用, FastMCP 底层
    py_mini_racer/V8 的 PartitionAlloc 可能重复初始化触发 fatal abort。
    **仅供独立进程使用** (alphascope-mcp console_script 启动守卫、单元测试)。
    uvicorn 请求处理路径请改用 describe() (返回静态 REGISTERED_TOOLS)。
    """
    if not _MCP_AVAILABLE:
        return []
    server = create_server()
    if server is None:
        return []
    try:
        import asyncio

        tools = asyncio.run(server.list_tools())
        return [t.name for t in tools]
    except Exception:
        return []


def assert_no_forbidden_tools() -> None:
    """断言 MCP server 未注册任何实盘下单工具 (Phase D 边界守卫)。

    由测试调用; 若发现禁止工具名, 抛 AssertionError。
    """
    names = list_tool_names()
    violations = [n for n in names if n in FORBIDDEN_TOOL_NAMES]
    if violations:
        raise AssertionError(
            f"MCP server 注册了禁止的工具: {violations} (AlphaScope 不暴露实盘下单能力)"
        )


def describe() -> dict[str, Any]:
    """MCP 能力概览 (供 UI/调试)。

    **静态**: 不在运行时 probe FastMCP, 直接返回 REGISTERED_TOOLS, 因此可在
    uvicorn 请求处理路径安全调用 (不会触发 py_mini_racer/V8 重复初始化 fatal)。
    """
    return {
        "available": _MCP_AVAILABLE,
        "tool_count": len(REGISTERED_TOOLS) if _MCP_AVAILABLE else 0,
        "tools": list(REGISTERED_TOOLS) if _MCP_AVAILABLE else [],
        "forbidden_tools": list(FORBIDDEN_TOOL_NAMES),
        "note": (
            "mcp 就绪: 暴露 get_market_data / search_evidence / list_integrations / "
            "get_trading_boundary / is_trading_day 等研究语义工具; 严格遵守 No-Live-Order。"
            if _MCP_AVAILABLE
            else "mcp 未安装。pip install 'mcp[cli]' 启用 MCP server (暴露研究工具给外部 LLM)。"
        ),
    }


def run_server() -> int:
    """启动 MCP server (stdio 传输), 供 console_script / ``python -m`` 调用。

    启动前先断言未注册禁止工具(No-Live-Order 边界);mcp 未安装时打印提示并返回非零。
    返回退出码 (0 成功)。
    """
    if not _MCP_AVAILABLE:
        print(
            "mcp 库未安装。启用 MCP server 请执行: pip install 'mcp[cli]'",
            flush=True,
        )
        return 1

    # 边界守卫:绝不暴露实盘下单工具
    assert_no_forbidden_tools()

    server = create_server()
    if server is None:
        print("MCP server 创建失败", flush=True)
        return 1

    # FastMCP.run() 默认 stdio 传输, 由外部 MCP client (Claude Desktop 等) 拉起
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_server())
