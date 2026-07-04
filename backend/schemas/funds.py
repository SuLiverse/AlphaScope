"""基金与定投模块 Schema"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# 枚举
# ============================================================


class FundType(str, Enum):
    """基金类型"""

    STOCK = "stock"  # 股票型
    BOND = "bond"  # 债券型
    MIXED = "mixed"  # 混合型
    INDEX = "index"  # 指数型
    MONEY = "money"  # 货币型
    QDII = "qdii"  # QDII
    OTHER = "other"  # 其他


class DCAFrequency(str, Enum):
    """定投频率"""

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


# ============================================================
# 基金基本信息
# ============================================================


class FundInfo(BaseModel):
    """基金基本信息"""

    code: str = Field(description="基金代码")
    name: str = Field(description="基金名称")
    fund_type: FundType = Field(default=FundType.OTHER, description="基金类型")
    manager: str = Field(default="", description="基金经理")
    company: str = Field(default="", description="基金公司")
    inception_date: Optional[str] = Field(default=None, description="成立日期")
    nav: Optional[float] = Field(default=None, description="最新净值")
    nav_date: Optional[str] = Field(default=None, description="净值日期")
    total_assets: Optional[float] = Field(default=None, description="总资产（亿元）")


class FundNav(BaseModel):
    """基金净值"""

    date: str = Field(description="日期")
    nav: float = Field(description="单位净值")
    acc_nav: Optional[float] = Field(default=None, description="累计净值")
    daily_return: Optional[float] = Field(default=None, description="日收益率")


class FundMetrics(BaseModel):
    """基金指标"""

    code: str = Field(description="基金代码")
    name: str = Field(default="", description="基金名称")
    total_return_1y: Optional[float] = Field(default=None, description="近1年收益率")
    total_return_3y: Optional[float] = Field(default=None, description="近3年收益率")
    annual_return_3y: Optional[float] = Field(default=None, description="近3年年化收益率")
    sharpe_ratio: Optional[float] = Field(default=None, description="夏普比率")
    max_drawdown: Optional[float] = Field(default=None, description="最大回撤")
    volatility: Optional[float] = Field(default=None, description="波动率")
    calmar_ratio: Optional[float] = Field(default=None, description="卡玛比率")
    win_rate: Optional[float] = Field(default=None, description="胜率")


# ============================================================
# 定投
# ============================================================


class DCASimulationRequest(BaseModel):
    """定投模拟请求"""

    fund_code: str = Field(description="基金代码")
    amount: float = Field(description="每期金额")
    frequency: DCAFrequency = Field(default=DCAFrequency.MONTHLY, description="定投频率")
    start_date: str = Field(description="开始日期 YYYY-MM-DD")
    end_date: str = Field(description="结束日期 YYYY-MM-DD")


class DCASimulationResult(BaseModel):
    """定投模拟结果"""

    fund_code: str = Field(description="基金代码")
    total_invested: float = Field(description="总投入")
    final_value: float = Field(description="最终市值")
    total_return: float = Field(description="总收益率")
    annualized_return: float = Field(description="年化收益率")
    max_drawdown: float = Field(description="最大回撤")
    investment_count: int = Field(description="定投次数")
    avg_cost: float = Field(description="平均成本")
    records: list[dict[str, Any]] = Field(default_factory=list, description="定投记录")


class DCAPlan(BaseModel):
    """定投计划"""

    id: str = Field(description="计划ID")
    fund_code: str = Field(description="基金代码")
    fund_name: str = Field(default="", description="基金名称")
    amount: float = Field(description="每期金额")
    frequency: DCAFrequency = Field(description="定投频率")
    start_date: str = Field(description="开始日期")
    status: str = Field(default="active", description="状态")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")


# ============================================================
# 组合
# ============================================================


class PortfolioHolding(BaseModel):
    """组合持仓"""

    fund_code: str = Field(description="基金代码")
    fund_name: str = Field(default="", description="基金名称")
    weight: float = Field(description="目标权重")
    current_value: Optional[float] = Field(default=None, description="当前市值")
    actual_weight: Optional[float] = Field(default=None, description="实际权重")


class Portfolio(BaseModel):
    """基金组合"""

    id: str = Field(description="组合ID")
    name: str = Field(description="组合名称")
    description: str = Field(default="", description="组合描述")
    holdings: list[PortfolioHolding] = Field(default_factory=list, description="持仓列表")
    total_value: Optional[float] = Field(default=None, description="总市值")
    created_at: Optional[datetime] = Field(default=None, description="创建时间")
    updated_at: Optional[datetime] = Field(default=None, description="更新时间")


class RebalanceRequest(BaseModel):
    """再平衡请求"""

    portfolio_id: str = Field(description="组合ID")
    target_weights: dict[str, float] = Field(description="目标权重 {fund_code: weight}")


class RebalanceResult(BaseModel):
    """再平衡结果"""

    portfolio_id: str = Field(description="组合ID")
    trades: list[dict[str, Any]] = Field(default_factory=list, description="需要执行的交易")
    estimated_cost: float = Field(default=0.0, description="预估交易成本")
