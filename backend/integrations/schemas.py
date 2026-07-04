"""Integration 统一数据契约 / Schemas.

所有外部项目 (OpenBB / vectorBT / Qlib / TradingAgents / ...) 通过 adapter 接入后,
统一用本模块的 schema 与 AlphaScope 内部通信。这样证据链、回测对比、Agent 辩论、
报告生成都不用关心数据来自哪个具体项目。

合规: 所有 schema 均 **研究语义**, 不含订单流; NormalizedBacktestResult 只是历史
回测的归一化结构, NormalizedAgentOpinion 永远带 forbidden_live_order=True。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ============================================================
# 集成元数据 / 健康 / 能力
# ============================================================


class IntegrationCategory(str, Enum):
    """集成大类。"""

    DATA = "data"  # 数据源
    FACTOR = "factor"  # 因子 / ML
    BACKTEST = "backtest"  # 回测 / 仿真引擎
    AGENT = "agent"  # 外部 Agent 团队
    DOCUMENT = "document"  # 文档 / RAG
    UI = "ui"  # 可视化 / 监控扩展


class IntegrationMode(str, Enum):
    """插件运行模式 (见主路线图 §13.1)。"""

    NATIVE = "native"  # AlphaScope 内置模块
    PYTHON_ADAPTER = "python_adapter"  # pip optional dependency
    EXTERNAL_PROCESS = "external_process"  # 子进程 / Docker / CLI / REST


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"  # 可用但有问题 (如可选依赖缺失/降级)
    UNAVAILABLE = "unavailable"  # 依赖未安装 / 未配置
    DOWN = "down"  # healthcheck 抛错


class LicenseSafety(str, Enum):
    """许可证防火墙分级 (见主路线图 §12 / License Firewall)。"""

    SAFE = "safe"  # MIT/Apache/BSD, 可代码级融合
    COPILEFT_RISK = "copyleft_risk"  # GPL/AGPL, 仅外部进程/格式兼容, 禁止拷码
    NONCOMMERCIAL = "noncommercial"  # 非商业限制 (RQAlpha/ArcticDB/TradingAgents-CN 部分)
    PROPRIETARY = "proprietary"  # 商业/BSL, 仅研究或外部调用
    UNKNOWN = "unknown"


class CapabilitySpec(BaseModel):
    """adapter 暴露的一个能力。"""

    name: str = Field(description="能力标识, 如 get_market_data / run_backtest")
    description: str = Field(default="", description="人读说明")


class IntegrationMetadata(BaseModel):
    """adapter 的自描述, 注册时必填。"""

    name: str = Field(description="唯一标识, 如 vectorbt / openbb / qlib")
    category: IntegrationCategory
    mode: IntegrationMode = Field(default=IntegrationMode.PYTHON_ADAPTER)
    version: str = Field(default="0.0.0")
    display_name: str = Field(default="", description="UI 显示名")
    description: str = Field(default="")
    homepage: Optional[str] = Field(default=None, description="项目主页")
    package: Optional[str] = Field(default=None, description="pip 包名 (可选依赖)")
    capabilities: list[CapabilitySpec] = Field(default_factory=list)

    # 许可证防火墙
    license_name: Optional[str] = Field(default=None, description="如 MIT / AGPL-3.0 / BSL")
    license_safety: LicenseSafety = Field(default=LicenseSafety.UNKNOWN)
    code_copy_allowed: bool = Field(
        default=False,
        description="是否允许把项目源码拷进 AlphaScope 主仓 (AGPL/非商业/BSL 必须 False)",
    )

    # 交易边界 (Phase 0 第四道防线): 恒 False, 注册时断言
    allow_live_order: bool = Field(
        default=False,
        description="恒 False: 本集成不得提供实盘下单能力 (Phase 0 边界)。",
    )

    requires_evidence: bool = Field(
        default=False,
        description="Agent 类集成是否强制要求输出绑定证据。",
    )


class IntegrationHealth(BaseModel):
    """adapter 健康检查结果。"""

    name: str
    status: HealthStatus
    message: str = Field(default="")
    last_check: datetime = Field(default_factory=datetime.now)
    degraded_reasons: list[str] = Field(default_factory=list)


# ============================================================
# 归一化输出 (跨引擎/跨 Agent 团队)
# ============================================================


class BacktestAssumptions(BaseModel):
    """回测假设卡 (Backtest Assumption Card, 主路线图 §6 / 想法 #4)。

    把「看起来很好, 实际不可用」的回测陷阱显式暴露。所有 BacktestEngineAdapter
    必须填齐这些字段。
    """

    engine_name: str
    commission_rate: Optional[float] = Field(default=None, description="佣金率")
    stamp_duty_rate: Optional[float] = Field(default=None, description="印花税率(卖方)")
    slippage_rate: Optional[float] = Field(default=None, description="滑点率")
    execution_price: Optional[str] = Field(default=None, description="成交价口径, 如 'T+1 开盘价' / '收盘价'")
    settlement_rule: Optional[str] = Field(default=None, description="如 'T+1' / 'T+0'")
    price_limit_filter: Optional[bool] = Field(default=None, description="是否过滤涨跌停")
    suspension_handling: Optional[str] = Field(default=None, description="停牌处理")
    adj_method: Optional[str] = Field(default=None, description="复权方式: 前/后/不复权")
    future_function_check: bool = Field(default=True, description="是否做了防未来函数检查")
    data_source: Optional[str] = Field(default=None)
    note: Optional[str] = Field(default=None, description="自由说明")


class BacktestMetrics(BaseModel):
    """归一化绩效指标 (跨引擎统一口径)。"""

    annual_return: Optional[float] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    calmar: Optional[float] = None
    max_drawdown: Optional[float] = None
    volatility: Optional[float] = None
    win_rate: Optional[float] = None
    turnover: Optional[float] = None
    profit_factor: Optional[float] = None
    total_return: Optional[float] = None


class NormalizedBacktestResult(BaseModel):
    """任意回测引擎产出的归一化结果。

    无论来自 AlphaScope 原生引擎 / vectorBT / Backtrader / Lean / Freqtrade,
    进入 AlphaScope 后都变成这个结构, 供 BacktestHub 多引擎对比页使用。
    """

    engine_name: str
    strategy_id: Optional[str] = None
    universe: list[str] = Field(default_factory=list)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    initial_cash: Optional[float] = None
    benchmark: Optional[str] = None
    assumptions: BacktestAssumptions
    metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    trades: list[dict[str, Any]] = Field(default_factory=list)
    risk_events: list[dict[str, Any]] = Field(default_factory=list)
    evidence_links: list[str] = Field(default_factory=list)
    reproducibility_hash: Optional[str] = None
    # 研究语义自证
    research_only: bool = Field(default=True, description="恒 True: 回测结果不构成投资建议")


class NormalizedAgentOpinion(BaseModel):
    """外部 Agent 团队产出的归一化观点 (主路线图 §7)。

    TradingAgents / ai-hedge-fund / HKUDS AI-Trader 等返回的结论都先归一化成此结构,
    再喂给 AlphaScope 内部的 Critic / Risk Agent / Chairman。
    """

    agent_name: str
    role: str = Field(default="", description="角色: 基本面/技术/情绪/风险/...")
    thesis: str = Field(description="一句话核心观点")
    confidence: float = Field(ge=0, le=100, description="置信度 0-100")
    horizon: Optional[str] = Field(default=None, description="时间视野")
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    opposing_evidence_ids: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    suggested_action_type: str = Field(
        default="generate_report",
        description="研究语义: add_to_watchlist / paper_rebalance / generate_report / ...",
    )
    # 交易边界自证
    forbidden_live_order: bool = Field(
        default=True,
        description="恒 True: Agent 观点绝不直接变成订单, 必须经证据+风控+人工确认。",
    )
