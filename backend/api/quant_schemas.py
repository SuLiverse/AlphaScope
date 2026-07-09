"""量化 API 请求体模型（从 quant.py 拆出，压低路由模块体积）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PreviewOptIn(BaseModel):
    """无真实行情时是否允许合成样例（默认关，须显式 opt-in）。"""

    allow_preview_data: bool = Field(
        default=False,
        description="无真实行情时是否允许使用本地合成样例（仅演示，须显式 opt-in）",
    )


class BacktestRequestBody(PreviewOptIn):
    """回测请求体"""

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数覆盖")


class WalkForwardRequestBody(PreviewOptIn):
    """走查(walk-forward)样本外稳健性分析请求体。"""

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数覆盖")
    n_splits: int = Field(default=5, description="样本外窗口数(2-12, 数据不足时自动收敛)")
    scheme: str = Field(default="anchored", description="切分方案: anchored(锚定) | rolling(滚动)")


class ChipDistributionRequestBody(PreviewOptIn):
    """筹码(成本)分布请求体。"""

    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    price_levels: int = Field(default=100, description="价位离散桶数(20-400)")


class PatternsRequestBody(PreviewOptIn):
    """K 线形态识别请求体。"""

    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    lookback: int = Field(default=60, description="蜡烛形态扫描窗口(最近 N 根)")


class StrategyCompareRequestBody(PreviewOptIn):
    """策略横向对比请求体。"""

    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    rank_by: str = Field(
        default="sharpe_ratio",
        description="排名指标: sharpe_ratio|total_return|calmar_ratio",
    )


class ExperimentCompareBody(BaseModel):
    """实验横向对比请求体。"""

    run_ids: list[str] = Field(default_factory=list, description="要对比的实验 run_id 列表")


class EvolveRequestBody(PreviewOptIn):
    """遗传算法策略参数寻优请求体。"""

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    params: dict[str, Any] = Field(default_factory=dict, description="固定基底参数(不被进化)")
    param_space: dict[str, Any] = Field(default_factory=dict, description="可选显式搜索空间;缺省由默认参数推断")
    population_size: int = Field(default=16, description="种群规模(4-40, 自动夹紧)")
    generations: int = Field(default=8, description="进化代数(1-20, 受算力预算约束)")
    fitness_metric: str = Field(
        default="sharpe_ratio",
        description="适应度指标: sharpe_ratio|calmar_ratio|sortino_ratio|total_return|annualized_return|profit_factor|win_rate",
    )
    seed: int = Field(default=42, description="随机种子(决定可复现性)")


class TdxCompileRequestBody(BaseModel):
    """通达信公式编译(语法检查/预览)请求体。"""

    formula: str = Field(description="通达信(TDX)公式源码")


class LiveStartBody(BaseModel):
    """实盘启动请求体"""

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数覆盖")
    capital: float = Field(default=1000000.0, description="投入资金")


class LiveStopBody(BaseModel):
    """实盘停止请求体"""

    run_id: str = Field(description="运行ID")


class StockPoolExportRequest(BaseModel):
    """Stock pool CSV export request."""

    text: str = Field(description="Stock pool text containing symbols")
