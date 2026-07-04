"""Lightweight tracing / observability for pipeline and agent calls.

Provides a simple span-based tracing system that logs timing and metadata
for key operations. Can be optionally upgraded to OpenTelemetry later.

Usage:
    from backend.utils.tracer import Tracer, traced

    tracer = Tracer("pipeline")

    # Context manager
    with traced("ingest_news", market="CN", symbol="600519") as span:
        items = do_work()
        span.set("items_count", len(items))

    # Decorator
    @traced("fetch_data")
    def fetch_data(source: str):
        ...

    # Query traces
    traces = tracer.get_traces(limit=10)
"""

from __future__ import annotations

import logging
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Callable
from functools import wraps

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))


@dataclass
class Span:
    """A single trace span recording timing and metadata."""

    name: str
    operation: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "ok"  # ok / error / skipped
    error: str = ""
    attributes: Dict[str, Any] = field(default_factory=dict)
    parent: Optional[str] = None
    trace_id: str = ""
    span_id: str = ""

    def set(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def finish(self, status: str = "ok", error: str = "") -> None:
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "operation": self.operation,
            "duration_ms": round(self.duration_ms, 1),
            "status": self.status,
            "error": self.error[:200] if self.error else "",
            "attributes": self.attributes,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "timestamp": datetime.fromtimestamp(self.start_time, tz=_CST).isoformat(),
        }


class Tracer:
    """Simple in-memory trace collector.

    Stores the last N spans in a ring buffer. Thread-safe.
    """

    def __init__(self, name: str = "default", max_spans: int = 500):
        self.name = name
        self.max_spans = max_spans
        self._spans: List[Span] = []
        self._lock = threading.Lock()
        self._trace_counter = 0

    def start_span(self, operation: str, parent: Optional[str] = None, **attrs) -> Span:
        with self._lock:
            self._trace_counter += 1
            counter = self._trace_counter
        span = Span(
            name=f"{self.name}.{operation}",
            operation=operation,
            start_time=time.time(),
            trace_id=f"{self.name}-{counter}",
            span_id=f"s{counter}",
            parent=parent,
            attributes=attrs,
        )
        return span

    def end_span(self, span: Span) -> None:
        with self._lock:
            self._spans.append(span)
            if len(self._spans) > self.max_spans:
                self._spans = self._spans[-self.max_spans :]
        if span.status == "error":
            logger.warning(
                "[Trace] %s failed (%.0fms): %s",
                span.name,
                span.duration_ms,
                span.error[:100],
            )
        else:
            logger.debug("[Trace] %s ok (%.0fms)", span.name, span.duration_ms)

    def get_traces(self, limit: int = 50, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            spans = list(self._spans)
        if status:
            spans = [s for s in spans if s.status == status]
        return [s.to_dict() for s in spans[-limit:]]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            spans = list(self._spans)
        if not spans:
            return {"total": 0}
        durations = [s.duration_ms for s in spans]
        errors = sum(1 for s in spans if s.status == "error")
        return {
            "total": len(spans),
            "errors": errors,
            "error_rate": round(errors / len(spans) * 100, 1),
            "avg_ms": round(sum(durations) / len(durations), 1),
            "max_ms": round(max(durations), 1),
            "min_ms": round(min(durations), 1),
        }

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()


# ---- Module-level singletons ----
_tracers: Dict[str, Tracer] = {}
_tracers_lock = threading.Lock()


def get_tracer(name: str = "default") -> Tracer:
    with _tracers_lock:
        if name not in _tracers:
            _tracers[name] = Tracer(name)
        return _tracers[name]


@contextmanager
def traced(operation: str, tracer_name: str = "default", **attrs):
    """Context manager that creates a trace span.

    Usage:
        with traced("ingest_news", market="CN") as span:
            result = do_work()
            span.set("count", len(result))
    """
    tracer = get_tracer(tracer_name)
    span = tracer.start_span(operation, **attrs)
    try:
        yield span
        span.finish("ok")
    except Exception as e:
        span.finish("error", str(e))
        raise
    finally:
        tracer.end_span(span)


def traced_func(operation: str = "", tracer_name: str = "default") -> Callable:
    """Decorator that traces function calls.

    Usage:
        @traced_func("fetch_data")
        def fetch_data(source: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        op_name = operation or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            with traced(op_name, tracer_name, **{k: str(v)[:50] for k, v in kwargs.items()}):
                return func(*args, **kwargs)

        return wrapper

    return decorator


def get_all_stats() -> Dict[str, Dict[str, Any]]:
    """Get stats from all registered tracers."""
    with _tracers_lock:
        return {name: t.get_stats() for name, t in _tracers.items()}
