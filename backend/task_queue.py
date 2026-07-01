"""任务队列 — 后台任务执行与管理"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

from backend.storage.db import Database

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id TEXT PRIMARY KEY,
    conversation_id TEXT DEFAULT '',
    task_type TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    input_json TEXT DEFAULT '{}',
    output_json TEXT DEFAULT '{}',
    error TEXT DEFAULT '',
    started_at REAL,
    completed_at REAL,
    created_at REAL NOT NULL
)
"""


def _ensure_table(conn) -> None:
    conn.execute(_TABLE_SQL)
    conn.commit()


class TaskQueue:
    """后台任务队列（单例）"""

    _instance: Optional["TaskQueue"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "TaskQueue":
        with cls._lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
        return cls._instance

    def __init__(self) -> None:
        with type(self)._lock:
            if self._initialized:
                return
            self._initialized = True
        self._executor = ThreadPoolExecutor(max_workers=3)
        self._futures: dict[str, Future] = {}
        self._cancelled: set[str] = set()
        self._state_lock = threading.Lock()  # Protects _futures and _cancelled
        db = Database()
        with db.transaction() as conn:
            _ensure_table(conn)

    def submit(
        self,
        task_type: str,
        func: Callable,
        *args,
        conversation_id: str = "",
        input_data: dict | None = None,
        **kwargs,
    ) -> str:
        """提交任务到后台执行，返回 task_id"""
        task_id = str(uuid.uuid4())[:8]
        now = time.time()
        db = Database()
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO analysis_tasks (id, conversation_id, task_type, status, input_json, created_at) "
                "VALUES (?, ?, ?, 'pending', ?, ?)",
                (
                    task_id,
                    conversation_id,
                    task_type,
                    json.dumps(input_data or {}, ensure_ascii=False),
                    now,
                ),
            )
            conn.commit()

        future = self._executor.submit(self._run_task, task_id, func, args, kwargs)
        with self._state_lock:
            self._futures[task_id] = future
        return task_id

    def _run_task(
        self, task_id: str, func: Callable, args: tuple, kwargs: dict
    ) -> None:
        """执行任务并更新状态"""
        db = Database()
        try:
            with self._state_lock:
                cancelled = task_id in self._cancelled

            if cancelled:
                with db.transaction() as conn:
                    conn.execute(
                        "UPDATE analysis_tasks SET status='cancelled', completed_at=? WHERE id=?",
                        (time.time(), task_id),
                    )
                    conn.commit()
                return

            with db.transaction() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status='running', started_at=? WHERE id=?",
                    (time.time(), task_id),
                )
                conn.commit()

            result = func(*args, **kwargs)

            with self._state_lock:
                cancelled = task_id in self._cancelled

            with db.transaction() as conn:
                if cancelled:
                    conn.execute(
                        "UPDATE analysis_tasks SET status='cancelled', completed_at=? WHERE id=?",
                        (time.time(), task_id),
                    )
                else:
                    conn.execute(
                        "UPDATE analysis_tasks SET status='success', output_json=?, completed_at=? WHERE id=?",
                        (
                            json.dumps(result, ensure_ascii=False) if result else "{}",
                            time.time(),
                            task_id,
                        ),
                    )
                conn.commit()
        except Exception as e:
            logger.exception("任务 %s 执行失败: %s", task_id, e)
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status='failed', error=?, completed_at=? WHERE id=?",
                    (str(e), time.time(), task_id),
                )
                conn.commit()
        finally:
            with self._state_lock:
                self._futures.pop(task_id, None)
                self._cancelled.discard(task_id)

    def get_task(self, task_id: str) -> Optional[dict[str, Any]]:
        """查询任务状态"""
        db = Database()
        with db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM analysis_tasks WHERE id=?", (task_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"] or "",
            "task_type": row["task_type"],
            "status": row["status"],
            "input_json": row["input_json"] or "{}",
            "output_json": row["output_json"] or "{}",
            "error": row["error"] or "",
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "created_at": row["created_at"],
        }

    def list_tasks(
        self, status: Optional[str] = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """列出任务"""
        db = Database()
        with db.transaction() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM analysis_tasks WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM analysis_tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            {
                "id": r["id"],
                "conversation_id": r["conversation_id"] or "",
                "task_type": r["task_type"],
                "status": r["status"],
                "error": r["error"] or "",
                "started_at": r["started_at"],
                "completed_at": r["completed_at"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        with self._state_lock:
            self._cancelled.add(task_id)
        task = self.get_task(task_id)
        if not task:
            return False
        if task["status"] in ("success", "failed", "cancelled"):
            return False
        # 如果任务还在 pending，直接标记取消
        if task["status"] == "pending":
            db = Database()
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE analysis_tasks SET status='cancelled', completed_at=? WHERE id=?",
                    (time.time(), task_id),
                )
                conn.commit()
        # 如果正在运行，future 会在检查点取消
        return True

    def shutdown(self) -> None:
        """优雅关闭线程池，释放资源"""
        self._executor.shutdown(wait=False)
