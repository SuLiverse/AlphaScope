"""Provider 基类 - 所有数据源插件必须继承此类"""

from __future__ import annotations

import logging
import time
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ProviderStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ProviderHealth:
    """数据源健康状态"""

    status: ProviderStatus = ProviderStatus.HEALTHY
    last_check: float = 0.0
    last_success: float = 0.0
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0
    error_message: str = ""


class BaseProvider(ABC):
    """数据源 Provider 基类

    所有数据源插件必须继承此类并实现所需方法。
    子类应设置以下类属性:
        name: str           - Provider 名称
        markets: list[str]  - 支持的市场 (CN/HK/US)
        data_types: list[str] - 支持的数据类型 (news/report/announcement/price/fundamental)
        priority: int       - 默认优先级 (0-100, 越高越优先)
        license_level: str  - 数据许可级别

    v0.12 enhanced fields:
        data_class: str     - 数据类别 (price/fundamental/sentiment/macro/event/alternative)
        freshness: str      - 数据时效 (realtime/intraday/daily/weekly/monthly)
        cost_tier: str      - 成本层级 (free/freemium/paid)
        rate_limit: dict    - 速率限制 {"per_minute": N, "per_day": N}
        requires_key: bool  - 是否需要 API Key
    """

    name: str = "base"
    markets: list[str] = field(default_factory=list)
    data_types: list[str] = field(default_factory=list)
    priority: int = 50
    license_level: str = "research_only"
    # v0.12: Enhanced provider metadata
    data_class: str = "fundamental"  # price | fundamental | sentiment | macro | event | alternative
    freshness: str = "daily"  # realtime | intraday | daily | weekly | monthly
    cost_tier: str = "free"  # free | freemium | paid
    rate_limit: dict = field(default_factory=lambda: {"per_minute": 60, "per_day": None})
    requires_key: bool = False

    @classmethod
    def is_available(cls) -> bool:
        """检查此 Provider 的依赖是否满足

        子类可覆盖, 检查 API Key 或可选包是否可用。
        默认返回 True (始终可用)。
        """
        return True

    def __init__(self) -> None:
        self._health = ProviderHealth()
        self._logger = logging.getLogger(f"provider.{self.name}")
        # v1.9.4: 类级 field(default_factory=...) 默认值在非 dataclass 上不会自动实例化,
        # 这里把未被子类覆盖的 list/dict 默认值实例化, 避免 capability()/health 遇到 Field 对象。
        from dataclasses import Field

        if isinstance(self.markets, Field):
            self.markets = list(self.markets.default_factory())  # type: ignore[misc]
        if isinstance(self.data_types, Field):
            self.data_types = list(self.data_types.default_factory())  # type: ignore[misc]
        if isinstance(self.rate_limit, Field):
            rl = self.rate_limit.default_factory
            self.rate_limit = rl() if callable(rl) else {}  # type: ignore[assignment]

    @property
    def health(self) -> ProviderHealth:
        return self._health

    def _record_success(self, latency_ms: float) -> None:
        """记录一次成功调用"""
        self._health.last_success = time.time()
        self._health.last_check = time.time()
        self._health.consecutive_failures = 0
        self._health.status = ProviderStatus.HEALTHY
        self._health.error_message = ""
        # 指数移动平均
        alpha = 0.3
        self._health.avg_latency_ms = alpha * latency_ms + (1 - alpha) * self._health.avg_latency_ms

    def _record_failure(self, error: str) -> None:
        """记录一次失败调用"""
        self._health.last_check = time.time()
        self._health.consecutive_failures += 1
        self._health.error_message = error
        if self._health.consecutive_failures >= 3:
            self._health.status = ProviderStatus.UNHEALTHY
        else:
            self._health.status = ProviderStatus.DEGRADED
        self._logger.warning(f"[{self.name}] 调用失败: {error}")

    def _timed_call(self, fn, *args, **kwargs):
        """包装调用, 自动计时和记录健康状态"""
        start = time.time()
        try:
            result = fn(*args, **kwargs)
            latency = (time.time() - start) * 1000
            self._record_success(latency)
            return result
        except Exception as e:
            self._record_failure(str(e))
            raise

    def health_check(self) -> dict:
        """健康检查, 返回 Provider 状态信息"""
        return {
            "name": self.name,
            "status": self._health.status.value,
            "last_success": self._health.last_success,
            "consecutive_failures": self._health.consecutive_failures,
            "avg_latency_ms": round(self._health.avg_latency_ms, 1),
            "error": self._health.error_message,
        }

    def capability(self) -> dict:
        """返回标准化的能力描述(v1.9.4, deep-research ProviderCapability)。

        统一所有数据源(AkShare/Tushare/CSV/Demo…)的能力表达, 对标 tickflow
        tiers.yaml 的「能力驱动」思想, 供前端用同一套 UI 展示与筛选。
        纯读取类属性, 不触发网络。
        """
        rl = self.rate_limit if isinstance(self.rate_limit, dict) else {}
        return {
            "name": self.name,
            "markets": list(self.markets or []),
            "data_types": list(self.data_types or []),
            "data_class": self.data_class,
            "freshness": self.freshness,  # realtime|intraday|daily|weekly|monthly
            "latency_tier": self._latency_tier(),
            "cost_tier": self.cost_tier,  # free|freemium|paid
            "rate_limit": {
                "per_minute": rl.get("per_minute"),
                "per_day": rl.get("per_day"),
            },
            "trust_level": self.license_level,
            "priority": self.priority,
            "requires_key": self.requires_key,
            "available": self.is_available(),
            "degradable": self.priority < 100,  # 非最高优先级源可作降级备用
        }

    def _latency_tier(self) -> str:
        """按 freshness 推断延迟等级(展示用)。"""
        return {
            "realtime": "realtime",
            "intraday": "low",
            "daily": "medium",
            "weekly": "high",
            "monthly": "high",
        }.get(self.freshness, "medium")

    # ---- 数据获取接口 (子类按需实现) ----

    def get_news(self, query: dict, **kwargs) -> list[dict]:
        """获取新闻数据"""
        raise NotImplementedError(f"{self.name} 不支持 get_news")

    def get_reports(self, query: dict, **kwargs) -> list[dict]:
        """获取研报数据"""
        raise NotImplementedError(f"{self.name} 不支持 get_reports")

    def get_announcements(self, query: dict, **kwargs) -> list[dict]:
        """获取公告数据"""
        raise NotImplementedError(f"{self.name} 不支持 get_announcements")

    def get_prices(self, query: dict, **kwargs) -> list[dict]:
        """获取行情数据"""
        raise NotImplementedError(f"{self.name} 不支持 get_prices")

    def get_fundamentals(self, query: dict, **kwargs) -> dict:
        """获取基本面数据"""
        raise NotImplementedError(f"{self.name} 不支持 get_fundamentals")

    def get_fund_flow(self, query: dict, **kwargs) -> list[dict]:
        """获取资金流数据"""
        raise NotImplementedError(f"{self.name} 不支持 get_fund_flow")

    def get_dragon_tiger(self, query: dict, **kwargs) -> dict:
        """获取龙虎榜 (机构 vs 游资席位) 数据"""
        raise NotImplementedError(f"{self.name} 不支持 get_dragon_tiger")
