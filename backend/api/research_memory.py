"""研究记忆 API (v1.9.18)

把每次 Agent 分析的结论快照(买入/卖出/观望 + 置信度 + 多空裁决 + 风控 + 数据核验)
落 SQLite, 供前端「研究记忆」页查看**同一股票研究结论随时间的变化轨迹**。
失败安全、不触网, 仅记录与回看历史, 不预测不建议。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/research-memory", tags=["research-memory"])


@router.get("/symbols")
async def list_memory_symbols(limit: int = Query(100, ge=1, le=500)):
    """列举有研究记忆的股票(按最近一次分析倒序)。"""
    from backend.quant import research_memory

    return ApiResponse(
        success=True,
        data={
            "symbols": research_memory.list_symbols(limit),
            "total": research_memory.count(),
        },
    )


@router.get("/timeline/{symbol}")
async def memory_timeline(symbol: str, limit: int = Query(200, ge=1, le=1000)):
    """某股票的研究记忆时间线:升序快照 + 变化转折 + 汇总。"""
    from backend.quant import research_memory

    return ApiResponse(success=True, data=research_memory.get_timeline(symbol, limit))


@router.delete("/snapshot/{snapshot_id}")
async def delete_memory_snapshot(snapshot_id: str):
    """删除单条快照。"""
    from backend.quant import research_memory

    ok = research_memory.delete_snapshot(snapshot_id)
    return ApiResponse(success=ok, data={"deleted": ok})


@router.delete("/symbol/{symbol}")
async def delete_memory_symbol(symbol: str):
    """删除某股票的全部研究记忆。"""
    from backend.quant import research_memory

    n = research_memory.delete_symbol(symbol)
    return ApiResponse(success=True, data={"deleted": n})
