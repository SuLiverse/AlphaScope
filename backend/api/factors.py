"""量化因子 API — 因子报告、批量分析"""

from __future__ import annotations

from fastapi import APIRouter

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/factors", tags=["factors"])


# 注意路由声明顺序:字面路径(/batch, /alternative, /alternative/{symbol})必须先于
# 参数路径 /{symbol} 声明, 否则 GET /alternative 会被 /{symbol} 吞掉(symbol="alternative")。


@router.post("/batch")
def get_factors_batch(
    symbols: list[str],
    stock_names: dict[str, str] | None = None,
    days: int = 30,
):
    """批量获取量化因子报告"""
    from backend.factors.generator import generate_factor_batch

    reports = generate_factor_batch(symbols, stock_names=stock_names, days=days)
    return ApiResponse(
        success=True,
        data={"reports": [r.to_dict() for r in reports], "total": len(reports)},
    )


@router.get("/alternative")
def get_alternative_factors_macro():
    """仅宏观的替代因子(不指定个股):FRED 宏观风险偏好。"""
    from backend.alternative_factors import build_vector

    return ApiResponse(success=True, data=build_vector(""))


@router.get("/alternative/{symbol}")
def get_alternative_factors(symbol: str):
    """替代因子(另类数据):FRED 宏观风险偏好 + Finnhub 美股情绪/内部人交易。

    把「注册了但无消费链路」的 FRED/finnhub provider 能力转成归一化因子向量。
    provider 不可用/缺凭证 → 对应因子 None + degraded, 不抛。
    """
    from backend.alternative_factors import build_vector

    return ApiResponse(success=True, data=build_vector(symbol))


@router.get("/{symbol}")
def get_factors(symbol: str, stock_name: str = "", days: int = 30):
    """获取单只股票的量化因子报告"""
    from backend.factors.generator import generate_factor_report

    report = generate_factor_report(symbol, stock_name=stock_name, days=days)
    return ApiResponse(success=True, data=report.to_dict())
