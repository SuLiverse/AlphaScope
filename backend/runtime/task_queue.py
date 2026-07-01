"""
Task Queue: 异步任务队列。

职责：
- 异步执行长时间运行的任务（Agent 分析、数据采集）
- 任务状态跟踪
- 结果回调

当前为内存实现，生产环境可替换为 Celery/RQ。
"""

import time
import uuid
import logging
import threading
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, Future

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """任务定义"""

    task_id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = 0
    started_at: float = 0
    completed_at: float = 0
    progress: float = 0.0  # 0-100
    callback: Optional[str] = ""  # callback URL or function name


class TaskQueue:
    """异步任务队列"""

    def __init__(self, max_workers: int = 4):
        self._tasks: Dict[str, Task] = {}
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        name: str,
        func: Callable,
        input_data: Optional[Dict] = None,
        callback: str = "",
    ) -> str:
        """提交异步任务"""
        task_id = uuid.uuid4().hex[:12]
        task = Task(
            task_id=task_id,
            name=name,
            input_data=input_data or {},
            created_at=time.time(),
            callback=callback,
        )

        with self._lock:
            self._tasks[task_id] = task

        # 提交到线程池
        future = self._executor.submit(self._run_task, task_id, func)
        with self._lock:
            self._futures[task_id] = future

        return task_id

    def _run_task(self, task_id: str, func: Callable):
        """执行任务"""
        with self._lock:
            task = self._tasks.get(task_id)
        if not task:
            return

        with self._lock:
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

        try:
            result = func(task.input_data, task_id=task_id)
            with self._lock:
                task.output_data = (
                    result if isinstance(result, dict) else {"result": result}
                )
                task.status = TaskStatus.COMPLETED
        except Exception as e:
            with self._lock:
                task.error = str(e)[:500]
                task.status = TaskStatus.FAILED
            logger.error(f"任务 {task_id} ({task.name}) 失败: {e}")
        finally:
            with self._lock:
                task.completed_at = time.time()

    def get_task(self, task_id: str) -> Optional[Task]:
        """获取任务状态"""
        with self._lock:
            return self._tasks.get(task_id)

    def get_task_dict(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取任务状态（字典格式）"""
        with self._lock:
            task = self._tasks.get(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "name": task.name,
            "status": task.status.value,
            "progress": task.progress,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "completed_at": task.completed_at,
            "duration_ms": round((task.completed_at - task.started_at) * 1000, 1)
            if task.completed_at
            else 0,
            "error": task.error,
        }

    def list_tasks(
        self, status: Optional[TaskStatus] = None, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """列出任务"""
        with self._lock:
            tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        tasks.sort(key=lambda t: t.created_at, reverse=True)
        return [self.get_task_dict(t.task_id) for t in tasks[:limit]]

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.CANCELLED
                future = self._futures.get(task_id)
                if future:
                    future.cancel()
                return True
        return False

    def update_progress(self, task_id: str, progress: float):
        """更新任务进度"""
        with self._lock:
            task = self._tasks.get(task_id)
            if task:
                task.progress = min(100, max(0, progress))

    def get_stats(self) -> Dict[str, Any]:
        """获取队列统计"""
        with self._lock:
            statuses = {}
            for task in self._tasks.values():
                s = task.status.value
                statuses[s] = statuses.get(s, 0) + 1
            total = len(self._tasks)
        return {
            "total": total,
            "by_status": statuses,
            "active_workers": self._max_workers,
        }

    def shutdown(self) -> None:
        """优雅关闭线程池，释放资源"""
        self._executor.shutdown(wait=False)


# 单例
_queue: Optional[TaskQueue] = None


def get_task_queue() -> TaskQueue:
    """获取全局任务队列"""
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue
