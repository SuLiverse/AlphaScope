"""系统监控中心聚合器 (v1.9.10)

把分散在各 observability / quant 子系统里的健康信号聚合成**单一快照**,
供前端「监控中心」做单页总览(数据源 / 回测引擎 / 实验记录 / 模型成本 /
工具调用 / 执行追踪)。

设计:
- **纯聚合 + 失败安全**:任一组件采集失败只把该组件标记为 ``unknown``,
  绝不抛出、不影响其它组件(沿用本项目「诚实降级、绝不伪造正常」的约定)。
- **不触网**:只读各子系统已缓存的进程内状态与本地 SQLite, 不发起任何
  数据源请求。
- **可单测**:状态分级逻辑抽成纯函数(``tool_call_status`` /
  ``trace_status`` / ``grade_from_quality``), 可脱离子系统直接断言。

合规:本面板仅反映系统**自身运行状态**, 不涉及任何标的预测或投资建议。
"""

from __future__ import annotations

import time
from typing import Any, Callable

# ---- 组件健康分级 ----
STATUS_GOOD = "good"
STATUS_WARN = "warn"
STATUS_POOR = "poor"
STATUS_UNKNOWN = "unknown"

# 质量分阈值(与 observability/source_health 一致)
QUALITY_GOOD = 80.0
QUALITY_WARN = 50.0

_LABELS = {
    "data_sources": "数据源",
    "quant_engine": "回测引擎",
    "experiments": "实验记录",
    "llm_cost": "模型调用成本",
    "tool_calls": "工具调用",
    "traces": "执行追踪",
}

_OVERALL_LABEL = {
    STATUS_GOOD: "运行正常",
    STATUS_WARN: "部分降级",
    STATUS_POOR: "存在异常",
    STATUS_UNKNOWN: "状态未知",
}

_DISCLAIMER = "本面板仅反映系统自身运行状态(数据源/引擎/成本/调用),不构成任何投资建议或预测。"


# ============== 纯函数:状态分级 ==============


def grade_from_quality(score: float) -> str:
    """数据源平均质量分 → 红黄绿等级。"""
    if score >= QUALITY_GOOD:
        return STATUS_GOOD
    if score >= QUALITY_WARN:
        return STATUS_WARN
    return STATUS_POOR


def tool_call_status(total: int, errors: int) -> str:
    """工具调用错误率 → 健康分级。无调用视为正常。"""
    if total <= 0:
        return STATUS_GOOD
    rate = errors / total
    if rate >= 0.3:
        return STATUS_POOR
    if rate >= 0.1:
        return STATUS_WARN
    return STATUS_GOOD


def trace_status(total_spans: int, error_spans: int) -> str:
    """执行追踪 span 错误率 → 健康分级。无 span 视为正常。"""
    if total_spans <= 0:
        return STATUS_GOOD
    rate = error_spans / total_spans
    if rate >= 0.25:
        return STATUS_POOR
    if rate >= 0.1:
        return STATUS_WARN
    return STATUS_GOOD


def compute_overall_status(components: list[dict[str, Any]]) -> str:
    """由各组件状态聚合系统总状态。

    规则:任一 ``poor`` → poor; 否则任一 ``warn`` → warn; 否则全部已知为
    good → good。``unknown`` 组件不参与判定(未知不等于异常); 若全部未知 →
    unknown。
    """
    known = [str(c.get("status")) for c in components if str(c.get("status")) != STATUS_UNKNOWN]
    if not known:
        return STATUS_UNKNOWN
    if STATUS_POOR in known:
        return STATUS_POOR
    if STATUS_WARN in known:
        return STATUS_WARN
    return STATUS_GOOD


def _component(
    key: str,
    status: str,
    summary: str,
    detail: str = "",
    metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": _LABELS.get(key, key),
        "status": status,
        "summary": summary,
        "detail": detail,
        "metrics": metrics or {},
    }


# ============== 组件采集器(各自失败安全) ==============


def _collect_data_sources(now: float) -> dict[str, Any]:
    from backend.observability.source_health import compute_quality_score
    from backend.providers.registry import get_registry

    registry = get_registry()
    total = healthy = degraded = unhealthy = 0
    good = warn = poor = 0
    quals: list[float] = []
    for _name, provider in registry._providers.items():
        h = provider.health
        status = h.status.value if hasattr(h.status, "value") else str(h.status)
        total += 1
        if status == "healthy":
            healthy += 1
        elif status == "degraded":
            degraded += 1
        else:
            unhealthy += 1
        entry = {
            "status": status,
            "consecutive_failures": getattr(h, "consecutive_failures", 0),
            "avg_latency_ms": getattr(h, "avg_latency_ms", 0),
            "last_success": getattr(h, "last_success", 0),
        }
        q = compute_quality_score(entry, now=now)
        quals.append(q["quality_score"])
        if q["grade"] == "good":
            good += 1
        elif q["grade"] == "warn":
            warn += 1
        else:
            poor += 1

    if total == 0:
        return _component("data_sources", STATUS_UNKNOWN, "无已注册数据源", metrics={"total": 0})
    avg_quality = round(sum(quals) / len(quals), 1)
    return _component(
        "data_sources",
        grade_from_quality(avg_quality),
        f"{healthy}/{total} 正常 · 均分 {avg_quality}",
        metrics={
            "total": total,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "avg_quality": avg_quality,
            "quality_good": good,
            "quality_warn": warn,
            "quality_poor": poor,
        },
    )


