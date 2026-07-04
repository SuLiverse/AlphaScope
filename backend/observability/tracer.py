"""
Tracer: 可观测性追踪系统。

职责：
- LLM 调用追踪（延迟、token、模型、结果）
- Agent 执行追踪
- 工具调用追踪
- 审计日志
- Langfuse/OpenTelemetry 兼容接口

架构文档要求：可观测从第一版就做，否则多 Agent 系统很难调试。
"""

import time
import json
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from contextlib import contextmanager

try:
    from project_paths import CACHE_DIR
except ImportError:
    from backend.project_paths import CACHE_DIR

TRACE_LOG_PATH = CACHE_DIR / "traces.jsonl"

logger = logging.getLogger(__name__)


@dataclass
class TraceSpan:
    """追踪跨度"""

    span_id: str
    trace_id: str
    parent_id: str = ""
    name: str = ""
    span_type: str = ""  # llm_call, agent_run, tool_call, pipeline
    start_time: float = 0
    end_time: float = 0
    duration_ms: float = 0
    input_data: Dict[str, Any] = field(default_factory=dict)
    output_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    status: str = "ok"  # ok, error
    error: str = ""


@dataclass
class Trace:
    """完整追踪"""

    trace_id: str
    name: str = ""
    start_time: float = 0
    end_time: float = 0
    spans: List[TraceSpan] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class Tracer:
    """追踪器"""

    def __init__(self):
        self._traces: List[Trace] = []
        self._current_trace: Optional[Trace] = None
        self._log_path = TRACE_LOG_PATH

    def start_trace(self, name: str, metadata: Optional[Dict] = None) -> str:
        """开始一个新追踪"""
        import uuid

        trace_id = uuid.uuid4().hex[:12]
        trace = Trace(
            trace_id=trace_id,
            name=name,
            start_time=time.time(),
            metadata=metadata or {},
        )
        self._traces.append(trace)
        self._current_trace = trace
        return trace_id

    def end_trace(self, trace_id: str):
        """结束追踪"""
        for t in self._traces:
            if t.trace_id == trace_id:
                t.end_time = time.time()
                self._flush_trace(t)
                break

    @contextmanager
    def trace(self, name: str, metadata: Optional[Dict] = None):
        """上下文管理器：自动开始/结束追踪"""
        trace_id = self.start_trace(name, metadata)
        try:
            yield trace_id
        finally:
            self.end_trace(trace_id)

    def add_span(
        self,
        trace_id: str,
        name: str,
        span_type: str,
        parent_id: str = "",
        input_data: Optional[Dict] = None,
        output_data: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
        status: str = "ok",
        error: str = "",
        duration_ms: float = 0,
    ) -> str:
        """添加一个跨度"""
        import uuid

        span_id = uuid.uuid4().hex[:8]

        span = TraceSpan(
            span_id=span_id,
            trace_id=trace_id,
            parent_id=parent_id,
            name=name,
            span_type=span_type,
            start_time=time.time(),
            end_time=time.time() + duration_ms / 1000,
            duration_ms=duration_ms,
            input_data=input_data or {},
            output_data=output_data or {},
            metadata=metadata or {},
            status=status,
            error=error,
        )

        for t in self._traces:
            if t.trace_id == trace_id:
                t.spans.append(span)
                break

        return span_id

    @contextmanager
    def span(
        self,
        trace_id: str,
        name: str,
        span_type: str,
        parent_id: str = "",
        metadata: Optional[Dict] = None,
    ):
        """上下文管理器：自动计时的跨度"""
        t0 = time.time()
        span_id = self.add_span(trace_id, name, span_type, parent_id=parent_id, metadata=metadata)
        try:
            yield span_id
            duration = (time.time() - t0) * 1000
            self._update_span_duration(trace_id, span_id, duration)
        except Exception as e:
            duration = (time.time() - t0) * 1000
            self._update_span_error(trace_id, span_id, str(e), duration)
            raise

    def _update_span_duration(self, trace_id: str, span_id: str, duration_ms: float):
        """更新跨度持续时间"""
        for t in self._traces:
            if t.trace_id == trace_id:
                for s in t.spans:
                    if s.span_id == span_id:
                        s.duration_ms = duration_ms
                        s.end_time = s.start_time + duration_ms / 1000
                        break
                break

    def _update_span_error(self, trace_id: str, span_id: str, error: str, duration_ms: float):
        """更新跨度错误信息"""
        for t in self._traces:
            if t.trace_id == trace_id:
                for s in t.spans:
                    if s.span_id == span_id:
                        s.status = "error"
                        s.error = error
                        s.duration_ms = duration_ms
                        s.end_time = s.start_time + duration_ms / 1000
                        break
                break

    def _flush_trace(self, trace: Trace):
        """将追踪写入日志文件"""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            record = {
                "trace_id": trace.trace_id,
                "name": trace.name,
                "start_time": trace.start_time,
                "end_time": trace.end_time,
                "duration_ms": round((trace.end_time - trace.start_time) * 1000, 1),
                "span_count": len(trace.spans),
                "spans": [
                    {
                        "span_id": s.span_id,
                        "name": s.name,
                        "type": s.span_type,
                        "duration_ms": s.duration_ms,
                        "status": s.status,
                        "error": s.error,
                    }
                    for s in trace.spans
                ],
                "metadata": trace.metadata,
            }
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass

    def get_recent_traces(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的追踪"""
        if not self._log_path.exists():
            return []
        try:
            lines = self._log_path.read_text(encoding="utf-8").strip().splitlines()
            records = [json.loads(line) for line in lines[-limit:] if line.strip()]
            return records
        except Exception:
            return []

    def get_stats(self) -> Dict[str, Any]:
        """获取追踪统计"""
        total_spans = sum(len(t.spans) for t in self._traces)
        error_spans = sum(1 for t in self._traces for s in t.spans if s.status == "error")
        avg_duration = 0
        if self._traces:
            durations = [(t.end_time - t.start_time) * 1000 for t in self._traces if t.end_time > 0]
            avg_duration = round(sum(durations) / max(len(durations), 1), 1)

        return {
            "total_traces": len(self._traces),
            "total_spans": total_spans,
            "error_spans": error_spans,
            "avg_duration_ms": avg_duration,
        }


# 单例
_tracer: Optional[Tracer] = None


def get_tracer() -> Tracer:
    """获取全局追踪器"""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer
