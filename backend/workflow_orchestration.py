"""工作流编排与可观测性 / Workflow Orchestration & Observability (Phase D #3/#4).

把 ``Prefect`` / ``Dagster`` / ``OpenTelemetry`` 接入 AlphaScope, 给多数据源/多 Agent/
多回测任务的工作流加上**调度、重试、缓存、追踪**能力 (对应战略规划 Phase D 第 3/4 项
「Prefect/Dagster 工作流」「OpenTelemetry Trace」与 §8「工作流编排与可观测性」)。

设计要点 (延续项目「确定性 · 失败安全」基线):
- **可选依赖 + 优雅降级**: 每个库独立 import-guard; 缺装不影响其余功能, 也不影响
  项目既有的自研 task_queue (本模块是增强, 非替代)。
- **轻量包装**: 不重造工作流引擎, 而是提供面向 AlphaScope 场景的便捷入口 (把回测/
  研究 pipeline 用 Prefect 装饰、把关键路径用 OpenTelemetry trace、把数据资产用
  Dagster 血缘管理)。
- **纯函数**: ``available_tools`` / ``describe`` / ``build_trace_context`` 不依赖任何
  工作流库, 始终可测。
- **合规**: 追踪/调度仅描述任务执行结构, 不涉及买卖指令。

A​PI 已对照真实源码核对 (非臆测):
- prefect 3.x: ``from prefect import flow, task`` + 装饰器
- opentelemetry: ``trace.set_tracer_provider + tracer.start_as_current_span``
- dagster: ``@asset @op @job`` (本模块仅探测可用性, 不强制依赖)
"""

from __future__ import annotations

from typing import Any, Callable

# ----- 可选依赖: 每个库独立 import-guard -----
_PREFECT = False
_DAGSTER = False
_OTEL = False

try:
    from prefect import flow as _prefect_flow  # type: ignore[import-untyped]
    from prefect import task as _prefect_task  # type: ignore[import-untyped]

    import prefect as _prefect_mod  # type: ignore[import-untyped]

    _PREFECT = True
except Exception:
    _prefect_flow = None  # type: ignore[assignment]
    _prefect_task = None  # type: ignore[assignment]
    _prefect_mod = None  # type: ignore[assignment]

try:
    from opentelemetry import trace as _otel_trace  # type: ignore[import-untyped]
    from opentelemetry.sdk.trace import TracerProvider as _OtelProvider  # type: ignore[import-untyped]

    _OTEL = True
except Exception:
    _otel_trace = None  # type: ignore[assignment]
    _OtelProvider = None  # type: ignore[assignment]

try:
    import dagster as _dagster_mod  # type: ignore[import-untyped]

    _DAGSTER = True
except Exception:
    _dagster_mod = None  # type: ignore[assignment]


_otel_initialized = False  # 进程级单例标志


# ============================================================
# 能力探测 (纯函数)
# ============================================================


def available_tools() -> dict[str, bool]:
    """当前已装的工作流/可观测性库清单。"""
    return {"prefect": _PREFECT, "dagster": _DAGSTER, "opentelemetry": _OTEL}


def is_available(tool: str | None = None) -> bool:
    """某库是否就绪; tool=None 时表示「至少一个就绪」。"""
    tools = available_tools()
    if tool is None:
        return any(tools.values())
    return tools.get(tool, False)


def describe() -> dict[str, Any]:
    """能力概览 (供 UI/调试)。"""
    tools = available_tools()
    ready = [k for k, v in tools.items() if v]
    return {
        "available_tools": tools,
        "ready_count": len(ready),
        "ready": ready,
        "note": (
            f"就绪工作流/可观测库: {', '.join(ready) if ready else '(无)'}; "
            "本模块是既有自研 task_queue 的增强, 缺装不影响其余功能。"
        ),
    }


# ============================================================
# OpenTelemetry: 追踪 (Phase D #4)
# ============================================================


