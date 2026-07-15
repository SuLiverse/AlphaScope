"""Integration Center API / 集成中心 (Phase 1).

暴露 AlphaScope 已注册的所有外部能力插件 (adapter), 以及交易边界概览。
对应主路线图 Phase 1 的 4 个端点 + UI「集成中心」面板的数据源。

端点:
- GET  /api/integrations                  列出所有 adapter 元数据 + 健康
- GET  /api/integrations/boundary         交易边界概览 (Phase 0 联动)
- GET  /api/integrations/{name}           单个 adapter 详情
- GET  /api/integrations/{name}/health    单个 adapter 健康
- POST /api/integrations/{name}/run       触发 adapter (受边界守卫, 禁 live order)
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.integrations.registry import (
    assert_boundary_invariant,
    get_registry,
)
from backend.schemas.api import ApiResponse
from backend.security.trading_boundary import (
    BoundaryViolation,
    describe_capabilities,
)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


# ----------------------------- 列表 / 详情 -----------------------------


@router.get("")
async def list_integrations() -> ApiResponse:
    """列出所有已注册 adapter 的元数据 + 健康摘要。"""
    try:
        reg = get_registry()
        health = reg.healthcheck_all()
        items = []
        for meta in reg.all_metadata():
            h = health.get(meta.name)
            items.append(
                {
                    **meta.model_dump(),
                    "health": h.model_dump() if h else None,
                }
            )
        return ApiResponse(
            success=True,
            data={
                "integrations": items,
                "count": len(items),
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.get("/boundary")
async def get_boundary_overview() -> ApiResponse:
    """交易边界概览 (供 UI「安全边界」面板)。"""
    try:
        return ApiResponse(success=True, data=describe_capabilities())
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


# 注意路由顺序: /marketplace 是字面路径, 必须先于参数路径 /{name} 声明,
# 否则 GET /marketplace 会被 /{name} 吞(name="marketplace")。
@router.get("/marketplace")
async def get_marketplace(category: str | None = None, installed_only: bool = False) -> ApiResponse:
    """插件市场目录(激活沉睡的 plugin_marketplace 模块)。

    返回市场概览 + 插件目录; 可按 category 过滤、只看已装。全部研究语义, 仅给安装指引不下单。
    """
    try:
        from backend import plugin_marketplace as pm

        if installed_only:
            plugins = pm.list_installed()
        elif category:
            plugins = pm.by_category(category)
        else:
            plugins = pm.list_catalog()
        return ApiResponse(
            success=True,
            data={
                "overview": pm.describe(),
                "plugins": plugins,
                "total": len(plugins),
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.get("/{name}")
async def get_integration(name: str) -> ApiResponse:
    """单个 adapter 详情。"""
    try:
        reg = get_registry()
        if not reg.has(name):
            return ApiResponse(success=False, error=f"未注册的 integration: {name}")
        adapter = reg.get(name)
        return ApiResponse(
            success=True,
            data={
                **adapter.metadata().model_dump(),
                "health": adapter.healthcheck().model_dump(),
            },
        )
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.get("/{name}/health")
async def get_integration_health(name: str) -> ApiResponse:
    """单个 adapter 健康检查。"""
    try:
        reg = get_registry()
        if not reg.has(name):
            return ApiResponse(success=False, error=f"未注册的 integration: {name}")
        return ApiResponse(success=True, data=reg.get(name).healthcheck().model_dump())
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


# ----------------------------- 运行 -----------------------------


class RunRequest(BaseModel):
    """触发 adapter 的通用入参 (具体含义由 adapter 类型决定)。"""

    capability: str = Field(default="", description="能力名 (如 run_backtest / analyze)")
    params: dict[str, Any] = Field(default_factory=dict)


class ParamSweepRequest(BaseModel):
    """vectorbt 参数扫描便捷入参: 服务端按 symbol 取 bars。"""

    symbol: str = Field(description="标的代码")
    days: int = Field(default=250, ge=30, le=2000)
    param_grid: dict[str, list] | None = Field(default=None)
    metric: str = Field(default="sharpe")
    top_n: int = Field(default=20, ge=1, le=100)


PARAM_SWEEP_DISCLAIMER = "vectorbt 扫描不完整模拟 A 股摩擦; DSR/PSR 仅校正历史样本与多重尝试偏差; 结果不构成投资建议。"


def _row_returns(row: dict[str, Any]) -> list[float]:
    returns = row.get("returns")
    if isinstance(returns, list):
        values: list[float] = []
        for value in returns:
            try:
                values.append(float(value))
            except (TypeError, ValueError):
                continue
        return values

    curve = row.get("equity_curve")
    if not isinstance(curve, list):
        return []
    values = []
    for point in curve:
        value = point.get("value") if isinstance(point, dict) else point
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return [
        (values[index] - values[index - 1]) / values[index - 1] for index in range(1, len(values)) if values[index - 1]
    ]


def _format_param_sweep_result(
    raw: Any,
    *,
    symbol: str,
    metric: str,
    n_trials: int,
) -> dict[str, Any]:
    """Normalize legacy list and future mapping sweep outputs to one API contract."""
    from backend.quant.metrics_advanced import attach_selection_bias_metrics

    if isinstance(raw, dict):
        rows = raw.get("results") or raw.get("top") or []
    else:
        rows = raw
    rows = rows if isinstance(rows, list) else []

    enriched: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            enriched.append(row)
            continue
        returns = _row_returns(row)
        metrics = dict(row.get("metrics") or {})
        already_enriched = {
            "probabilistic_sharpe",
            "deflated_sharpe",
            "n_trials_for_dsr",
        }.issubset(metrics)
        if not already_enriched:
            metrics = attach_selection_bias_metrics(
                metrics or row,
                returns,
                n_trials=n_trials,
                sharpe_key="sharpe",
            )
        observations = int(row.get("observations") or len(returns))
        selection_bias_status = str(
            row.get("selection_bias_status")
            or metrics.get("selection_bias_status")
            or ("ok" if observations >= 2 else "insufficient")
        )
        clean_row = {key: value for key, value in row.items() if key != "returns"}
        enriched.append(
            {
                **clean_row,
                "metrics": metrics,
                "probabilistic_sharpe": metrics.get("probabilistic_sharpe"),
                "deflated_sharpe": metrics.get("deflated_sharpe"),
                "n_trials": n_trials,
                "observations": observations,
                "selection_bias_status": selection_bias_status,
            }
        )

    has_insufficient = any(isinstance(row, dict) and row.get("selection_bias_status") != "ok" for row in enriched)
    status = "empty" if not enriched else ("degraded" if has_insufficient else "ok")
    return {
        "status": status,
        "engine": "vectorbt",
        "symbol": symbol,
        "metric": metric,
        "n_trials": max(1, int(n_trials)),
        "returned": len(enriched),
        "results": enriched,
        "top": enriched,
        "disclaimer": PARAM_SWEEP_DISCLAIMER,
    }


@router.post("/vectorbt/param-sweep")
async def vectorbt_param_sweep(req: ParamSweepRequest) -> ApiResponse:
    """产品化参数扫描: 从本地 price_store 取数 + vectorbt param_sweep + DSR。"""
    try:
        from backend.integrations.registry import get_registry
        from backend.integrations.backtest.vectorbt_adapter import count_param_trials
        from backend.price_store import get_prices

        assert_boundary_invariant()
        reg = get_registry()
        if not reg.has("vectorbt"):
            return ApiResponse(success=False, error="vectorbt adapter 未注册")
        adapter = reg.get("vectorbt")
        if not adapter.is_available():
            return ApiResponse(
                success=False,
                error="vectorbt 不可用, 请 pip install vectorbt",
            )

        bars = await asyncio.to_thread(lambda: get_prices(symbol=req.symbol, frequency="1d", limit=req.days))
        if not bars or len(bars) < 30:
            return ApiResponse(success=False, error="行情不足, 请先拉取价格数据")

        raw = await asyncio.to_thread(
            adapter.param_sweep,
            bars=bars,
            param_grid=req.param_grid,
            metric=req.metric,
            top_n=req.top_n,
        )
        data = _format_param_sweep_result(
            raw,
            symbol=req.symbol,
            metric=req.metric,
            n_trials=count_param_trials(req.param_grid),
        )
        return ApiResponse(success=True, data=data)
    except BoundaryViolation as e:
        return ApiResponse(success=False, error=f"交易边界拒绝: {e}")
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


@router.post("/{name}/run")
async def run_integration(name: str, req: RunRequest) -> ApiResponse:
    """触发 adapter 的某项能力 (受边界守卫)。

    注意: 任何「接近交易」的能力都被 Phase 0 边界禁止; 本端点绝不产生实盘订单。
    """
    try:
        # 启动边界守卫: 若边界被改坏, 拒绝执行
        assert_boundary_invariant()
        reg = get_registry()
        if not reg.has(name):
            return ApiResponse(success=False, error=f"未注册的 integration: {name}")
        adapter = reg.get(name)
        meta = adapter.metadata()
        if not adapter.is_available():
            return ApiResponse(success=False, error=f"adapter {name!r} 当前不可用")

        # 安全白名单: 这里只代理「研究/回测/分析」类能力, 由 adapter 自行实现具体 run。
        cap = (req.capability or "").strip()
        allowed = {c.name for c in meta.capabilities}
        if cap and cap not in allowed:
            return ApiResponse(
                success=False,
                error=f"adapter {name!r} 未声明能力 {cap!r}",
            )

        result = await asyncio.to_thread(
            _dispatch,
            adapter,
            meta.category.value,
            cap or _default_capability(meta.category.value),
            req.params,
        )
        return ApiResponse(success=True, data={"result": result})
    except BoundaryViolation as e:
        return ApiResponse(success=False, error=f"交易边界拒绝: {e}")
    except Exception as e:
        return ApiResponse(success=False, error=str(e))


def _default_capability(category: str) -> str:
    return {
        "backtest": "run_backtest",
        "agent": "analyze",
        "factor": "compute_factors",
        "data": "get_ohlcv",
    }.get(category, "")


def _dispatch(adapter: Any, category: str, capability: str, params: dict[str, Any]) -> Any:
    """按类别调用 adapter 的对应方法, 返回可序列化结果。

    覆盖已落地的四类能力: backtest/run_backtest, backtest/param_sweep (vectorBT),
    data/get_ohlcv (OpenBB), agent/analyze, factor/compute_factors。
    """
    if category == "backtest" and capability in ("", "run_backtest"):
        from backend.integrations.schemas import BacktestAssumptions

        assumptions = params.get("assumptions")
        res = adapter.run_backtest(
            strategy_id=params.get("strategy_id", "demo"),
            symbols=params.get("symbols", []),
            start=params.get("start", ""),
            end=params.get("end", ""),
            assumptions=BacktestAssumptions(engine_name=adapter.NAME, **(assumptions or {})),
            **_extra_backtest_kwargs(params),
        )
        return res.model_dump()
    if category == "backtest" and capability == "param_sweep":
        # vectorBT 的差异化能力: 参数网格扫描
        bars = params.get("bars", [])
        return adapter.param_sweep(
            bars=bars,
            param_grid=params.get("param_grid"),
            metric=params.get("metric", "sharpe"),
            top_n=int(params.get("top_n", 20)),
            **_extra_kwargs(params, {"bars", "param_grid", "metric", "top_n"}),
        )
    if category == "data" and capability in ("", "get_ohlcv"):
        # OpenBB 等数据源 adapter: 取历史 OHLCV
        symbol = params.get("symbol") or (params.get("symbols") or [""])[0]
        return adapter.get_ohlcv(
            symbol=symbol,
            start=params.get("start", ""),
            end=params.get("end", ""),
            **_extra_kwargs(params, {"symbol", "symbols", "start", "end"}),
        )
    if category == "agent" and (capability in ("", "analyze")):
        out = adapter.analyze(
            symbols=params.get("symbols", []),
            **_extra_kwargs(params, {"symbols"}),
        )
        return [o.model_dump() if hasattr(o, "model_dump") else o for o in out]
    if category == "factor" and (capability in ("", "compute_factors")):
        return adapter.compute_factors(
            symbols=params.get("symbols", []),
            **_extra_kwargs(params, {"symbols"}),
        )
    raise ValueError(f"adapter {adapter.NAME!r} 不支持能力 {capability!r}")


def _extra_backtest_kwargs(params: dict[str, Any]) -> dict[str, Any]:
    """把 backtest 的额外参数 (bars/fast/slow/fees/init_cash 等) 透传给 adapter。

    run_backtest 的基础字段 (strategy_id/symbols/start/end/assumptions) 已显式抽出,
    其余如 vectorBT 的 bars/fast/slow/fees/init_cash 通过 **kw 注入。
    """
    reserved = {"strategy_id", "symbols", "start", "end", "assumptions"}
    return {k: v for k, v in params.items() if k not in reserved}


def _extra_kwargs(params: dict[str, Any], reserved: set[str]) -> dict[str, Any]:
    return {key: value for key, value in params.items() if key not in reserved}
