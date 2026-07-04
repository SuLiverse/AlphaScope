"""工作流编排与可观测性测试 / Phase D #3/#4.

覆盖:
1. 能力探测 (始终跑): available_tools / is_available / describe
2. 纯函数 (始终跑): build_trace_context
3. OpenTelemetry 路径 (skipif): init_tracing / trace_span
4. Prefect 路径 (skipif): as_prefect_flow / as_prefect_task
5. 降级路径 (强制不可用): trace_span 是 no-op, 装饰器原样返回

合规: 测试只校验追踪/调度逻辑, 不涉及买卖指令。
"""

from __future__ import annotations

import pytest

from backend import workflow_orchestration as wo


# ============================================================
# 1. 能力探测 (始终跑)
# ============================================================


def test_available_tools_returns_dict():
    tools = wo.available_tools()
    assert set(tools.keys()) == {"prefect", "dagster", "opentelemetry"}


def test_is_available_unknown_returns_false():
    assert wo.is_available("totally_unknown") is False


def test_describe_structure():
    info = wo.describe()
    assert "available_tools" in info
    assert "ready_count" in info
    assert isinstance(info["ready"], list)


# ============================================================
# 2. 纯函数 (始终跑)
# ============================================================


def test_build_trace_context_basic():
    ctx = wo.build_trace_context("job-123", user_prompt="分析茅台", data_sources=["akshare", "openbb"])
    assert ctx["job_id"] == "job-123"
    assert ctx["data_sources"] == "akshare,openbb"
    assert ctx["service"] == "alphascope"


def test_build_trace_context_truncates_long_prompt():
    long_prompt = "x" * 500
    ctx = wo.build_trace_context("j", user_prompt=long_prompt)
    assert len(ctx["user_prompt"]) <= 200


def test_build_trace_context_empty_safe():
    ctx = wo.build_trace_context("j")
    assert ctx["data_sources"] == ""


# ============================================================
# 3. OpenTelemetry 路径 (skipif)
# ============================================================

otel_required = pytest.mark.skipif(not wo.is_available("opentelemetry"), reason="opentelemetry 未装")


@otel_required
def test_init_tracing_idempotent():
    """init_tracing 应可重复调用 (第二次返回 already_initialized)。"""
    r1 = wo.init_tracing("test_service")
    r2 = wo.init_tracing("test_service")
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert "already" in r2["error"]


@otel_required
def test_trace_span_creates_span():
    """trace_span 上下文管理器应在 otel 下创建真实 span。"""
    with wo.trace_span("test_op", {"key": "value"}):
        # 进入 span 不抛即通过 (otel 装了会创建真实 span)
        pass


# ============================================================
# 4. Prefect 路径 (skipif)
# ============================================================

prefect_required = pytest.mark.skipif(not wo.is_available("prefect"), reason="prefect 未装")


@prefect_required
def test_as_prefect_flow_decorates():
    """as_prefect_flow 应把函数变成 prefect flow。"""

    @wo.as_prefect_flow
    def my_flow(x: int) -> int:
        return x * 2

    # prefect flow 仍可同步调用 (同步 flow)
    result = my_flow(5)
    assert result == 10


@prefect_required
def test_as_prefect_task_decorates():
    @wo.as_prefect_task
    def my_task(x: int) -> int:
        return x + 1

    assert callable(my_task)


# ============================================================
# 5. 降级路径 (强制全部不可用)
# ============================================================


@pytest.fixture
def all_degraded(monkeypatch):
    for attr in ("_PREFECT", "_DAGSTER", "_OTEL"):
        monkeypatch.setattr(wo, attr, False)


def test_degraded_trace_span_is_noop(all_degraded):
    """未装 otel 时 trace_span 退化为 no-op (不抛, 不创建 span)。"""
    with wo.trace_span("anything"):
        # no-op 上下文, 不抛即通过
        pass


def test_degraded_as_prefect_flow_returns_original(all_degraded):
    """未装 prefect 时 as_prefect_flow 原样返回函数。"""

    @wo.as_prefect_flow
    def my_fn(x):
        return x + 1

    assert my_fn(5) == 6  # 普通函数直接调用


def test_degraded_init_tracing_returns_error(all_degraded):
    r = wo.init_tracing()
    assert r["ok"] is False
    assert "opentelemetry" in r["error"]


def test_degraded_available_tools_all_false(all_degraded):
    tools = wo.available_tools()
    assert all(v is False for v in tools.values())
