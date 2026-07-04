"""估值建模 API — DCF / Comps / LBO / 三表。

支持通过查询参数调整关键假设(stage1_growth / terminal_g / beta)做情景分析。
移植自 UZI-Skill (MIT) 的估值引擎，见 ``docs/uzi-integration/ATTRIBUTION.md``。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from backend.schemas.api import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/valuation", tags=["valuation"])


@router.get("/{symbol}")
async def get_valuation(
    symbol: str,
    stage1_growth: float | None = Query(default=None, ge=-0.5, le=1.0, description="一阶段 FCF 年增速(小数,如 0.10)"),
    terminal_g: float | None = Query(default=None, ge=0.0, le=0.2, description="永续增长率(小数,如 0.025)"),
    beta: float | None = Query(default=None, ge=0.1, le=3.0, description="贝塔(影响 WACC)"),
):
    """对个股运行机构级估值建模(DCF/Comps/LBO/三表);可调假设做情景分析。"""
    from backend.valuation import value_symbol

    assumptions: dict = {}
    if stage1_growth is not None:
        assumptions["stage1_growth"] = stage1_growth
    if terminal_g is not None:
        assumptions["terminal_g"] = terminal_g
    if beta is not None:
        assumptions["beta"] = beta

    try:
        data = value_symbol(symbol, assumptions or None)
        return ApiResponse(success=True, data=data)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[valuation] %s 估值失败: %s", symbol, exc)
        return ApiResponse(
            success=False,
            data={"symbol": symbol},
            error=str(exc),
            error_code="VALUATION_FAILED",
        )
