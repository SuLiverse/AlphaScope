"""并发限制 — 全局信号量，限制同时运行的任务数"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


class ConcurrencyLimiter:
    """线程安全的并发限制器。

    用法：
        limiter = ConcurrencyLimiter(max_concurrent=10)
        with limiter.acquire():
            do_work()
    """

    def __init__(self, max_concurrent: int = 10):
        self._semaphore = threading.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._active = 0
        self._total_acquired = 0
        self._total_rejected = 0
        self._lock = threading.Lock()

    @contextmanager
    def acquire(self, timeout: float = 60.0):
        """获取并发槽位。超时抛 TimeoutError。"""
        acquired = self._semaphore.acquire(timeout=timeout)
        if not acquired:
            with self._lock:
                self._total_rejected += 1
            raise TimeoutError(f"并发限制: 等待 {timeout}s 后仍未获取到槽位（当前最大并发: {self._max_concurrent}）")
        with self._lock:
            self._active += 1
            self._total_acquired += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1
            self._semaphore.release()

    def stats(self) -> dict[str, Any]:
        """当前状态。"""
        with self._lock:
            return {
                "max_concurrent": self._max_concurrent,
                "active": self._active,
                "total_acquired": self._total_acquired,
                "total_rejected": self._total_rejected,
            }


# 全局实例
_llm_limiter = ConcurrencyLimiter(max_concurrent=10)
_data_limiter = ConcurrencyLimiter(max_concurrent=20)


def get_llm_limiter() -> ConcurrencyLimiter:
    """获取 LLM 调用并发限制器（默认最大 10 并发）。"""
    return _llm_limiter


def get_data_limiter() -> ConcurrencyLimiter:
    """获取数据获取并发限制器（默认最大 20 并发）。"""
    return _data_limiter
