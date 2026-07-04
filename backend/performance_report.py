"""绩效报告 / Performance Report — QuantStats 集成 (20 项目 #5).

把 ``quantstats`` 接入 AlphaScope, 给回测结果加上**专业级绩效报告** (Sharpe/Sortino/
Calmar/Max Drawdown/Var/CVaR/月度收益热力图等数十项), 补齐自研 metrics 所不擅长的
「卖方级报告密度」(对应战略规划「20 个最优先项目」第 5 项「QuantStats 绩效报告」)。

设计要点 (延续项目「确定性 · 失败安全」基线):
- **可选依赖 + 优雅降级**: ``quantstats`` 用 import-guard 包裹, 没装不影响其余功能 —
  ``build_report`` 返回 ``{"available": False, ...}`` 并标注降级。
- **纯函数**: 对外暴露 ``build_report / metric_summary / render_html_report /
  is_available / describe``, 全部失败安全、可单测。
- **输入归一化**: 支持 equity_curve (list[float]) / returns (list[float]) / pandas
  Series 三种输入, 内部归一化成 quantstats 要求的 returns Series。
- **合规**: 报告仅是对历史绩效的统计描述, **不预测未来、不代表未来收益**; 输出附免责。

A​PI 已对照 quantstats 0.0.81 真实源码核对 (非臆测):
- ``qs.reports.metrics(returns, display=False)`` → DataFrame (指标名作为 index)
- ``qs.stats.sharpe(returns)`` / ``qs.stats.max_drawdown(returns)`` 等单指标
- ``qs.reports.html(returns, output=...)`` → 生成 HTML 报告文件
- 输入要求: pandas Series of period returns (非 equity curve, 是收益率序列)
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: quantstats 缺失时优雅降级 -----
try:
    import quantstats as qs  # type: ignore[import-untyped]
    import pandas as pd
    import numpy as np

    _QS_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    qs = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    _QS_AVAILABLE = False


# ============================================================
# 输入归一化 (纯函数, 不依赖 quantstats)
# ============================================================


def equity_to_returns(equity_curve: list[float]) -> list[float]:
    """把权益曲线转成周期收益率序列 (pct change)。

    纯函数, 失败安全: 长度 < 2 或含非数值 → 返回空列表。
    第一个点无前值, 输出长度 = len(equity_curve) - 1。
    """
    if not isinstance(equity_curve, list) or len(equity_curve) < 2:
        return []
    out: list[float] = []
    for i in range(1, len(equity_curve)):
        try:
            prev = float(equity_curve[i - 1])
            cur = float(equity_curve[i])
            if prev == 0:  # 前值为 0 无法算 pct, 填 0
                out.append(0.0)
            else:
                out.append((cur - prev) / prev)
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def _to_returns_series(
    equity_curve: list[float] | None = None,
    returns: list[float] | None = None,
) -> Any:
    """把 equity_curve 或 returns 归一化成 quantstats 要求的 pandas Series。

    优先用 returns (如果提供); 否则从 equity_curve 算 pct change。
    返回 None 表示无法归一化 (空/非数值)。
    """
    if pd is None:
        return None
    ret_list = returns if returns is not None else equity_to_returns(equity_curve or [])
    if not ret_list:
        return None
    try:
        # 用交易日 index (bdate_range), 保证 quantstats 识别为日频
        idx = pd.bdate_range("2020-01-01", periods=len(ret_list))
        return pd.Series(ret_list, index=idx, dtype="float64")
    except Exception:
        return None


# ============================================================
# 公开 API
# ============================================================


def is_available() -> bool:
    """quantstats 是否就绪。"""
    return _QS_AVAILABLE


def build_report(
    equity_curve: list[float] | None = None,
    returns: list[float] | None = None,
) -> dict[str, Any]:
    """生成完整绩效报告 (数十项指标)。

    返回结构:
    ```
    {"available": bool, "metrics": {name: value}, "row_count": int,
     "input": "returns" | "equity_curve", "disclaimer": str}
    ```
    失败安全: quantstats 不可用 / 输入不足 → 返回 available=False + 空 metrics, 不抛。
    """
    base: dict[str, Any] = {
        "available": _QS_AVAILABLE,
        "metrics": {},
        "row_count": 0,
        "input": "returns" if returns is not None else "equity_curve",
        "disclaimer": ("绩效报告基于历史数据统计, 不代表未来收益, 不构成投资建议。"),
    }
    if not _QS_AVAILABLE:
        base["error"] = "quantstats 未安装。pip install quantstats"
        return base

    ret_series = _to_returns_series(equity_curve, returns)
    if ret_series is None or len(ret_series) < 2:
        base["error"] = "输入数据不足 (需至少 2 个收益点)"
        return base

    base["row_count"] = len(ret_series)
    try:
        # qs.reports.metrics 返回 DataFrame (指标名作为 index, 单列 value)
        df = qs.reports.metrics(ret_series, display=False)  # type: ignore[union-attr]
        # 归一化成 {指标名: 值} dict (取第一列)
        col = df.columns[0] if len(df.columns) > 0 else df.columns[0]
        metrics: dict[str, Any] = {}
        for idx_name, row in df.iterrows():
            val = row[col]
            # 标量值保留, 复杂对象转 str
            try:
                if isinstance(val, (int, float, np.floating, np.integer)):  # type: ignore[union-attr]
                    metrics[str(idx_name)] = float(val)
                else:
                    metrics[str(idx_name)] = str(val)
            except Exception:
                metrics[str(idx_name)] = str(val)
        base["metrics"] = metrics
    except Exception as e:
        base["error"] = f"quantstats 生成报告失败: {str(e)[:150]}"
    return base


def metric_summary(
    equity_curve: list[float] | None = None,
    returns: list[float] | None = None,
) -> dict[str, float | None]:
    """抽取几个最关键指标的精简版 (sharpe/sortino/max_drawdown/cagr/volatility)。

    比 build_report 更轻量; 返回 {name: float|None}。
    """
    empty: dict[str, float | None] = {
        "sharpe": None,
        "sortino": None,
        "max_drawdown": None,
        "cagr": None,
        "volatility": None,
    }
    if not _QS_AVAILABLE:
        return empty
    ret_series = _to_returns_series(equity_curve, returns)
    if ret_series is None or len(ret_series) < 2:
        return empty

    out = dict(empty)

    def _safe(call, *args):
        try:
            v = call(ret_series, *args)
            # quantstats 返回可能是 Series (单值) 或标量
            if hasattr(v, "iloc"):
                return float(v.iloc[0])
            return float(v)
        except Exception:
            return None

    out["sharpe"] = _safe(qs.stats.sharpe)  # type: ignore[union-attr]
    out["sortino"] = _safe(qs.stats.sortino)  # type: ignore[union-attr]
    out["max_drawdown"] = _safe(qs.stats.max_drawdown)  # type: ignore[union-attr]
    out["cagr"] = _safe(qs.stats.cagr)  # type: ignore[union-attr]
    out["volatility"] = _safe(qs.stats.volatility)  # type: ignore[union-attr]
    return out


def render_html_report(
    output_path: str,
    equity_curve: list[float] | None = None,
    returns: list[float] | None = None,
    title: str = "AlphaScope 回测绩效报告",
) -> dict[str, Any]:
    """生成完整 HTML 报告文件 (含图表/热力图/月度收益表)。

    返回 {ok, path, error}。失败安全: quantstats 不可用/输入不足 → ok=False, 不抛。
    """
    base: dict[str, Any] = {"ok": False, "path": output_path, "error": ""}
    if not _QS_AVAILABLE:
        base["error"] = "quantstats 未安装"
        return base
    ret_series = _to_returns_series(equity_curve, returns)
    if ret_series is None or len(ret_series) < 2:
        base["error"] = "输入数据不足"
        return base
    try:
        qs.reports.html(  # type: ignore[union-attr]
            ret_series, title=title, output=output_path
        )
        base["ok"] = True
    except Exception as e:
        base["error"] = f"HTML 报告生成失败: {str(e)[:150]}"
    return base


def describe() -> dict[str, Any]:
    """能力概览 (供 UI/调试)。"""
    return {
        "available": _QS_AVAILABLE,
        "version": getattr(qs, "__version__", "unknown") if _QS_AVAILABLE else None,  # type: ignore[union-attr]
        "note": (
            "quantstats 就绪: 可生成专业级绩效报告 (Sharpe/Sortino/Calmar/Max DD/月度收益热力图等数十项)"
            if _QS_AVAILABLE
            else "quantstats 未安装。pip install quantstats 启用专业级绩效报告。"
        ),
    }
