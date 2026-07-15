"""Tests for Task Queue API — 任务队列端点"""

from __future__ import annotations

import time
from datetime import date, timedelta
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_list_tasks(client):
    """GET /api/tasks 返回任务列表"""
    mock_tasks = [
        {
            "id": "abc123",
            "task_type": "analysis",
            "status": "success",
            "created_at": time.time(),
        },
        {
            "id": "def456",
            "task_type": "analysis",
            "status": "running",
            "created_at": time.time(),
        },
    ]
    with patch("backend.task_queue.TaskQueue.list_tasks", return_value=mock_tasks):
        resp = await client.get("/api/tasks")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["tasks"]) == 2


@pytest.mark.anyio
async def test_list_tasks_with_status_filter(client):
    """GET /api/tasks?status=running 筛选"""
    with patch("backend.task_queue.TaskQueue.list_tasks", return_value=[]) as mock:
        resp = await client.get("/api/tasks?status=running&limit=10")
    assert resp.status_code == 200
    mock.assert_called_once_with(status="running", limit=10)


@pytest.mark.anyio
async def test_get_task(client):
    """GET /api/tasks/{id} 返回任务详情"""
    mock_task = {
        "id": "abc123",
        "task_type": "analysis",
        "status": "success",
        "output_json": '{"result": "ok"}',
        "error": "",
        "created_at": time.time(),
    }
    with patch("backend.task_queue.TaskQueue.get_task", return_value=mock_task):
        resp = await client.get("/api/tasks/abc123")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["id"] == "abc123"
    assert data["data"]["status"] == "success"


@pytest.mark.anyio
async def test_get_task_not_found(client):
    """GET /api/tasks/{id} 任务不存在"""
    with patch("backend.task_queue.TaskQueue.get_task", return_value=None):
        resp = await client.get("/api/tasks/nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "不存在" in data["error"]


@pytest.mark.anyio
async def test_cancel_task(client):
    """POST /api/tasks/{id}/cancel 取消任务"""
    with patch("backend.task_queue.TaskQueue.cancel_task", return_value=True):
        resp = await client.post("/api/tasks/abc123/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["cancelled"] == "abc123"


@pytest.mark.anyio
async def test_cancel_task_not_found(client):
    """POST /api/tasks/{id}/cancel 任务不存在或已完成"""
    with patch("backend.task_queue.TaskQueue.cancel_task", return_value=False):
        resp = await client.post("/api/tasks/abc123/cancel")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False


@pytest.mark.anyio
async def test_async_analysis_records_cutoff_and_question_in_task_input(client):
    with patch("backend.task_queue.TaskQueue.submit", return_value="snap1234") as submit:
        resp = await client.post(
            "/api/analysis/async",
            json={
                "stock_symbol": "600519",
                "stock_name": "贵州茅台",
                "as_of": "2026-06-30",
                "research_question": "利润增长是否可持续？",
            },
        )

    assert resp.status_code == 200
    assert resp.json()["data"]["task_id"] == "snap1234"
    input_data = submit.call_args.kwargs["input_data"]
    assert input_data["as_of"] == "2026-06-30"
    assert input_data["research_question"] == "利润增长是否可持续？"


@pytest.mark.anyio
async def test_async_analysis_populates_quant_referee_indicators(client):
    first_day = date(2026, 4, 1)
    bars = [
        {
            "date": (first_day + timedelta(days=index)).isoformat(),
            "open": 99 + index,
            "close": 100 + index,
            "high": 101 + index,
            "low": 98 + index,
            "volume": 1_000 + index * 10,
            "amount": 1_000_000,
        }
        for index in range(65)
    ]
    captured: dict = {}

    def fake_run_agents_with_mode(*, stock_data, **_kwargs):
        captured.update(stock_data)
        return {
            "mode": "deep",
            "summary": {"final": "观望"},
            "agents": {},
            "model_status": {"ok_agents": 0, "total_agents": 0},
        }

    def run_submitted_task(*, func, **_kwargs):
        func()
        return "quant123"

    with (
        patch("backend.price_store.get_prices", return_value=bars),
        patch("backend.runtime.orchestrator.run_agents_with_mode", side_effect=fake_run_agents_with_mode),
        patch("backend.task_queue.TaskQueue.submit", side_effect=run_submitted_task),
    ):
        response = await client.post(
            "/api/analysis/async",
            json={"stock_symbol": "600519", "stock_name": "贵州茅台", "mode": "deep"},
        )

    assert response.status_code == 200
    assert response.json()["data"]["task_id"] == "quant123"
    for field in ("ma5", "ma20", "ma60", "rsi", "dif", "dea", "macd", "vol_ratio"):
        assert isinstance(captured[field], float), field


@pytest.mark.anyio
async def test_async_analysis_rejects_future_cutoff(client):
    resp = await client.post(
        "/api/analysis/async",
        json={"stock_symbol": "600519", "as_of": "2099-01-01"},
    )

    assert resp.status_code == 422


@pytest.mark.anyio
async def test_submit_task():
    """TaskQueue.submit 返回 task_id 并执行任务"""
    from backend.task_queue import TaskQueue

    # Reset singleton for test
    original = TaskQueue._instance
    TaskQueue._instance = None

    try:
        q = TaskQueue()
        result_box = []

        def slow_func():
            time.sleep(0.1)
            result_box.append("done")
            return {"status": "ok"}

        task_id = q.submit("test", slow_func)
        assert len(task_id) == 8

        # 等待完成
        for _ in range(50):
            task = q.get_task(task_id)
            if task["status"] == "success":
                break
            time.sleep(0.05)

        assert task["status"] == "success"
        assert result_box == ["done"]
    finally:
        TaskQueue._instance = original


@pytest.mark.anyio
async def test_task_failure():
    """任务失败时状态更新为 failed"""
    from backend.task_queue import TaskQueue

    original = TaskQueue._instance
    TaskQueue._instance = None

    try:
        q = TaskQueue()

        def fail_func():
            raise ValueError("test error")

        task_id = q.submit("test", fail_func)

        for _ in range(50):
            task = q.get_task(task_id)
            if task["status"] == "failed":
                break
            time.sleep(0.05)

        assert task["status"] == "failed"
        assert "test error" in task["error"]
    finally:
        TaskQueue._instance = original


def test_build_analysis_stock_data_honors_cutoff_and_records_price_date():
    from backend.api.tasks import _build_analysis_stock_data

    bars = [
        {
            "date": f"2026-06-{day:02d}",
            "open": 100 + day,
            "high": 102 + day,
            "low": 99 + day,
            "close": 101 + day,
            "volume": 1000,
            "amount": 10000,
        }
        for day in range(1, 31)
    ]
    with patch("backend.price_store.get_prices", return_value=bars) as get_prices:
        result = _build_analysis_stock_data(
            "600519",
            "贵州茅台",
            as_of=date(2026, 6, 30),
            research_question="利润增长是否可持续？",
        )

    assert get_prices.call_args.kwargs["end_date"] == "2026-06-30"
    assert result["as_of"] == "2026-06-30"
    assert result["price_data_date"] == "2026-06-30"
    assert result["research_question"] == "利润增长是否可持续？"
