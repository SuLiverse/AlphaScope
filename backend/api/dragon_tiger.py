"""龙虎榜 / 游资席位 API — A 股「机构 vs 游资」博弈。

数据来自 :class:`backend.providers.dragontiger_provider.DragonTigerProvider`
(akshare 龙虎榜 + 席位库)。移植自 UZI-Skill (MIT)。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query

from backend.schemas.api import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dragon-tiger", tags=["dragon-tiger"])


@router.get("/{symbol}")
async def get_dragon_tiger(symbol: str, days: int = Query(default=30, ge=1, le=90)):
    """个股龙虎榜:近 N 日上榜 + 知名游资席位匹配 + 机构/游资净额拆分(仅 A 股)。"""
    from backend.providers.dragontiger_provider import DragonTigerProvider

    try:
        data = DragonTigerProvider().get_dragon_tiger({"symbol": symbol, "days": days})
        return ApiResponse(success=True, data=data or {"lhb_count_30d": 0, "matched_youzi": []})
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[dragon-tiger] %s 失败: %s", symbol, exc)
        return ApiResponse(
            success=False,
            data={"symbol": symbol},
            error=str(exc),
            error_code="DRAGON_TIGER_FAILED",
        )


@router.get("/{symbol}/trap")
def scan_trap(symbol: str, name: str | None = Query(default=None)):
    """杀猪盘(拉高出货/荐股诈骗)信号扫描 — 8 类推广痕迹关键词检测(基于网搜)。"""
    from backend.dragon_tiger.trap_signals import scan_trap_signals

    target = (name or symbol).strip()
    try:
        return ApiResponse(success=True, data=scan_trap_signals(target))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[trap] %s 失败: %s", symbol, exc)
        return ApiResponse(
            success=False,
            data={"symbol": symbol},
            error=str(exc),
            error_code="TRAP_SCAN_FAILED",
        )
