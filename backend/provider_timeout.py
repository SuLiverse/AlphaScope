"""Bounded execution helpers for blocking provider calls."""

from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

_T = TypeVar("_T")


def _max_inflight_calls() -> int:
    try:
        return max(1, int(os.environ.get("ALPHASCOPE_PROVIDER_MAX_INFLIGHT", "20")))
    except ValueError:
        return 20


_INFLIGHT = threading.BoundedSemaphore(_max_inflight_calls())


def call_with_timeout(
    fn: Callable[[], _T],
    timeout: float,
    *,
    name: str = "provider-call",
) -> _T:
    """Run a blocking provider call without letting a request hang indefinitely."""

    deadline = time.monotonic() + max(0.0, timeout)
    if not _INFLIGHT.acquire(timeout=max(0.0, timeout)):
        raise TimeoutError(f"{name} capacity exhausted")

    result_queue: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            try:
                result_queue.put((True, fn()), block=False)
            except Exception as exc:
                try:
                    result_queue.put((False, exc), block=False)
                except queue.Full:
                    pass
        finally:
            _INFLIGHT.release()

    thread = threading.Thread(target=worker, name=name, daemon=True)
    try:
        thread.start()
    except Exception:
        _INFLIGHT.release()
        raise
    try:
        ok, payload = result_queue.get(timeout=max(0.0, deadline - time.monotonic()))
    except queue.Empty as exc:
        raise TimeoutError(f"{name} timed out") from exc
    if ok:
        return payload
    raise payload
