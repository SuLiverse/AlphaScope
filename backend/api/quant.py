"""量化实验室 API — 项目内置本地回测端点。

本模块默认不探测、不监听外部量化服务。参考外部量化项目的策略/回测/报告思路，
但运行链路固定使用当前项目内置策略、行情缓存、provider 取数和本地回测引擎。

路由定义在此文件；业务实现见 quant_core（再导出以兼容既有测试 import 路径）。
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from backend.api.quant_schemas import (
    BacktestRequestBody,
    ChipDistributionRequestBody,
    EvolveRequestBody,
    ExperimentCompareBody,
    LiveStartBody,
    LiveStopBody,
    PatternsRequestBody,
    StockPoolExportRequest,
    StrategyCompareRequestBody,
    TdxCompileRequestBody,
    WalkForwardRequestBody,
)
from backend.api import quant_core
from backend.api.quant_core import (
    _builtin_strategy_data,
    _extract_stock_pool_symbols,
    _local_run_details,
    _local_runs,
    _local_status_payload,
    _run_chip_distribution_local,
    _run_evolution_local,
    _run_local_backtest,
    _run_patterns_local,
    _run_strategy_comparison_local,
    _run_walk_forward_local,
    _stock_pool_csv,
    run_local_backtest_payload,
)
from backend.schemas.api import ApiResponse

# Historical re-exports for tests: `from backend.api.quant import X`
_load_local_bars = quant_core._load_local_bars
_require_bars = quant_core._require_bars
_source_fields = quant_core._source_fields

router = APIRouter(prefix="/api/quant", tags=["quant"])


def __getattr__(name: str) -> Any:
    """Expose quant_core helpers on this module for historical imports."""
    if hasattr(quant_core, name):
        return getattr(quant_core, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ============================================================
# 端点
# ============================================================


@router.get("/status")
async def get_status():
    """获取回测能力状态"""
    data = _local_status_payload()
    return ApiResponse(
        success=True,
        data=data,
        message="本地回测引擎可用。",
    )


@router.get("/strategies")
async def list_strategies():
    """获取策略列表"""
    return ApiResponse(
        success=True,
        data={
            "strategies": _builtin_strategy_data(),
            "can_run_backtest": True,
            "local_backtest_available": True,
            "execution_mode": "local",
            "source_status": "local",
            "degraded": False,
        },
    )


@router.get("/strategies/{strategy_name}")
async def get_strategy(strategy_name: str):
    """获取本地内置策略详情"""
    for strategy in _builtin_strategy_data():
        if strategy.get("name") == strategy_name:
            return ApiResponse(success=True, data=strategy)
    from fastapi import HTTPException

    raise HTTPException(status_code=404, detail=f"策略不存在: {strategy_name}")


@router.get("/builtin-strategies")
async def list_builtin_strategies():
    """列出本地内置策略"""
    return ApiResponse(success=True, data=_builtin_strategy_data())


@router.post("/strategies/reload")
async def reload_strategies():
    """重载策略"""
    strategies = _builtin_strategy_data()
    return ApiResponse(
        success=True,
        data={
            "reloaded": len(strategies),
            "strategies": strategies,
            "can_run_backtest": True,
            "local_backtest_available": True,
            "execution_mode": "local",
            "source_status": "local",
            "degraded": False,
        },
        message=f"已加载 {len(strategies)} 个本地策略。",
    )


@router.post("/stock-pool/export")
async def export_stock_pool(body: StockPoolExportRequest):
    """Export a parsed stock pool as a testable server-side CSV file."""
    symbols = _extract_stock_pool_symbols(body.text)
    if not symbols:
        return ApiResponse(
            success=False,
            error="No valid stock symbols found",
            error_code="STOCK_POOL_EMPTY",
        )

    csv_text = _stock_pool_csv(symbols)
    return Response(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="alphascope-stock-pool.csv"'},
    )


@router.post("/backtest")
async def run_backtest(body: BacktestRequestBody):
    """发起回测（同步重计算丢线程池，避免阻塞事件循环）"""
    try:
        result = await asyncio.to_thread(_run_local_backtest, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_BACKTEST_ERROR",
        )


@router.post("/walk-forward")
async def run_walk_forward_endpoint(body: WalkForwardRequestBody):
    """样本外走查(walk-forward)稳健性分析。

    把历史切成锚定/滚动的 IS+OOS 窗口，逐窗用同一策略回测，评估策略在不同
    历史区间的稳健性(而非单一窗口的运气)。纯确定性、失败安全。
    同步重计算丢线程池，避免阻塞事件循环。
    """
    try:
        result = await asyncio.to_thread(_run_walk_forward_local, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_WALK_FORWARD_ERROR",
        )


@router.post("/chip-distribution")
async def run_chip_distribution_endpoint(body: ChipDistributionRequestBody):
    """筹码(成本)分布分析。

    用换手率扩散模型重建当前持仓成本分布,读出获利盘/平均成本/集中度/上下方
    筹码密集价。纯确定性、失败安全;描述历史成本结构,不预测价格、不构成建议。
    同步重计算丢线程池,避免阻塞事件循环。
    """
    try:
        result = await asyncio.to_thread(_run_chip_distribution_local, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_CHIP_DISTRIBUTION_ERROR",
        )


@router.post("/patterns")
async def run_patterns_endpoint(body: PatternsRequestBody):
    """K 线形态识别。确定性检出蜡烛形态(吞没/锤子/十字星/启明星-黄昏星/红三兵-三只乌鸦)
    与结构信号(跳空/N 日突破/均线金叉死叉/双顶双底)。纯本地、失败安全;描述历史形态,
    不预测涨跌、不构成任何投资建议。同步重计算丢线程池,避免阻塞事件循环。
    """
    try:
        result = await asyncio.to_thread(_run_patterns_local, body)
        return ApiResponse(success=True, data=result, message=result.get("note") or None)
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_PATTERNS_ERROR",
        )


@router.post("/compare-strategies")
async def run_strategy_comparison_endpoint(body: StrategyCompareRequestBody):
    """策略横向对比:同一标的/区间跑全部内置策略并按指标排名。

    一次取数、复用已测回测引擎逐策略回测,帮助快速看哪些策略在该标的上历史表现更好。
    纯本地、确定性;同步重计算丢线程池,避免阻塞事件循环。结果仅供历史研究,不构成选股建议。
    """
    try:
        result = await asyncio.to_thread(_run_strategy_comparison_local, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_STRATEGY_COMPARE_ERROR",
        )


@router.post("/evolve")
async def run_evolution_endpoint(body: EvolveRequestBody):
    """遗传算法策略参数寻优。

    在策略的数值参数空间内用**确定性**遗传算法(同 seed 同结果)搜索更优组合,
    适应度=复用回测引擎跑一遍的某项绩效(默认夏普)。纯本地、失败安全。
    同步重计算丢线程池,避免阻塞事件循环。

    合规:样本内寻优极易过拟合,样本内最优≠未来有效;响应附强免责并建议对最优
    参数再做样本外走查验证。不构成任何投资建议。
    """
    try:
        result = await asyncio.to_thread(_run_evolution_local, body)
        return ApiResponse(success=True, data=result, message=result.get("message"))
    except Exception as e:
        return ApiResponse(
            success=False,
            error=str(e),
            error_code="LOCAL_EVOLUTION_ERROR",
        )


@router.get("/param-space/{strategy_name}")
async def get_param_space_endpoint(strategy_name: str):
    """返回某策略可寻优的数值参数空间(供进化面板预填默认范围)。"""
    from backend.quant.evolution import infer_param_space

    space = await asyncio.to_thread(infer_param_space, strategy_name)
    return ApiResponse(
        success=True,
        data={
            "strategy_id": strategy_name,
            "param_space": space,
            "evolvable": bool(space),
        },
    )


@router.get("/experiments")
async def list_experiments_endpoint(mode: str = "", symbol: str = "", limit: int = Query(50, ge=1, le=500)):
    """列举已持久化的量化实验(回测/走查/筹码/策略榜),按时间倒序,可按 mode/symbol 过滤。"""
    from backend.quant.experiment_store import count_experiments, list_experiments

    items = await asyncio.to_thread(list_experiments, limit=limit, mode=mode or None, symbol=symbol or None)
    return ApiResponse(
        success=True,
        data={"experiments": items, "total": count_experiments()},
    )


@router.get("/experiments/{run_id}")
async def get_experiment_endpoint(run_id: str):
    """取一次实验的完整载荷。"""
    from backend.quant.experiment_store import get_experiment

    result = await asyncio.to_thread(get_experiment, run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"实验记录不存在: {run_id}")
    return ApiResponse(success=True, data=result)


@router.delete("/experiments/{run_id}")
async def delete_experiment_endpoint(run_id: str):
    """删除一次实验记录。"""
    from backend.quant.experiment_store import delete_experiment

    ok = await asyncio.to_thread(delete_experiment, run_id)
    return ApiResponse(success=ok, data={"run_id": run_id, "deleted": ok})


@router.post("/experiments/compare")
async def compare_experiments_endpoint(body: ExperimentCompareBody):
    """取若干实验的摘要并排,供横向对比。"""
    from backend.quant.experiment_store import compare_experiments

    rows = await asyncio.to_thread(compare_experiments, body.run_ids)
    return ApiResponse(success=True, data={"items": rows, "count": len(rows)})


@router.post("/tdx/compile")
async def compile_tdx_endpoint(body: TdxCompileRequestBody):
    """编译/校验通达信(TDX)公式(不回测),返回解析结构、买卖信号与错误/告警。

    用于前端「编译」按钮即时反馈语法是否合法、识别出哪些买卖信号。要回测时,用
    `/api/quant/backtest` 传 strategy_id="tdx", params={"formula": ...}。
    """
    from backend.quant.tdx_compiler import compile_formula

    compiled = compile_formula(body.formula)
    return ApiResponse(
        success=compiled.ok,
        data=compiled.to_dict(),
        message=("公式编译通过。" if compiled.ok else "公式有错误,请查看 errors。"),
    )


@router.post("/live/start")
async def start_live(body: LiveStartBody):
    """启动实盘"""
    return ApiResponse(
        success=False,
        error="本地量化实验室暂未接入实盘执行，只支持历史回测。",
        error_code="LOCAL_LIVE_NOT_IMPLEMENTED",
        data={"strategy_id": body.strategy_id, "symbol": body.symbol},
    )


@router.post("/live/stop")
async def stop_live(body: LiveStopBody):
    """停止实盘"""
    return ApiResponse(
        success=False,
        error="本地量化实验室暂未接入实盘执行，无需停止实盘任务。",
        error_code="LOCAL_LIVE_NOT_IMPLEMENTED",
        data={"run_id": body.run_id},
    )


@router.get("/runs")
async def list_runs():
    """获取运行记录"""
    return ApiResponse(
        success=True,
        data={
            "runs": _local_runs,
            "can_run_backtest": True,
            "local_backtest_available": True,
            "execution_mode": "local",
            "source_status": "local",
            "degraded": False,
        },
    )


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """获取运行详情"""
    result = _local_run_details.get(run_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"运行记录不存在: {run_id}")
    return ApiResponse(success=True, data=result)
