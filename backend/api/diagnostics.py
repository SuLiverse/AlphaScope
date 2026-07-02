"""日志与诊断 API — traces/工具调用/模型调用/健康历史/汇总"""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("/traces")
async def get_traces(limit: int = 50):
    """最近 trace/span"""
    try:
        from backend.observability.tracer import get_tracer

        tracer = get_tracer()
        stats = tracer.get_stats()
        return ApiResponse(success=True, data={"stats": stats})
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.get("/tool-calls")
async def get_tool_calls(limit: int = 50):
    """工具调用日志"""
    from backend.diagnostics_store import list_tool_calls as _list

    items = _list(limit=limit)
    return ApiResponse(success=True, data={"tool_calls": items, "total": len(items)})


@router.get("/model-calls")
async def get_model_calls(model: str | None = None, limit: int = 50):
    """模型调用日志"""
    from backend.diagnostics_store import list_cost_records as _list

    items = _list(model=model, limit=limit)
    return ApiResponse(success=True, data={"model_calls": items, "total": len(items)})


@router.get("/health-history")
async def get_health_history(limit: int = 50):
    """数据源健康历史"""
    from backend.diagnostics_store import get_health_history as _get

    items = _get(limit=limit)
    return ApiResponse(success=True, data={"history": items, "total": len(items)})


@router.get("/errors")
async def get_errors(limit: int = 50):
    """错误日志（工具调用错误 + 健康检查错误）"""
    from backend.diagnostics_store import get_health_history, list_tool_calls

    tc_errors = [t for t in list_tool_calls(limit=limit) if t.get("status") != "ok"]
    health_errors = [
        h for h in get_health_history(limit=limit) if h.get("status") == "error"
    ]
    return ApiResponse(
        success=True,
        data={"tool_call_errors": tc_errors, "health_errors": health_errors},
    )


@router.get("/summary")
async def get_summary():
    """汇总诊断统计"""
    from backend.diagnostics_store import get_diagnostics_summary

    summary = get_diagnostics_summary()
    return ApiResponse(success=True, data=summary)


@router.get("/cost-summary")
async def get_cost_summary():
    """LLM 调用成本汇总:今日/近7天/近30天/累计 + 按模型明细。"""
    from backend.diagnostics_store import get_cost_summary as _summary

    return ApiResponse(success=True, data=_summary())


@router.get("/mcp")
async def get_mcp_status():
    """MCP server 能力概览 + 启动方式(供 UI/诊断)。

    暴露 mcp_server.describe() + console_script 启动命令, 让用户知道如何把
    AlphaScope 的研究能力接到 Claude Desktop 等外部 LLM。
    """
    from backend.mcp_server import describe

    info = describe()
    info["start_command"] = "alphascope-mcp  # 或 python -m backend.mcp_server"
    info["claude_desktop_config"] = {
        "command": "alphascope-mcp",
        "note": "把此段加入 Claude Desktop 的 mcpServers 配置即可调用 AlphaScope 研究工具",
    }
    return ApiResponse(success=True, data=info)
