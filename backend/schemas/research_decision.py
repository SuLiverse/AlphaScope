"""ResearchDecision / 研究决策 — 下单前的最终决策留痕。

描述「AlphaScope 建议你考虑这样做, 以及为什么」, 是 Agent 辩论 + 证据 + 风控 +
回测汇聚后的 **可审计决策对象**。它是 ManualReviewTicket 与研究报告之间的桥层:
决策可以被导出为人工确认单, 也可以被研究报告引用。

合规: ResearchDecision 只表达研究观点, 不产生订单。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class DecisionVerdict(str, Enum):
    """研究决策结论 (确定性评级映射)。"""

    STRONG_BUY = "强烈推荐"
    BUY = "推荐"
    NEUTRAL = "中性"
    CAUTIOUS = "谨慎"
    AVOID = "回避"
    RISK_VETOED = "风控否决"


class ResearchDecision(BaseModel):
    """单次研究任务对单个标的/主题的最终决策留痕。"""

    decision_id: str = Field(description="决策 ID (可复现 hash 衍生)")
    symbol: str = Field(description="标的代码")
    name: Optional[str] = Field(default=None, description="标的名称")

    # 结论 (与 backend.runtime.rating 对齐)
    verdict: DecisionVerdict = Field(description="五档评级结论")
    score: float = Field(ge=0, le=100, description="确定性评分 0-100")
    rating_breakdown: dict[str, Any] = Field(default_factory=dict, description="评分可审计明细")
    confidence: float = Field(ge=0, le=100, description="平均置信度")

    # 推理链
    thesis: str = Field(description="一句话核心结论")
    supporting_evidence_ids: list[str] = Field(default_factory=list, description="支持证据")
    opposing_evidence_ids: list[str] = Field(default_factory=list, description="反方证据")
    risk_flags: list[str] = Field(default_factory=list, description="风险提示")
    backtest_refs: list[str] = Field(default_factory=list, description="回测参考")

    # 建议 (研究语义, 非下单指令)
    suggested_next_step: Optional[str] = Field(
        default=None,
        description="建议下一步: 加观察池 / 生成研报 / 出人工确认单 / 谨慎观望",
    )

    created_at: datetime = Field(default_factory=datetime.now)

    # 合规自证
    research_only: bool = Field(
        default=True,
        description="恒为 True: 研究决策不构成投资建议, 不触发下单。",
    )
