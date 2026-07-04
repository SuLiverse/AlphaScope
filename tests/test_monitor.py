"""系统监控中心聚合器测试 (v1.9.10)。

覆盖纯函数状态分级、快照结构、now 注入、以及失败安全(单组件采集失败 →
该组件降级为 unknown、整体不崩溃)。全部离线、确定性。
"""

from __future__ import annotations

from backend.observability import monitor
from backend.observability.monitor import (
    STATUS_GOOD,
    STATUS_POOR,
    STATUS_UNKNOWN,
    STATUS_WARN,
    build_system_snapshot,
    compute_overall_status,
    grade_from_quality,
    tool_call_status,
    trace_status,
)

_VALID = {STATUS_GOOD, STATUS_WARN, STATUS_POOR, STATUS_UNKNOWN}
_EXPECTED_KEYS = [
    "data_sources",
    "quant_engine",
    "experiments",
    "llm_cost",
    "tool_calls",
    "traces",
]


def test_grade_from_quality_thresholds():
    assert grade_from_quality(95) == STATUS_GOOD
    assert grade_from_quality(80) == STATUS_GOOD  # 边界含
    assert grade_from_quality(79.9) == STATUS_WARN
    assert grade_from_quality(50) == STATUS_WARN  # 边界含
    assert grade_from_quality(49.9) == STATUS_POOR
    assert grade_from_quality(0) == STATUS_POOR


def test_tool_call_status():
    assert tool_call_status(0, 0) == STATUS_GOOD  # 无调用视为正常
    assert tool_call_status(100, 0) == STATUS_GOOD
    assert tool_call_status(100, 9) == STATUS_GOOD
    assert tool_call_status(100, 10) == STATUS_WARN  # 10% 起黄
    assert tool_call_status(100, 29) == STATUS_WARN
    assert tool_call_status(100, 30) == STATUS_POOR  # 30% 起红


def test_trace_status():
    assert trace_status(0, 0) == STATUS_GOOD
    assert trace_status(100, 9) == STATUS_GOOD
    assert trace_status(100, 10) == STATUS_WARN  # 10% 起黄
    assert trace_status(100, 24) == STATUS_WARN
    assert trace_status(100, 25) == STATUS_POOR  # 25% 起红


def test_compute_overall_status():
    g = {"status": STATUS_GOOD}
    w = {"status": STATUS_WARN}
    p = {"status": STATUS_POOR}
    u = {"status": STATUS_UNKNOWN}
    assert compute_overall_status([g, g]) == STATUS_GOOD
    assert compute_overall_status([g, w]) == STATUS_WARN
    assert compute_overall_status([w, p]) == STATUS_POOR
    assert compute_overall_status([g, u]) == STATUS_GOOD  # unknown 不拉低总状态
    assert compute_overall_status([u, u]) == STATUS_UNKNOWN  # 全未知 → 未知
    assert compute_overall_status([]) == STATUS_UNKNOWN


def test_snapshot_shape_and_now_injection():
    snap = build_system_snapshot(now=1_700_000_000.0)
    assert snap["generated_at"] == 1_700_000_000.0
    assert snap["overall"] in _VALID
    assert snap["overall_label"]
    assert snap["disclaimer"]
    comps = snap["components"]
    assert isinstance(comps, list) and len(comps) == 6
    assert [c["key"] for c in comps] == _EXPECTED_KEYS
    for c in comps:
        assert set(c) >= {"key", "label", "status", "summary", "detail", "metrics"}
        assert c["status"] in _VALID
        assert isinstance(c["metrics"], dict)
    # status_counts 自洽: 各档计数之和 == 组件数
    assert sum(snap["status_counts"].values()) == 6


def test_snapshot_wrapper_is_failure_safe(monkeypatch):
    def boom(now):
        raise RuntimeError("kaboom")

    def ok(now):
        return {
            "key": "ok",
            "label": "OK",
            "status": STATUS_GOOD,
            "summary": "",
            "detail": "",
            "metrics": {},
        }

    monkeypatch.setattr(monitor, "_COLLECTORS", [("traces", boom), ("quant_engine", ok)])
    snap = build_system_snapshot(now=1.0)
    by_key = {c["key"]: c for c in snap["components"]}
    assert by_key["traces"]["status"] == STATUS_UNKNOWN
    assert "kaboom" in by_key["traces"]["detail"]
    assert by_key["ok"]["status"] == STATUS_GOOD
    # unknown 不拉低, 余下为 good → 总状态 good
    assert snap["overall"] == STATUS_GOOD


def test_snapshot_dependency_failure_degrades_component(monkeypatch):
    import backend.diagnostics_store as ds

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(ds, "get_diagnostics_summary", boom)
    snap = build_system_snapshot(now=1.0)
    by_key = {c["key"]: c for c in snap["components"]}
    # tool_calls 依赖崩溃 → 该组件 unknown
    assert by_key["tool_calls"]["status"] == STATUS_UNKNOWN
    # 其它组件不受影响, 仍产出全部 6 个
    assert len(snap["components"]) == 6
    assert [c["key"] for c in snap["components"]] == _EXPECTED_KEYS


def test_snapshot_never_raises_real_collectors():
    # 端到端跑真实采集器(进程内缓存 + 本地 SQLite, 不触网), 只验证不抛 + 结构正确
    snap = build_system_snapshot()
    assert snap["overall"] in _VALID
    assert len(snap["components"]) == 6
