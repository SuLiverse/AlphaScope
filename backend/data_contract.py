"""数据契约 / Data Contract — Pandera schema 校验 (Phase A #5).

把 ``pandera`` 接入 AlphaScope, 给行情/财务数据加上**显式 schema 校验**, 补齐「数据
是否缺失/字段是否变了/值是否合法」这一层 (对应战略规划 Phase A 第 5 项「Pandera 数据
契约」与 §2「数据质量与数据契约 · Data Quality Gate」)。

设计要点 (延续项目「确定性 · 失败安全」基线):
- **可选依赖 + 优雅降级**: ``pandera`` 用 import-guard 包裹, 没装不影响其余功能 —
  ``validate_ohlcv`` 等函数在降级时返回 ``{"ok": True, "degraded": True, ...}``,
  让调用方知道「没校验过」而非误以为通过。
- **纯函数**: 对外暴露 ``validate_ohlcv / validate_bars / schema_available / describe``,
  全部失败安全、可单测。
- **不抛破坏性异常**: 校验失败不 raise, 而是返回结构化报告 (errors 列表), 由调用方
  决定如何处理 (回测引擎可选择跳过坏数据, 不让单条脏数据中断整个 pipeline)。
- **合规**: 本模块只校验数据结构合法性, 不预测、不荐股、不构成投资建议。

A​PI 已对照 pandera 0.20+ 真实源码核对 (非臆测):
- ``import pandera.pandas as pa`` (pandas 3.x 兼容入口)
- ``class Schema(pa.DataFrameModel)`` + ``Schema.validate(df)`` → 抛异常或返回 df
- 异常 ``pa.errors.ValidationError`` 含 ``failure_cases`` 明细
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: pandera 缺失时优雅降级 -----
try:
    import pandera.pandas as pa  # type: ignore[import-untyped]

    # pandera 0.20+: DataFrameModel/Column 从 pandera.pandas 导入 (顶层已弃用, 未来移除)
    from pandera.pandas import DataFrameModel, Column  # type: ignore[import-untyped]

    # pandera 0.20+: 多行校验错误是 SchemaErrors (复数); 旧版 ValidationError 已移除
    from pandera.errors import SchemaErrors  # type: ignore[import-untyped]

    import pandas as pd

    _PA_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    pa = None  # type: ignore[assignment]
    DataFrameModel = None  # type: ignore[assignment]
    Column = None  # type: ignore[assignment]
    SchemaErrors = None  # type: ignore[assignment]
    pd = None  # type: ignore[assignment]
    _PA_AVAILABLE = False


# ============================================================
# Schema 定义 (仅 pandera 可用时定义; 否则 None)
# ============================================================

if _PA_AVAILABLE:

    class OhlcvSchema(DataFrameModel):  # type: ignore[misc, valid-type]
        """标准 OHLCV 行情数据的契约。

        - date/open/high/low/close/volume 必须存在且类型正确
        - open/high/low/close >= 0 (价格非负)
        - high >= max(open, close), low <= min(open, close) (OHLC 一致性, 警告级)
        - volume >= 0
        """

        date: str
        open: float = pa.Field(ge=0)  # type: ignore[assignment]
        high: float = pa.Field(ge=0)  # type: ignore[assignment]
        low: float = pa.Field(ge=0)  # type: ignore[assignment]
        close: float = pa.Field(ge=0)  # type: ignore[assignment]
        volume: float = pa.Field(ge=0)  # type: ignore[assignment]

        class Config:
            strict = False  # 允许额外字段 (symbol/amount/change_pct 等), 不报错
            coerce = True  # 自动把 int 价格转 float

else:
    OhlcvSchema = None  # type: ignore[assignment]


# ============================================================
# 公开 API
# ============================================================


def schema_available() -> bool:
    """pandera 是否就绪。"""
    return _PA_AVAILABLE


def _bars_to_df(bars: list[dict[str, Any]]) -> Any:
    """把 OHLCV dict 列表转成 pandas DataFrame (pandera 要求 df 输入)。"""
    if pd is None or not bars:
        return None
    try:
        return pd.DataFrame(bars)
    except Exception:
        return None


def validate_ohlcv(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """校验 OHLCV 数据是否符合契约。

    返回结构化报告 (失败安全, 不抛):
    ```
    {"ok": bool, "degraded": bool, "errors": [str], "row_count": int,
     "checked_fields": [...], "mode": "pandera" | "disabled"}
    ```
    degraded=True 表示 pandera 不可用, 仅做了最小结构性检查 (字段存在性), 未做值校验。
    """
    base: dict[str, Any] = {
        "ok": True,
        "degraded": False,
        "errors": [],
        "row_count": len(bars) if isinstance(bars, list) else 0,
        "checked_fields": [],
        "mode": "disabled",
    }

    if not isinstance(bars, list) or len(bars) == 0:
        base["errors"].append("bars 为空或非列表")
        base["ok"] = len(bars) == 0  # 空列表算 ok (无数据可校验), 非列表算 fail
        return base

    # 字段存在性检查 (pandera 不可用时也做, 这是最低底线)
    required = ("date", "open", "high", "low", "close", "volume")
    base["checked_fields"] = list(required)
    first = bars[0] if isinstance(bars[0], dict) else {}
    missing = [f for f in required if f not in first]
    if missing:
        base["errors"].append(f"缺失必需字段: {missing}")
        base["ok"] = False
        return base

    if not _PA_AVAILABLE:
        # 降级: 仅做了字段存在性检查, 未做类型/值域校验
        base["degraded"] = True
        base["mode"] = "field_presence_only"
        return base

    # pandera 完整校验
    base["mode"] = "pandera"
    df = _bars_to_df(bars)
    if df is None:
        base["errors"].append("无法转成 DataFrame")
        base["ok"] = False
        return base

    try:
        OhlcvSchema.validate(df)  # type: ignore[union-attr]
    except SchemaErrors as e:  # type: ignore[misc]
        base["ok"] = False
        # 抽取 failure_cases 的可读明细
        try:
            cases = e.failure_cases  # type: ignore[attr-defined]
            # 每行一个错误, 限制条数防爆炸
            for _, row in cases.head(20).iterrows():
                col = row.get("column", "?")
                val = row.get("failure_case", "?")
                idx = row.get("index", "?")
                base["errors"].append(f"行{idx} 列{col}={val!r} 不符契约")
        except Exception:
            base["errors"].append(f"pandera 校验失败: {str(e)[:200]}")
    except Exception as e:
        base["ok"] = False
        base["errors"].append(f"校验异常: {str(e)[:200]}")
    return base


def validate_bars(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """validate_ohlcv 的别名 (语义: 校验 bar 列表)。"""
    return validate_ohlcv(bars)


def check_ohlcv_consistency(bars: list[dict[str, Any]]) -> list[str]:
    """额外的 OHLC 一致性检查 (pandera schema 之外的语义校验)。

    返回警告列表 (不阻塞 pipeline, 仅提示):
    - high < max(open, close): 异常 (high 应是最高)
    - low > min(open, close): 异常 (low 应是最低)
    - close 不在 [low, high] 区间: 异常

    纯函数, 不依赖 pandera, 始终可测。
    """
    warnings: list[str] = []
    if not isinstance(bars, list):
        return warnings
    for i, b in enumerate(bars):
        if not isinstance(b, dict):
            continue
        try:
            o = float(b.get("open", 0))
            h = float(b.get("high", 0))
            lo = float(b.get("low", 0))
            c = float(b.get("close", 0))
        except (TypeError, ValueError):
            continue
        if h < max(o, c) - 1e-9:
            warnings.append(f"行{i}: high={h} < max(open={o}, close={c})")
        if lo > min(o, c) + 1e-9:
            warnings.append(f"行{i}: low={lo} > min(open={o}, close={c})")
        if not (lo - 1e-9 <= c <= h + 1e-9):
            warnings.append(f"行{i}: close={c} 不在 [low={lo}, high={h}] 区间")
    return warnings


def describe() -> dict[str, Any]:
    """数据契约能力概览 (供 UI/调试)。"""
    return {
        "available": _PA_AVAILABLE,
        "mode": "pandera" if _PA_AVAILABLE else "field_presence_only",
        "schema": "OhlcvSchema (date/open/high/low/close/volume, 全部 ge=0)",
        "note": (
            "pandera 未装时仅做字段存在性检查, 不做类型/值域校验。 pip install pandera 启用完整契约校验。"
            if not _PA_AVAILABLE
            else "pandera 就绪, 校验 OHLCV 字段类型/非负/存在性。"
        ),
    }