def _collect_quant_engine(now: float) -> dict[str, Any]:
    from backend.quant.local_runner import local_status_payload

    payload = local_status_payload()
    strat = int(payload.get("strategy_count", 0) or 0)
    runs = int(payload.get("run_count", 0) or 0)
    return _component(
        "quant_engine",
        STATUS_GOOD,
        f"本地引擎在线 · {strat} 策略 · {runs} 次运行",
        metrics={
            "strategy_count": strat,
            "run_count": runs,
            "execution_mode": payload.get("execution_mode", "local"),
            "capabilities": payload.get("capabilities", {}),
        },
    )


def _collect_experiments(now: float) -> dict[str, Any]:
    from backend.quant.experiment_store import count_experiments

    total = int(count_experiments() or 0)
    return _component(
        "experiments",
        STATUS_GOOD,
        f"{total} 条实验记录已持久化",
        metrics={"total": total},
    )


def _collect_llm_cost(now: float) -> dict[str, Any]:
    from backend.diagnostics_store import get_cost_summary

    cs = get_cost_summary(now=now)
    windows = cs.get("windows", {}) or {}
    today = windows.get("today", {}) or {}
    total = windows.get("total", {}) or {}
    return _component(
        "llm_cost",
        STATUS_GOOD,
        f"今日 {today.get('calls', 0)} 次 · ${today.get('cost_usd', 0)} · 累计 ${total.get('cost_usd', 0)}",
        metrics={
            "today": today,
            "last_7d": windows.get("last_7d", {}),
            "total": total,
            "by_model": (cs.get("by_model") or [])[:8],
        },
    )


def _collect_tool_calls(now: float) -> dict[str, Any]:
    from backend.diagnostics_store import get_diagnostics_summary

    summary = get_diagnostics_summary()
    tc = summary.get("tool_calls", {}) or {}
    total = int(tc.get("total", 0) or 0)
    errors = int(tc.get("errors", 0) or 0)
    rate = round(errors / total * 100, 1) if total else 0.0
    return _component(
        "tool_calls",
        tool_call_status(total, errors),
        f"{total} 次调用 · {errors} 错误 · 错误率 {rate}%",
        metrics={
            "total": total,
            "errors": errors,
            "error_rate": rate,
            "avg_latency_ms": tc.get("avg_latency_ms", 0),
        },
    )


def _collect_traces(now: float) -> dict[str, Any]:
    from backend.observability.tracer import get_tracer

    stats = get_tracer().get_stats()
    total_spans = int(stats.get("total_spans", 0) or 0)
    error_spans = int(stats.get("error_spans", 0) or 0)
    return _component(
        "traces",
        trace_status(total_spans, error_spans),
        f"{stats.get('total_traces', 0)} 追踪 · {total_spans} span · "
        f"{error_spans} 错误 · 均时 {stats.get('avg_duration_ms', 0)}ms",
        metrics=stats,
    )


_COLLECTORS: list[tuple[str, Callable[[float], dict[str, Any]]]] = [
    ("data_sources", _collect_data_sources),
    ("quant_engine", _collect_quant_engine),
    ("experiments", _collect_experiments),
    ("llm_cost", _collect_llm_cost),
    ("tool_calls", _collect_tool_calls),
    ("traces", _collect_traces),
]


def build_system_snapshot(now: float | None = None) -> dict[str, Any]:
    """聚合系统监控快照。

    逐个调用组件采集器, 单个失败降级为 ``unknown`` 组件而不中断整体;
    最终算出系统总状态。永不抛出。

    Args:
        now: 当前时间戳(测试注入); 默认 ``time.time()``。
    """
    now = time.time() if now is None else now
    components: list[dict[str, Any]] = []
    for key, fn in _COLLECTORS:
        try:
            components.append(fn(now))
        except Exception as exc:  # noqa: BLE001 - 失败安全, 任一组件不拖垮整体
            components.append(_component(key, STATUS_UNKNOWN, "采集失败", detail=str(exc)))

    overall = compute_overall_status(components)
    counts = {STATUS_GOOD: 0, STATUS_WARN: 0, STATUS_POOR: 0, STATUS_UNKNOWN: 0}
    for c in components:
        counts[str(c.get("status"))] = counts.get(str(c.get("status")), 0) + 1

    return {
        "generated_at": now,
        "overall": overall,
        "overall_label": _OVERALL_LABEL.get(overall, overall),
        "component_count": len(components),
        "status_counts": counts,
        "components": components,
        "disclaimer": _DISCLAIMER,
    }
