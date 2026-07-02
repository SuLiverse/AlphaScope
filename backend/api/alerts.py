"""自选股监控告警 API — 通知中心的后端。

接出 ScheduledReportManager 的告警能力:
- GET  /api/alerts           列出告警(可选 ?unacknowledged_only=1 / ?limit=N)
- GET  /api/alerts/count      未确认告警数(供通知铃铛红点)
- POST /api/alerts/check      手动触发一次自选股扫描(写入新告警)
- POST /api/alerts/{id}/ack   确认单条告警
- POST /api/alerts/ack-all    确认全部告警
- POST /api/alerts/clear      清空告警(?acknowledged_only=1 只清已确认)

告警由后台定时扫描 + 用户手动触发共同写入 alert_store(SQLite 持久化)。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    unacknowledged_only: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
):
    """列出告警(按时间倒序)。"""
    from backend import alert_store

    return ApiResponse(
        success=True,
        data={
            "items": alert_store.list_alerts(
                unacknowledged_only=unacknowledged_only, limit=limit
            )
        },
    )


@router.get("/count")
def alert_count():
    """未确认告警数。"""
    from backend import alert_store

    return ApiResponse(
        success=True, data={"unacknowledged": alert_store.count_unacknowledged()}
    )


class CheckResponse(BaseModel):
    scanned: int
    new: int


@router.post("/check")
def check_alerts():
    """手动触发一次自选股告警扫描,返回扫描数与新增告警数。"""
    from backend.ingestion.scheduled_reports import get_scheduled_report_manager
    from backend.watchlist_store import list_watchlist

    manager = get_scheduled_report_manager()
    new_alerts = manager.check_alerts(persist=True)
    scanned = len(list_watchlist())
    return ApiResponse(
        success=True,
        data={"scanned": scanned, "new": len(new_alerts)},
    )


@router.post("/{alert_id}/ack")
def acknowledge(alert_id: str):
    """确认单条告警。"""
    from backend import alert_store

    ok = alert_store.acknowledge_alert(alert_id)
    return ApiResponse(success=ok, data={"acknowledged": ok})


@router.post("/ack-all")
def acknowledge_all():
    """确认全部告警。"""
    from backend import alert_store

    n = alert_store.acknowledge_all()
    return ApiResponse(success=True, data={"acknowledged": n})


@router.post("/clear")
def clear_alerts(acknowledged_only: bool = Query(default=False)):
    """清空告警。acknowledged_only=1 时只清已确认的。"""
    from backend import alert_store

    n = alert_store.clear_all(acknowledged_only=acknowledged_only)
    return ApiResponse(success=True, data={"cleared": n})
