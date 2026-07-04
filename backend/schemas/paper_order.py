"""PaperOrder / 纸面订单 — 模拟撮合, 不触碰真实券商。

合规语义: 这是 **研究/沙盘** 产物, 绝不发送给任何真实 broker。
由 backend/integrations/paper_broker.py (Phase 2) 产出, 复用 quant/constraints.py
的 T+1 / 印花税 / 滑点 / 涨跌停模型, 与回测引擎同口径。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PaperOrderStatus(str, Enum):
    """纸面订单生命周期 (仅模拟)。"""

    PENDING = "pending"  # 已提交到纸面撮合器, 等待处理
    FILLED = "filled"  # 已模拟成交
    PARTIAL = "partial"  # 部分模拟成交
    REJECTED = "rejected"  # 被规则拒绝 (涨跌停/T+1/风控)
    CANCELLED = "cancelled"  # 人工取消


class PaperOrder(BaseModel):
    """纸面订单 — 模拟账户账本的一条记录。"""

    order_id: str = Field(description="纸面订单 ID (本地生成, 非真实券商订单号)")
    portfolio_id: str = Field(description="所属模拟组合 ID")
    symbol: str = Field(description="标的代码")
    side: str = Field(description="买入 / 卖出")
    shares: float = Field(ge=0, description="申请数量(股)")
    limit_price: Optional[float] = Field(default=None, description="限价; None=市价")

    # 模拟成交 (FILLED/PARTIAL 时填)
    fill_price: Optional[float] = Field(default=None, description="模拟成交价 (含滑点)")
    fill_shares: Optional[float] = Field(default=None, description="实际成交数量")
    commission: Optional[float] = Field(default=None, description="模拟佣金")
    stamp_duty: Optional[float] = Field(default=None, description="模拟印花税 (卖出)")

    status: PaperOrderStatus = Field(default=PaperOrderStatus.PENDING)
    reject_reason: Optional[str] = Field(default=None, description="REJECTED 时的规则理由")
    created_at: datetime = Field(default_factory=datetime.now)
    filled_at: Optional[datetime] = Field(default=None)

    # 合规自证: 永远为 True, 标记此对象绝不进入真实交易链路
    paper_only: bool = Field(
        default=True,
        description="恒为 True: 本订单仅在纸面撮合器内成交, 不发送真实券商。",
    )

    def assert_paper_only(self) -> None:
        """守卫: 防止未来误把 PaperOrder 喂给真实 broker 适配器。"""
        if not self.paper_only:
            raise ValueError("PaperOrder.paper_only 必须为 True; 纸面订单不可进入真实交易链路。")
