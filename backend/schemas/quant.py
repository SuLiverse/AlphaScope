"""量化模块 Schema — 本地回测引擎数据模型"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# 枚举
# ============================================================


class StrategyStatus(str, Enum):
    """策略状态"""

    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


class RunStatus(str, Enum):
    """运行状态"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OrderSide(str, Enum):
    """买卖方向"""

    BUY = "buy"
    SELL = "sell"


# ============================================================
# 策略
# ============================================================


class StrategyParam(BaseModel):
    """策略参数定义"""

    name: str = Field(description="参数名")
    type: str = Field(default="float", description="参数类型")
    default: Any = Field(default=None, description="默认值")
    min: Optional[float] = Field(default=None, description="最小值")
    max: Optional[float] = Field(default=None, description="最大值")
    description: str = Field(default="", description="参数说明")


class StrategyInfo(BaseModel):
    """策略信息"""

    id: str = Field(description="策略ID")
    name: str = Field(description="策略名称")
    description: str = Field(default="", description="策略描述")
    status: StrategyStatus = Field(default=StrategyStatus.ACTIVE, description="策略状态")
    params: list[StrategyParam] = Field(default_factory=list, description="策略参数")
    version: str = Field(default="1.0", description="策略版本")


# ============================================================
# 回测
# ============================================================


class BacktestRequest(BaseModel):
    """回测请求"""

    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")
    initial_capital: float = Field(default=1000000.0, description="初始资金")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数覆盖")


class BacktestMetrics(BaseModel):
    """回测指标"""

    total_return: float = Field(default=0.0, description="总收益率")
    annual_return: float = Field(default=0.0, description="年化收益率")
    sharpe_ratio: float = Field(default=0.0, description="夏普比率")
    max_drawdown: float = Field(default=0.0, description="最大回撤")
    win_rate: float = Field(default=0.0, description="胜率")
    trade_count: int = Field(default=0, description="交易次数")
    profit_factor: float = Field(default=0.0, description="盈亏比")
    volatility: float = Field(default=0.0, description="波动率")


class BacktestResult(BaseModel):
    """回测结果"""

    run_id: str = Field(description="运行ID")
    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    status: RunStatus = Field(description="运行状态")
    metrics: Optional[BacktestMetrics] = Field(default=None, description="回测指标")
    equity_curve: list[dict[str, Any]] = Field(default_factory=list, description="权益曲线")
    trades: list[dict[str, Any]] = Field(default_factory=list, description="交易记录")
    error: Optional[str] = Field(default=None, description="错误信息")
    started_at: Optional[datetime] = Field(default=None, description="开始时间")
    finished_at: Optional[datetime] = Field(default=None, description="完成时间")


# ============================================================
# 运行记录
# ============================================================


class RunRecord(BaseModel):
    """运行记录摘要"""

    run_id: str = Field(description="运行ID")
    strategy_id: str = Field(description="策略ID")
    symbol: str = Field(description="标的代码")
    mode: str = Field(default="backtest", description="模式: backtest/live")
    status: RunStatus = Field(description="运行状态")
    total_return: Optional[float] = Field(default=None, description="总收益率")
    started_at: Optional[datetime] = Field(default=None, description="开始时间")
    finished_at: Optional[datetime] = Field(default=None, description="完成时间")


# ============================================================
# 本地量化能力状态
# ============================================================


class QuantEngineStatus(BaseModel):
    """本地量化能力状态"""

    connected: bool = Field(description="是否连接")
    version: Optional[str] = Field(default=None, description="引擎版本")
    strategy_count: int = Field(default=0, description="可用策略数")
    active_runs: int = Field(default=0, description="活跃运行数")
    error: Optional[str] = Field(default=None, description="错误信息")
