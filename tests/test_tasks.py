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


class _StubQueue:
    """只实现 _collect_task_events 依赖的最小查询接口"""

    def __init__(self, task):
        self._task = task

    def get_task(self, task_id):
        return self._task

    def list_tasks(self, limit=50):
        return [self._task] if self._task else []


def _terminal_task(task_id: str, status: str) -> dict:
    return {"id": task_id, "status": status, "error": "", "created_at": time.time()}


def test_collect_task_events_terminal_sets_done():
    """指定任务到终态时 _collect_task_events 返回 done=True 且事件含终态状态"""
    from backend.api.tasks import _collect_task_events

    events, done = _collect_task_events(_StubQueue(_terminal_task("term0001", "success")), "term0001", 50, set())
    assert done is True
    assert len(events) == 1
    assert events[0]["task_id"] == "term0001"
    assert events[0]["status"] == "success"
    assert events[0]["type"] == "task_completed"

    events, done = _collect_task_events(_StubQueue(_terminal_task("run00001", "running")), "run00001", 50, set())
    assert done is False
    assert events[0]["type"] == "task_progress"


def test_collect_task_events_dedup_terminal():
    """终态去重保持: 同一终态任务第二轮调用不再产生事件"""
    from backend.api.tasks import _collect_task_events

    terminal_sent: set[str] = set()
    stub = _StubQueue(_terminal_task("term0002", "cancelled"))

    events, done = _collect_task_events(stub, "term0002", 50, terminal_sent)
    assert len(events) == 1
    assert done is True

    events2, done2 = _collect_task_events(stub, "term0002", 50, terminal_sent)
    assert events2 == []
    assert done2 is False


def test_cancel_task_unknown_does_not_leak_marker():
    """对不存在任务取消返回 False 且不污染 _cancelled"""
    from backend.task_queue import TaskQueue

    original = TaskQueue._instance
    TaskQueue._instance = None
    try:
        q = TaskQueue()
        assert q.cancel_task("missing-0001") is False
        with q._state_lock:
            assert q._cancelled == set()
    finally:
        TaskQueue._instance = original


@pytest.mark.parametrize("status", ["success", "failed", "cancelled"])
def test_cancel_terminal_task_does_not_leak_marker(status):
    """对终态任务取消返回 False 且不污染 _cancelled"""
    from backend.task_queue import TaskQueue

    original = TaskQueue._instance
    TaskQueue._instance = None
    try:
        q = TaskQueue()
        with patch("backend.task_queue.TaskQueue.get_task", return_value=_terminal_task("done0001", status)):
            assert q.cancel_task("done0001") is False
        with q._state_lock:
            assert q._cancelled == set()
    finally:
        TaskQueue._instance = original


def test_cancel_runnable_task_still_marks_marker():
    """可取消任务仍被标记进 _cancelled(标记时机后移不破坏取消语义)"""
    from backend.task_queue import TaskQueue

    original = TaskQueue._instance
    TaskQueue._instance = None
    try:
        q = TaskQueue()
        with patch("backend.task_queue.TaskQueue.get_task", return_value=_terminal_task("pend0001", "pending")):
            assert q.cancel_task("pend0001") is True
        with q._state_lock:
            assert "pend0001" in q._cancelled
            q._cancelled.discard("pend0001")
    finally:
        TaskQueue._instance = original
