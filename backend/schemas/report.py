"""标准化研报数据模型"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ResearchReport(BaseModel):
    """统一研报条目模型"""

    id: str = Field(default="", description="唯一ID")
    title: str = Field(description="研报标题")
    report_type: str = Field(
        default="company",
        description="研报类型: company/industry/macro/strategy",
    )
    institution: str = Field(default="", description="发布机构/券商")
    authors: list[str] = Field(default_factory=list, description="作者")
    symbols: list[str] = Field(default_factory=list, description="关联股票代码")
    industry: str = Field(default="", description="关联行业")
    rating: str = Field(default="", description="评级: 买入/增持/中性/减持/卖出")
    target_price: Optional[float] = Field(default=None, description="目标价")
    summary: str = Field(default="", description="摘要")
    pdf_url: str = Field(default="", description="PDF下载链接")
    published_at: Optional[datetime] = Field(default=None, description="发布日期")
    fetched_at: datetime = Field(default_factory=datetime.now, description="抓取时间")
    source: str = Field(description="数据来源: tushare/eastmoney/akshare")
    source_url: str = Field(default="", description="原始链接")
    pdf_hash: str = Field(default="", description="PDF文件SHA256哈希")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="可信度")
    license_level: str = Field(default="restricted", description="许可级别")

    def model_post_init(self, __context) -> None:
        if not self.id:
            raw = f"{self.source}_{self.title}_{self.institution}_{self.published_at}"
            self.id = f"report_{self.source}_{hashlib.md5(raw.encode()).hexdigest()[:12]}"


class ReportQuery(BaseModel):
    """研报查询参数"""

    symbols: list[str] = Field(default_factory=list)
    industry: str = ""
    report_type: str = ""
    institution: str = ""
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)
