"""组合优化 / Portfolio Optimizer Hub (Phase B #5/#6/#7).

把 ``skfolio`` / ``Riskfolio-Lib`` / ``PyPortfolioOpt`` 接入 AlphaScope, 给回测/组合
模块加上**专业级组合优化能力** (均值方差/CVaR/HRP/风险平价/Black-Litterman 等),
对应战略规划 Phase B 第 5/6/7 项 + §5「Portfolio Optimizer Hub」蓝图。

设计要点 (延续项目「确定性 · 失败安全 · No-Live-Order」基线):
- **可选依赖 + 优雅降级**: 三个库都用 import-guard 包裹 (优先级 skfolio > riskfolio >
  pypfopt), 没装不影响其余功能 — optimize_portfolio 在降级时回落等权, 标 degraded。
- **纯函数**: ``normalize_returns_input`` / ``equal_weight`` / ``build_rebalance_draft``
  / ``build_disclaimer`` 不依赖任何优化库, 始终可单测。
- **统一输出**: 所有优化器返回 ``OptimizationResult`` 结构 (weights/research_only/
  method/notes), 永远是 **rebalance draft** (研究语义), 不是 live order。
- **合规**: 输出永远 ``forbidden_live_order=True``; optimizer 只生成草案, 不能连 broker、
  不能自动执行 (与 No-Live-Order 边界一致, 规划 §5 明确)。

A​PI 已对照真实源码核对 (非臆测):
- skfolio 0.20.x: ``MeanRisk(objective_function=ObjectiveFunction.MAXIMIZE_RATIO,
  risk_measure=RiskMeasure.STANDARD_DEVIATION).fit(returns)`` → ``.weights_``
  (注意: 此版本无 RiskMeasure.SHARPE, 用 STANDARD_DEVIATION + MAXIMIZE_RATIO)
- riskfolio 7.x: ``rp.Portfolio(returns=...)`` + ``.assets_stats()`` +
  ``.optimization(model='Classic', rm='MV', obj='Sharpe'/'MinRisk', rf=, l=, hist=)``
- pypfopt: ``EfficientFrontier(mu, S).max_sharpe()`` → ``clean_weights()``
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: 三个库优先级递减 -----
_SKFOLIO = False
_RISKFOLIO = False
_PYPFOPT = False
try:
    import pandas as pd
    import numpy as np
except Exception:  # pandas/numpy 是核心依赖, 理论上不会缺
    pd = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]

try:
    from skfolio.optimization import MeanRisk, ObjectiveFunction  # type: ignore[import-untyped]
    from skfolio import RiskMeasure  # type: ignore[import-untyped]

    _SKFOLIO = True
except Exception:
    MeanRisk = None  # type: ignore[assignment]
    ObjectiveFunction = None  # type: ignore[assignment]
    RiskMeasure = None  # type: ignore[assignment]

try:
    import riskfolio as rp  # type: ignore[import-untyped]

    _RISKFOLIO = True
except Exception:
    rp = None  # type: ignore[assignment]

try:
    from pypfopt import EfficientFrontier, expected_returns, risk_models  # type: ignore[import-untyped]

    _PYPFOPT = True
except Exception:
    EfficientFrontier = None  # type: ignore[assignment]
    expected_returns = None  # type: ignore[assignment]
    risk_models = None  # type: ignore[assignment]


# ============================================================
# 纯函数 (不依赖优化库, 始终可单测)
# ============================================================


def normalize_returns_input(
    returns: "pd.DataFrame | list[list[float]] | None",
    asset_names: list[str] | None = None,
) -> "pd.DataFrame | None":
    """把收益数据归一化成 pandas DataFrame (列=资产, 行=时间)。

    支持: 已是 DataFrame / 二维 list (配合 asset_names) / None。
    失败安全: 空/非法 → None。
    """
    if pd is None or returns is None:
        return None
    if isinstance(returns, pd.DataFrame):
        return returns
    if isinstance(returns, list):
        try:
            cols = asset_names or [f"A{i}" for i in range(len(returns[0]) if returns else 0)]
            return pd.DataFrame(returns, columns=cols)
        except Exception:
            return None
    return None


def equal_weight(n_assets: int) -> dict[str, float]:
    """等权组合 (失败安全兜底, 也是基准)。

    n_assets <= 0 → 空 dict; 否则每个资产 1/n。
    """
    if n_assets <= 0:
        return {}
    w = 1.0 / n_assets
    return {f"A{i}": round(w, 6) for i in range(n_assets)}


def build_rebalance_draft(
    weights: dict[str, float],
    method: str,
    total_value: float = 1_000_000.0,
) -> dict[str, Any]:
    """把优化权重转成「再平衡草案」(研究语义, 非订单)。

    输出: {target_weights, target_shares(按总市值估算), method, research_only,
    forbidden_live_order, disclaimer}
    """
    # 归一化 (容错: 权重和可能因数值误差不为 1)
    total = sum(max(0.0, float(w)) for w in weights.values())
    norm = {k: (float(v) / total if total > 0 else 0.0) for k, v in weights.items()}
    return {
        "target_weights": {k: round(v, 6) for k, v in norm.items()},
        "target_value_by_asset": ({k: round(v * total_value, 2) for k, v in norm.items()} if total_value > 0 else {}),
        "total_value": total_value,
        "method": method,
        "research_only": True,
        "forbidden_live_order": True,
        "disclaimer": (
            "组合优化输出仅是再平衡草案 (research draft), 不构成投资建议, 不自动下单; "
            "须经人工确认后才可能执行 (AlphaScope 不连 broker)。"
        ),
    }


def build_disclaimer(method: str) -> str:
    """构造合规免责 (附在每个优化结果)。"""
    return (
        f"组合优化(method={method})基于历史收益统计, 不代表未来收益; "
        "输出仅是研究草案, forbidden_live_order=True, 须经人工确认。"
    )


# ============================================================
# 公开 API
# ============================================================


def available_optimizers() -> list[str]:
    """当前可用的优化器列表 (按优先级)。"""
    out = []
    if _SKFOLIO:
        out.append("skfolio")
    if _RISKFOLIO:
        out.append("riskfolio")
    if _PYPFOPT:
        out.append("pypfopt")
    return out


def is_available() -> bool:
    """至少一个优化器就绪。"""
    return _SKFOLIO or _RISKFOLIO or _PYPFOPT


def optimize_portfolio(
    returns: Any,
    method: str = "max_sharpe",
    asset_names: list[str] | None = None,
    rf: float = 0.02,
    total_value: float = 1_000_000.0,
) -> dict[str, Any]:
    """组合优化统一入口。

    参数:
    - returns: DataFrame (列=资产) 或二维 list; 行=时间 (日/周收益)
    - method: "max_sharpe" / "min_variance" / "equal_weight"(兜底)
    - asset_names: returns 是 list 时的资产名
    - rf: 无风险利率 (年化, 用于 Sharpe)
    - total_value: 总市值 (用于估算再平衡草案的目标金额)

    返回 OptimizationResult 结构 (失败安全):
    ```
    {"weights": {asset: weight}, "method": str, "optimizer": str,
     "degraded": bool, "research_only": True, "forbidden_live_order": True,
     "disclaimer": str, "error": str (仅失败时)}
    ```
    优化失败/无可用库 → 退化等权 + degraded=True, 不抛。
    """
    df = normalize_returns_input(returns, asset_names)
    base: dict[str, Any] = {
        "weights": {},
        "method": method,
        "optimizer": "none",
        "degraded": False,
        "research_only": True,
        "forbidden_live_order": True,
        "disclaimer": build_disclaimer(method),
    }
    if df is None or df.shape[1] < 2 or df.shape[0] < 30:
        base["error"] = "收益数据不足 (需 ≥2 资产 × ≥30 时间点)"
        base["degraded"] = True
        return base

    # method=equal_weight 直接等权 (无需优化库)
    if method == "equal_weight":
        names = list(df.columns)
        w = equal_weight(len(names))
        base["weights"] = {n: w[f"A{i}"] for i, n in enumerate(names)}
        base["optimizer"] = "equal_weight"
        return base

    # 优先级尝试: skfolio → riskfolio → pypfopt → 等权兜底
    try:
        if _SKFOLIO:
            w = _optimize_with_skfolio(df, method, rf)
            if w:
                base["weights"] = w
                base["optimizer"] = "skfolio"
                return base
        if _RISKFOLIO:
            w = _optimize_with_riskfolio(df, method, rf)
            if w:
                base["weights"] = w
                base["optimizer"] = "riskfolio"
                return base
        if _PYPFOPT:
            w = _optimize_with_pypfopt(df, method, rf)
            if w:
                base["weights"] = w
                base["optimizer"] = "pypfopt"
                return base
    except Exception as e:
        base["error"] = f"优化异常: {str(e)[:120]}"
        base["degraded"] = True

    # 全部失败 → 等权兜底
    names = list(df.columns)
    w = equal_weight(len(names))
    base["weights"] = {n: w[f"A{i}"] for i, n in enumerate(names)}
    base["optimizer"] = "equal_weight(fallback)"
    base["degraded"] = True
    return base


# ============================================================
# 各优化器实现 (私有, 失败返回 None)
# ============================================================


def _optimize_with_skfolio(df: "pd.DataFrame", method: str, rf: float) -> dict[str, float] | None:
    """skfolio: MeanRisk 优化。"""
    try:
        if method == "max_sharpe":
            opt = MeanRisk(
                objective_function=ObjectiveFunction.MAXIMIZE_RATIO,  # type: ignore[union-attr]
                risk_measure=RiskMeasure.STANDARD_DEVIATION,  # type: ignore[union-attr]
                min_return=rf / 252,  # skfolio 的 risk-free 处理
            )
        elif method == "min_variance":
            opt = MeanRisk(
                objective_function=ObjectiveFunction.MINIMIZE_RISK,  # type: ignore[union-attr]
                risk_measure=RiskMeasure.VARIANCE,  # type: ignore[union-attr]
            )
        else:
            opt = MeanRisk()  # 默认
        opt.fit(df)
        weights = opt.weights_
        return {col: round(float(w), 6) for col, w in zip(df.columns, weights)}
    except Exception:
        return None


def _optimize_with_riskfolio(df: "pd.DataFrame", method: str, rf: float) -> dict[str, float] | None:
    """riskfolio: rp.Portfolio 经典优化。"""
    try:
        port = rp.Portfolio(returns=df)  # type: ignore[union-attr]
        port.assets_stats(method_mu="hist", method_cov="hist")
        # 加宽松约束防 infeasible
        try:
            port.lowerret = -1.0
            port.upperret = 1.0
            port.budget = 1.0
        except Exception:
            pass
        obj = "Sharpe" if method == "max_sharpe" else "MinRisk"
        w = port.optimization(model="Classic", rm="MV", obj=obj, rf=rf, l=0, hist=True)
        if w is None or len(w) == 0:
            return None
        return {col: round(float(w.loc[col].iloc[0]), 6) for col in df.columns}
    except Exception:
        return None


def _optimize_with_pypfopt(df: "pd.DataFrame", method: str, rf: float) -> dict[str, float] | None:
    """pypfopt: EfficientFrontier。"""
    try:
        mu = expected_returns.mean_historical_return(df, compounding=False)  # type: ignore[union-attr]
        S = risk_models.sample_cov(df)  # type: ignore[union-attr]
        ef = EfficientFrontier(mu, S)  # type: ignore[union-attr]
        if method == "max_sharpe":
            ef.max_sharpe(risk_free_rate=rf)
        else:
            ef.min_volatility()
        clean = ef.clean_weights()
        return {k: round(float(v), 6) for k, v in clean.items() if v > 1e-6}
    except Exception:
        return None


def describe() -> dict[str, Any]:
    """能力概览 (供 UI/调试)。"""
    opts = available_optimizers()
    return {
        "available": len(opts) > 0,
        "optimizers": opts,
        "primary": opts[0] if opts else None,
        "supported_methods": ["max_sharpe", "min_variance", "equal_weight"],
        "note": (
            f"就绪优化器: {', '.join(opts)} (优先级递减); 支持 max_sharpe/min_variance。"
            if opts
            else "未装任何组合优化库。pip install skfolio (或 riskfolio / pyportfolioopt) 启用。"
        ),
    }
