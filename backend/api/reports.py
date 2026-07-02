"""报告中心 API — 暴露 archive.py 的报告管理功能"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/archive", tags=["archive"])


class ArchiveCreateRequest(BaseModel):
    """Create a lightweight archive entry from a generated frontend report."""

    stock_name: str = Field(default="", description="股票名称")
    symbol: str = Field(description="股票代码")
    content: str = Field(description="Markdown 报告正文")
    rating: str = Field(default="", description="报告评级")
    report_type: str = Field(default="frontend_report", description="报告类型")
    payload: dict[str, Any] = Field(default_factory=dict, description="报告元数据")


@router.get("")
async def list_reports(
    stock: Optional[str] = Query(None, description="股票名称/代码筛选"),
    decision: Optional[str] = Query(None, description="决策筛选（买/卖/持）"),
    date_from: Optional[str] = Query(None, description="起始日期 YYYYMMDD"),
    date_to: Optional[str] = Query(None, description="结束日期 YYYYMMDD"),
    type: Optional[str] = Query(None, description="类型: agent/roundtable"),
    limit: int = Query(200, ge=1, le=1000, description="返回数量"),
):
    """报告列表（支持筛选）"""
    from backend.archive import list_reports as _list

    reports = _list(
        stock_filter=stock,
        decision_filter=decision,
        date_from=date_from,
        date_to=date_to,
        type_filter=type,
        limit=limit,
    )
    return ApiResponse(success=True, data={"reports": reports, "total": len(reports)})


@router.post("")
async def create_report(req: ArchiveCreateRequest):
    """保存前端生成的 Markdown 报告到归档中心。"""
    if not req.symbol.strip():
        raise HTTPException(status_code=400, detail="缺少股票代码")
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="报告内容为空")

    from backend.archive import save_report

    rating = req.rating.strip() or "未评级"
    result = save_report(
        stock_name=req.stock_name.strip() or req.symbol.strip(),
        symbol=req.symbol.strip(),
        payload=req.payload or {},
        llm_result={
            "summary": {
                "final": rating,
                "avg_confidence": req.payload.get("confidence", 0),
            },
            "agents": {},
        },
        chairman_text=rating,
        report_md=req.content,
        dedupe_minutes=0,
        report_type=req.report_type or "frontend_report",
    )
    return ApiResponse(success=True, data=result)


@router.get("/stats")
async def get_stats():
    """全局统计"""
    from backend.archive import get_stats as _stats

    return ApiResponse(success=True, data=_stats())


@router.get("/combo-stats")
async def get_combo_stats():
    """模型组合统计"""
    from backend.archive import get_combo_stats as _combo

    return ApiResponse(success=True, data={"combos": _combo()})


@router.get("/report/{path:path}")
async def get_report(path: str):
    """读取报告内容"""
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="非法路径")
    from backend.archive import load_report as _load

    content = _load(path)
    if content.startswith("⚠️"):
        raise HTTPException(status_code=404, detail=content)
    return ApiResponse(success=True, data={"path": path, "content": content})


@router.delete("/report/{path:path}")
async def delete_report(path: str):
    """删除报告"""
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="非法路径")
    from backend.archive import delete_report as _delete

    deleted = _delete(path)
    if not deleted:
        return ApiResponse(success=False, error="报告不存在或路径不允许")
    return ApiResponse(success=True, data={"deleted": path})


@router.post("/backfill")
async def backfill_posteriors():
    """回填后验标签:为所有归档报告补齐 3/5/10/20 日收益、命中标签、10 日最大回撤。

    可选依赖 archive_tagger(import-guard);缺 akshare 时跳过,不抛。
    """
    try:
        from backend.archive_tagger import tag_all_reports
    except Exception as e:  # noqa: BLE001
        return ApiResponse(success=False, error=f"后验模块不可用: {str(e)[:120]}")
    result = tag_all_reports()
    return ApiResponse(success=True, data=result)
