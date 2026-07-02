"""DuckDB/Parquet 数据湖 API(v1.9.20)。

把行情统一物化为列存 parquet, 用一条 SQL 跨标的批量扫描/选股。
duckdb 未安装时优雅降级(status.available=False);写入仅在显式「入湖」时发生;
对外查询只读守卫。纯历史筛选, 不预测不构成选股建议。

端点:
  GET    /api/datalake/status            数据湖概览(可用性/标的数/行数/范围)
  GET    /api/datalake/symbols           已入湖标的
  GET    /api/datalake/latest            每标的最新一根 bar 快照
  POST   /api/datalake/ingest            从价格面取数入湖 {symbols,...}
  POST   /api/datalake/screen            批量筛选 {filters, order_by, descending, limit}
  POST   /api/datalake/query             只读 SQL {sql, limit}
  DELETE /api/datalake/symbol/{symbol}   删除某标的
  DELETE /api/datalake/all               清空数据湖
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/datalake", tags=["datalake"])


# 请求体须为模块级类(FastAPI + from __future__ import annotations)。
class IngestBody(BaseModel):
    symbols: list[str] = []
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = Field(default=500, ge=1, le=2000)


class ScreenFilter(BaseModel):
    field: str
    op: str
    value: float


class ScreenBody(BaseModel):
    filters: list[ScreenFilter] = []
    order_by: str = "close"
    descending: bool = True
    limit: int = Field(default=100, ge=1, le=500)


class QueryBody(BaseModel):
    sql: str = ""
    limit: int = Field(default=500, ge=1, le=2000)


@router.get("/status", response_model=ApiResponse[dict])
def datalake_status():
    """数据湖概览。"""
    from backend.quant import datalake

    return ApiResponse(success=True, data=datalake.stats())


@router.get("/symbols", response_model=ApiResponse[dict])
def datalake_symbols():
    """已入湖标的列表。"""
    from backend.quant import datalake

    syms = datalake.list_symbols()
    return ApiResponse(success=True, data={"symbols": syms, "count": len(syms)})


@router.get("/latest", response_model=ApiResponse[dict])
def datalake_latest(limit: int = 500):
    """每标的最新一根 bar 快照。"""
    from backend.quant import datalake

    return ApiResponse(success=True, data=datalake.latest_snapshot(limit))


@router.post("/ingest", response_model=ApiResponse[dict])
def datalake_ingest(body: IngestBody):
    """从价格面取数并入湖(失败安全, 逐标的)。"""
    from backend.quant import datalake

    result = datalake.ingest_from_provider(
        body.symbols,
        start_date=body.start_date,
        end_date=body.end_date,
        limit=body.limit,
    )
    return ApiResponse(
        success=bool(result.get("ok")),
        data=result,
        error=result.get("reason") if not result.get("ok") else None,
    )


@router.post("/screen", response_model=ApiResponse[dict])
def datalake_screen(body: ScreenBody):
    """跨标的批量筛选(纯历史, 不构成选股建议)。"""
    from backend.quant import datalake

    filters = [f.model_dump() for f in body.filters]
    result = datalake.screen(
        filters, order_by=body.order_by, descending=body.descending, limit=body.limit
    )
    return ApiResponse(
        success=bool(result.get("ok")),
        data=result,
        error=result.get("reason") if not result.get("ok") else None,
    )


@router.post("/query", response_model=ApiResponse[dict])
def datalake_query(body: QueryBody):
    """对数据湖跑只读 SQL(表名 prices)。"""
    from backend.quant import datalake

    result = datalake.query(body.sql, limit=body.limit)
    return ApiResponse(
        success=bool(result.get("ok")),
        data=result,
        error=result.get("reason") if not result.get("ok") else None,
    )


@router.delete("/symbol/{symbol}", response_model=ApiResponse[dict])
def datalake_delete_symbol(symbol: str):
    """删除某标的的湖文件。"""
    from backend.quant import datalake

    ok = datalake.clear_symbol(symbol)
    return ApiResponse(success=ok, data={"deleted": ok})


@router.delete("/all", response_model=ApiResponse[dict])
def datalake_clear_all():
    """清空数据湖。"""
    from backend.quant import datalake

    n = datalake.clear_all()
    return ApiResponse(success=True, data={"deleted": n})
