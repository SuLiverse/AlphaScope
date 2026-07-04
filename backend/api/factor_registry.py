"""因子注册中心 / 研究流水线 API(v1.9.21)。

统一因子目录 + 确定性技术因子计算 + 跨标的因子矩阵 + 缓存。
纯确定性、失败安全、不触网(技术因子从本地行情算)。因子为历史量价度量,
不预测、不构成选股建议。

端点:
  GET  /api/factor-registry/catalog          因子目录(可按 category/source 过滤)
  GET  /api/factor-registry/symbol/{symbol}  单标的技术因子向量
  POST /api/factor-registry/matrix           跨标的因子矩阵 {symbols}
  GET  /api/factor-registry/cached/{symbol}  取缓存因子向量
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/factor-registry", tags=["factor-registry"])


class MatrixBody(BaseModel):
    symbols: list[str] = []
    use_cache: bool = True


@router.get("/catalog", response_model=ApiResponse[dict])
def factor_catalog(category: Optional[str] = None, source: Optional[str] = None):
    """因子目录(注册的全部因子定义)。"""
    from backend.quant import factor_registry

    factors = factor_registry.list_factors(category=category, source=source)
    return ApiResponse(success=True, data={"factors": factors, "count": len(factors)})


@router.get("/symbol/{symbol}", response_model=ApiResponse[dict])
def factor_for_symbol(symbol: str):
    """单标的的确定性技术因子向量(从本地行情计算并缓存)。"""
    from backend.quant import factor_registry

    return ApiResponse(success=True, data=factor_registry.compute_for_symbol(symbol))


@router.post("/matrix", response_model=ApiResponse[dict])
def factor_matrix(body: MatrixBody):
    """跨标的因子矩阵(研究流水线)。"""
    from backend.quant import factor_registry

    data = factor_registry.compute_matrix(body.symbols, use_cache=body.use_cache)
    return ApiResponse(success=True, data=data)


@router.get("/cached/{symbol}", response_model=ApiResponse[dict])
def factor_cached(symbol: str):
    """取缓存的因子向量(最新截面)。"""
    from backend.quant import factor_registry

    vec = factor_registry.get_cached_vector(symbol)
    return ApiResponse(success=bool(vec is not None), data={"symbol": symbol, "factors": vec or {}})
