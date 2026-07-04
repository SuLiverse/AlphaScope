"""ManualReviewTicket / 人工确认单 — 「接近交易」输出的统一收口。

AlphaScope 不做实盘自动下单, 因此所有「再平衡建议 / 调仓想法 / Agent 共识」
最终都汇成一张 *人工确认单*, 由用户自行决定是否在自己的券商端执行。
本对象 **只导出** (CSV/Markdown/PDF), 不触发任何下单动作。
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    """人工确认单状态。"""

    DRAFT = "draft"  # 系统生成草案
    PENDING_REVIEW = "pending_review"  # 待人工复核
    APPROVED = "approved"  # 用户已确认 (仅在 AlphaScope 内标记, 不等于已下单)
    REJECTED = "rejected"  # 用户否决
    EXECUTED_EXTERNALLY = "executed_externally"  # 用户自行在券商端执行后回填


class TicketLineAction(str, Enum):
    """建议动作类型 (研究语义, 非下单指令)。"""

    OPEN = "open"  # 建议新建仓位
    ADD = "add"  # 建议加仓
    REDUCE = "reduce"  # 建议减仓
    CLOSE = "close"  # 建议清仓
    HOLD = "hold"  # 维持
    WATCH = "watch"  # 加入观察池


class TicketLine(BaseModel):
    """人工确认单中的单标的行。"""

    symbol: str = Field(description="标的代码")
    name: Optional[str] = Field(default=None, description="标的名称")
    action: TicketLineAction = Field(description="建议动作 (研究语义)")
    target_weight: Optional[float] = Field(default=None, description="目标权重 %")
    current_weight: Optional[float] = Field(default=None, description="当前权重 %")
    rationale: str = Field(description="调仓理由 (附证据链/Agent 共识)")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑证据 ID")
    risk_flags: list[str] = Field(default_factory=list, description="相关风险提示")
    confidence: Optional[float] = Field(default=None, ge=0, le=100, description="置信度")


class ManualReviewTicket(BaseModel):
    """人工确认单 / 再平衡草案。

    这是 AlphaScope 对「交易」的最终合法输出形态: 一份可导出、可留痕、
    需人工确认的研究文档, 而非订单流。
    """

    ticket_id: str = Field(description="单据 ID")
    portfolio_id: Optional[str] = Field(default=None, description="关联模拟组合")
    trade_date: date = Field(description="拟调仓日期")
    title: str = Field(default="再平衡草案", description="单据标题")
    summary: str = Field(default="", description="整体说明 / Agent 主席结论")
    lines: list[TicketLine] = Field(default_factory=list, description="逐标的建议")

    # 证据与风险
    evidence_ids: list[str] = Field(default_factory=list, description="全局证据引用")
    backtest_refs: list[str] = Field(default_factory=list, description="回测参考 ID")
    risk_warnings: list[str] = Field(default_factory=list, description="风险提示")
    agent_disagreement: Optional[str] = Field(default=None, description="Agent 分歧摘要")

    # 流程
    status: TicketStatus = Field(default=TicketStatus.DRAFT)
    requires_human_review: bool = Field(default=True, description="是否强制人工复核")
    created_at: datetime = Field(default_factory=datetime.now)
    reviewed_at: Optional[datetime] = Field(default=None)

    # 合规自证
    manual_only: bool = Field(
        default=True,
        description="恒为 True: 本单据仅用于人工确认, 不触发自动下单。",
    )

    def assert_manual_only(self) -> None:
        """守卫: ManualReviewTicket 永远是研究产物, 不应进入任何 broker 调用。"""
        if not self.manual_only:
            raise ValueError("ManualReviewTicket.manual_only 必须为 True; 人工确认单不可自动执行。")