def init_tracing(service_name: str = "alphascope") -> dict[str, Any]:
    """初始化 OpenTelemetry tracer (进程级单例, 只初始化一次)。

    返回 {ok, service_name, exporter, error}。失败安全: 未装/已初始化/异常 → 不抛。
    默认用 ConsoleSpanExporter (开发期); 生产应在调用方配置 OTLP exporter 指向
    Jaeger/Tempo/Phoenix 等 backend。
    """
    global _otel_initialized
    base: dict[str, Any] = {
        "ok": False,
        "service_name": service_name,
        "exporter": "console",
        "error": "",
    }
    if not _OTEL:
        base["error"] = "opentelemetry 未安装。pip install opentelemetry-sdk"
        return base
    if _otel_initialized:
        base["ok"] = True
        base["error"] = "already_initialized"
        return base
    try:
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            BatchSpanProcessor,
        )

        provider = _OtelProvider()  # type: ignore[misc]
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        _otel_trace.set_tracer_provider(provider)  # type: ignore[union-attr]
        _otel_initialized = True
        base["ok"] = True
    except Exception as e:
        base["error"] = f"otel 初始化失败: {str(e)[:120]}"
    return base


def get_tracer(name: str = "alphascope"):
    """获取 OpenTelemetry tracer; 未装时返回 None。"""
    if not _OTEL:
        return None
    try:
        return _otel_trace.get_tracer(name)  # type: ignore[union-attr]
    except Exception:
        return None


def trace_span(name: str, attributes: dict[str, Any] | None = None):
    """上下文管理器: 在 OpenTelemetry span 下执行代码块。

    用法:
        with trace_span("run_backtest", {"strategy": "ma_cross"}) as span:
            ...

    未装 opentelemetry 时退化为 no-op (用 contextlib.nullcontext), 不影响代码。
    """
    if not _OTEL:
        from contextlib import nullcontext

        return nullcontext()
    tracer = get_tracer()
    if tracer is None:
        from contextlib import nullcontext

        return nullcontext()
    cm = tracer.start_as_current_span(name)

    # 包装一下: 进入时设 attributes
    class _Wrapped:
        def __init__(self, ctx):
            self._ctx = ctx
            self.span = None

        def __enter__(self):
            self.span = self._ctx.__enter__()
            if self.span is not None and attributes:
                for k, v in attributes.items():
                    try:
                        self.span.set_attribute(k, v)
                    except Exception:
                        pass
            return self.span

        def __exit__(self, *args):
            return self._ctx.__exit__(*args)

    return _Wrapped(cm)


def build_trace_context(job_id: str, user_prompt: str = "", data_sources: list[str] | None = None) -> dict[str, Any]:
    """构造标准 trace 属性 (纯函数, 不依赖 otel)。

    用于给回测/研究任务的 span 提供统一属性集 (job_id/user_prompt/data_sources)。
    """
    return {
        "job_id": str(job_id),
        "user_prompt": str(user_prompt)[:200],  # 限长防 span 膨胀
        "data_sources": ",".join(data_sources) if data_sources else "",
        "service": "alphascope",
    }


# ============================================================
# Prefect: 工作流装饰器 (Phase D #3)
# ============================================================


def as_prefect_flow(fn: Callable | None = None, **flow_kwargs: Any):
    """把一个普通函数装饰成 Prefect flow; prefect 不可用时原样返回 (no-op)。

    用法:
        @as_prefect_flow
        def my_pipeline(...): ...

    失败安全: 未装 prefect 时函数不变 (仍可直接调用), 只是没有调度/重试能力。
    """
    if not _PREFECT:
        if fn is None:
            return lambda f: f  # 装饰器工厂模式
        return fn
    if fn is None:
        return _prefect_flow(**flow_kwargs)  # type: ignore[union-attr]
    return _prefect_flow(fn, **flow_kwargs)  # type: ignore[union-attr]


def as_prefect_task(fn: Callable | None = None, **task_kwargs: Any):
    """把一个普通函数装饰成 Prefect task; prefect 不可用时原样返回。"""
    if not _PREFECT:
        if fn is None:
            return lambda f: f
        return fn
    if fn is None:
        return _prefect_task(**task_kwargs)  # type: ignore[union-attr]
    return _prefect_task(fn, **task_kwargs)  # type: ignore[union-attr]
