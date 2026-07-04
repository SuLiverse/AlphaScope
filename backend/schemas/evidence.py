"""证据链数据模型 - 支撑证据驱动型研究"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """单条证据"""

    id: str = Field(description="证据唯一ID")
    evidence_type: str = Field(
        description="证据类型: news/report/announcement/price/fund_flow/fundamental",
    )
    title: str = Field(description="证据标题")
    source: str = Field(description="数据来源")
    source_url: str = Field(default="", description="原始链接")
    published_at: Optional[datetime] = Field(default=None, description="发布时间")
    content_summary: str = Field(default="", description="内容摘要")
    symbols: list[str] = Field(default_factory=list, description="关联股票")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0, description="可信度")
    relevance: float = Field(default=0.5, ge=0.0, le=1.0, description="相关度")


class EvidenceBundle(BaseModel):
    """证据集合 - 用于支撑某个投资观点"""

    claim: str = Field(description="投资观点/结论")
    evidence_ids: list[str] = Field(default_factory=list, description="证据ID列表")
    evidence_items: list[EvidenceItem] = Field(default_factory=list, description="证据详情")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="综合置信度")
    risk_note: str = Field(default="", description="风险提示")
    source_count: int = Field(default=0, description="来源数量")
    official_count: int = Field(default=0, description="官方来源数量")
    created_at: datetime = Field(default_factory=datetime.now)


class AgentReport(BaseModel):
    """Agent分析报告"""

    id: str = Field(default="", description="报告ID")
    symbol: str = Field(description="股票代码")
    agent_role: str = Field(description="Agent角色")
    decision: str = Field(default="", description="决策: buy/sell/hold")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    summary: str = Field(default="", description="分析摘要")
    evidence_bundles: list[EvidenceBundle] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    model_used: str = Field(default="", description="使用的模型")
