"""数据源统一返回模型

为所有 Provider 提供标准化的返回格式，确保每条数据都有来源溯源。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class DataSourceResult(BaseModel):
    """数据源统一返回格式

    所有 Provider 的 get_news/get_reports/get_announcements 等方法
    应返回此格式的列表，确保每条数据都有完整的来源溯源。
    """

    id: str = Field(default="", description="数据唯一ID")
    title: str = Field(default="", description="标题")
    content: str = Field(default="", description="内容/摘要")
    source: str = Field(description="数据来源标识，如 akshare/cls/eastmoney/sec")
    source_name: str = Field(default="", description="来源显示名称，如 财联社/东方财富")
    source_url: str = Field(default="", description="原始链接")
    published_at: Optional[datetime] = Field(default=None, description="发布时间")
    fetched_at: datetime = Field(default_factory=datetime.now, description="抓取时间")
    data_type: str = Field(default="news", description="数据类型: news/report/announcement/price/fund_flow")
    symbols: list[str] = Field(default_factory=list, description="关联股票代码")
    confidence: float = Field(default=0.7, ge=0.0, le=1.0, description="数据可信度")
    metadata: dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class ProviderHealthStatus(BaseModel):
    """Provider 健康状态"""

    name: str = Field(description="Provider 名称")
    status: str = Field(description="状态: healthy/degraded/unhealthy/unknown")
    consecutive_failures: int = Field(default=0, description="连续失败次数")
    avg_latency_ms: float = Field(default=0.0, description="平均延迟(ms)")
    last_error: str = Field(default="", description="最近错误信息")
    last_success: Optional[datetime] = Field(default=None, description="最近成功时间")
    data_types: list[str] = Field(default_factory=list, description="支持的数据类型")
    markets: list[str] = Field(default_factory=list, description="支持的市场")


class DataSourceStatus(BaseModel):
    """数据源整体状态"""

    total_providers: int = Field(default=0, description="总 Provider 数")
    healthy: int = Field(default=0, description="健康数")
    degraded: int = Field(default=0, description="降级数")
    unhealthy: int = Field(default=0, description="不健康数")
    providers: list[ProviderHealthStatus] = Field(default_factory=list, description="各 Provider 状态")
