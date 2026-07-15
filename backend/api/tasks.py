"""任务中心 API — 后台任务管理"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import date, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from backend.schemas.api import ApiResponse

router = APIRouter(tags=["tasks"])


def _build_analysis_stock_data(
    symbol: str,
    stock_name: str,
    *,
    as_of: Optional[date] = None,
    research_question: str = "",
) -> dict[str, Any]:
    """Build a real market snapshot for report generation instead of empty zeros."""
    from backend.api.analysis_stock_data import build_analysis_stock_data
    from backend.price_quality import filter_incompatible_price_bars
    from backend.price_store import get_prices, normalize_symbol, save_price_bars
    from backend.providers.registry import get_registry

    code = normalize_symbol(symbol) or symbol
    end_date = as_of.isoformat() if as_of else ""
    bars = get_prices(
        symbol=code,
        frequency="1d",
        end_date=end_date or None,
        limit=90,
        include_incompatible=True,
    )
    bars = filter_incompatible_price_bars(bars)

    if len(bars) < 30:
        try:
            registry = get_registry()
            cutoff = as_of or date.today()
            provider_end_date = cutoff.strftime("%Y%m%d")
            start_date = (cutoff - timedelta(days=240)).strftime("%Y%m%d")
            fetched = registry.get(
                data_type="prices",
                market="HK" if len(code) == 5 else "CN",
                symbol=code,
                limit=120,
                start_date=start_date,
                end_date=provider_end_date,
                period="daily",
                frequency="1d",
                adjust="",
            )
            if fetched:
                save_price_bars(fetched)
                bars = filter_incompatible_price_bars(
                    get_prices(
                        symbol=code,
                        frequency="1d",
                        end_date=end_date or None,
                        limit=90,
                        include_incompatible=True,
                    )
                )
        except Exception:
            bars = bars or []

    return build_analysis_stock_data(
        symbol,
        stock_name,
        bars,
        as_of=end_date,
        research_question=research_question,
    )


def _estimate_task_progress(task: dict[str, Any]) -> int:
    status = task.get("status")
    if status in {"success", "failed", "cancelled"}:
        return 100
    if status == "pending":
        return 8

    started_at = task.get("started_at") or task.get("created_at") or time.time()
    try:
        elapsed = max(0.0, time.time() - float(started_at))
    except (TypeError, ValueError):
        elapsed = 0.0
    return min(92, 18 + int(elapsed * 2))


def _task_to_event(task: dict[str, Any]) -> dict[str, Any]:
    status = task.get("status") or "pending"
    event_type = {
        "success": "task_completed",
        "failed": "task_failed",
        "cancelled": "task_cancelled",
    }.get(status, "task_progress")

    message = {
        "pending": "任务已进入队列",
        "running": "后台正在生成报告",
        "success": "报告生成完成",
        "failed": "报告生成失败",
        "cancelled": "任务已取消",
    }.get(status, "任务状态已更新")

    return {
        "type": event_type,
        "task_id": task.get("id"),
        "status": status,
        "progress": _estimate_task_progress(task),
        "message": message,
        "error": task.get("error") or "",
    }


def _sse_data(payload: dict[str, Any] | str) -> str:
    if isinstance(payload, str):
        return f"data: {payload}\n\n"
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


class AsyncAnalysisRequest(BaseModel):
    stock_symbol: str = Field(description="股票代码")
    stock_name: str = Field(default="", description="股票名称")
    mode: str = Field(default="deep", description="分析模式: standard/deep/auto")
    conversation_id: str = Field(default="", description="会话 ID")
    agent_configs: Optional[list[dict[str, Any]]] = Field(default=None, description="Agent 配置覆盖")
    global_ai_settings: Optional[dict[str, Any]] = Field(default=None, description="全局 AI 模型设置")
    as_of: Optional[date] = Field(default=None, description="研究数据截止日；为空表示使用当前可用数据")
    research_question: str = Field(default="", max_length=2_000, description="本次研究要回答的具体问题")
    report_template: str = Field(
        default="standard",
        description="研报大纲范式: standard(个股深度) / macro(行业专题) / risk(黑天鹅预警)",
    )

    @field_validator("as_of")
    @classmethod
    def reject_future_as_of(cls, value: Optional[date]) -> Optional[date]:
        if value and value > date.today():
            raise ValueError("研究数据截止日不能晚于今天")
        return value


@router.get("/api/tasks")
async def list_tasks(
    status: Optional[str] = Query(None, description="状态筛选: pending/running/success/failed/cancelled"),
    limit: int = Query(50, ge=1, le=500, description="返回数量"),
):
    """任务列表"""
    from backend.task_queue import TaskQueue

    tasks = TaskQueue().list_tasks(status=status, limit=limit)
    return ApiResponse(success=True, data={"tasks": tasks, "total": len(tasks)})


@router.get("/api/tasks/events")
async def stream_task_events(
    task_id: Optional[str] = Query(None, description="只监听指定任务 ID"),
    limit: int = Query(50, ge=1, le=200, description="未指定任务时监听的最近任务数"),
):
    """任务状态事件流。

    当前任务队列没有细粒度进度回调，因此这里把数据库任务状态转换为稳定的 SSE
    事件，供前端报告生成页展示“已启动/运行中/成功/失败”的可见反馈。
    """
    from backend.task_queue import TaskQueue

    async def event_generator():
        queue = TaskQueue()
        terminal_sent: set[str] = set()

        while True:
            if task_id:
                task = queue.get_task(task_id)
                if not task:
                    yield _sse_data(
                        {
                            "type": "task_failed",
                            "task_id": task_id,
                            "status": "failed",
                            "progress": 100,
                            "message": "任务不存在",
                            "error": "任务不存在或已被清理",
                        }
                    )
                    return
                tasks = [task]
            else:
                tasks = queue.list_tasks(limit=limit)

            emitted = False
            for task in tasks:
                current_task_id = str(task.get("id") or "")
                if not current_task_id:
                    continue
                status = task.get("status") or "pending"
                if status in {"success", "failed", "cancelled"}:
                    if current_task_id in terminal_sent:
                        continue
                    terminal_sent.add(current_task_id)

                yield _sse_data(_task_to_event(task))
                emitted = True

            if not emitted:
                yield _sse_data(": heartbeat")

            await asyncio.sleep(1)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """任务详情"""
    from backend.task_queue import TaskQueue

    task = TaskQueue().get_task(task_id)
    if not task:
        return ApiResponse(success=False, error="任务不存在")
    return ApiResponse(success=True, data=task)


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """取消任务"""
    from backend.task_queue import TaskQueue

    cancelled = TaskQueue().cancel_task(task_id)
    if not cancelled:
        return ApiResponse(success=False, error="任务不存在或已完成")
    return ApiResponse(success=True, data={"cancelled": task_id})


@router.post("/api/analysis/async")
async def run_analysis_async(req: AsyncAnalysisRequest):
    """异步运行分析（返回 task_id）"""
    from backend.task_queue import TaskQueue

    def _run():
        from backend.runtime.orchestrator import run_agents_with_mode
        from backend.agent_modes import AnalysisMode

        mode_map = {
            "standard": AnalysisMode.STANDARD,
            "deep": AnalysisMode.DEEP,
            "auto": AnalysisMode.AUTO,
        }
        mode = mode_map.get(req.mode, AnalysisMode.DEEP)
        stock_data = _build_analysis_stock_data(
            req.stock_symbol,
            req.stock_name,
            as_of=req.as_of,
            research_question=req.research_question,
        )
        result = run_agents_with_mode(
            stock_data=stock_data,
            mode=mode,
            agent_configs=req.agent_configs,
            global_ai_settings=req.global_ai_settings,
        )
        # 回显用户选择的研报范式, 供前端导出/排版使用(不改变分析本身)
        if isinstance(result, dict):
            result["report_template"] = req.report_template
        return result

    task_id = TaskQueue().submit(
        task_type="analysis",
        func=_run,
        conversation_id=req.conversation_id,
        input_data={
            "stock_symbol": req.stock_symbol,
            "stock_name": req.stock_name,
            "mode": req.mode,
            "report_template": req.report_template,
            "agent_configs": req.agent_configs,
            "global_ai_settings": req.global_ai_settings,
            "as_of": req.as_of.isoformat() if req.as_of else "",
            "research_question": req.research_question,
        },
    )
    return ApiResponse(success=True, data={"task_id": task_id, "status": "pending"})
