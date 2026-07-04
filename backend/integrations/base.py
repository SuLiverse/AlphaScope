"""Integration Adapter 基类 / 协议定义.

四类 adapter (主路线图 §13 / Phase 1):
- DataAdapter            : 行情/财务/新闻/宏观数据
- FactorAdapter          : 因子计算 / ML 模型实验
- BacktestEngineAdapter  : 回测 / 仿真引擎
- AgentTeamAdapter       : 外部 AI 投研团队

每个 adapter 必须:
1. 提供 ``metadata()`` 自描述 (含许可证/能力/allow_live_order=False)。
2. 实现 ``healthcheck()``。可选依赖缺失应返回 DEGRADED/UNAVAILABLE, 不抛错。
3. 实现 ``is_available()`` 依赖探测。
4. 子类实现各自的 ``run()`` / 数据获取方法。

设计原则:
- 默认失败安全, 不抛破坏性异常。
- 严格遵守交易边界 (Phase 0): 任何 adapter 都不得暴露实盘下单能力。
- 许可证防火墙: AGPL/非商业/BSL 的 adapter 必须 mode=EXTERNAL_PROCESS,
  且 code_copy_allowed=False。
"""

from __future__ import annotations

import abc
from typing import Any

from backend.integrations.schemas import (
    BacktestAssumptions,
    IntegrationCategory,
    IntegrationHealth,
    IntegrationMetadata,
    NormalizedAgentOpinion,
    NormalizedBacktestResult,
    HealthStatus,
)


class BaseAdapter(abc.ABC):
    """所有 adapter 的抽象基类。"""

    #: 子类必须覆盖: 类级元数据模板 (name/category 至少)
    NAME: str = ""
    CATEGORY: IntegrationCategory = IntegrationCategory.DATA

    # ---------- 元数据 ----------
    def metadata(self) -> IntegrationMetadata:
        """返回 adapter 元数据。子类一般覆盖 ``_metadata()`` 而非本方法。"""
        meta = self._metadata()
        # 交易边界硬约束 (Phase 0 第四道防线): 双保险
        if meta.allow_live_order is not False:
            raise ValueError(f"Integration {meta.name!r} 违反交易边界: allow_live_order 必须 False")
        return meta

    def _metadata(self) -> IntegrationMetadata:
        """子类覆盖此方法填充完整元数据。默认用类属性 + 空字段。"""
        return IntegrationMetadata(
            name=self.NAME,
            category=self.CATEGORY,
            display_name=self.NAME,
        )

    # ---------- 健康与依赖 ----------
    @abc.abstractmethod
    def healthcheck(self) -> IntegrationHealth:
        """探测 adapter 当前是否可用。可选依赖缺失应返回 DEGRADED, 不抛。"""

    def is_available(self) -> bool:
        """依赖是否就绪 (True = healthcheck 通过且可 run)。"""
        return self.healthcheck().status in (
            HealthStatus.HEALTHY,
            HealthStatus.DEGRADED,
        )

    # ---------- 证据钩子 ----------
    def create_evidence(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """把 adapter 的输出包装成证据条目 (供 EvidenceHub)。子类可覆盖。"""
        meta = self.metadata()
        return {
            "source_type": meta.category.value,
            "source_name": meta.name,
            "payload": payload or {},
        }


# ============================================================
# 四类专用 adapter 抽象基类
# ============================================================


class DataAdapter(BaseAdapter):
    """数据源 adapter: 行情 / 财务 / 新闻 / 宏观。"""

    CATEGORY = IntegrationCategory.DATA

    def get_ohlcv(self, symbol: str, start: str, end: str, **kw: Any) -> list[dict[str, Any]]:
        raise NotImplementedError

    def healthcheck(self) -> IntegrationHealth:  # pragma: no cover - abstract shim
        raise NotImplementedError


class FactorAdapter(BaseAdapter):
    """因子 / ML 实验 adapter (如 Qlib / Panda-factor)。"""

    CATEGORY = IntegrationCategory.FACTOR

    def compute_factors(self, symbols: list[str], **kw: Any) -> dict[str, Any]:
        raise NotImplementedError

    def healthcheck(self) -> IntegrationHealth:  # pragma: no cover
        raise NotImplementedError


class BacktestEngineAdapter(BaseAdapter):
    """回测引擎 adapter (如 vectorBT / Backtrader / Lean / Freqtrade)。"""

    CATEGORY = IntegrationCategory.BACKTEST

    def run_backtest(
        self,
        strategy_id: str,
        symbols: list[str],
        start: str,
        end: str,
        assumptions: BacktestAssumptions | None = None,
        **kw: Any,
    ) -> NormalizedBacktestResult:
        """运行回测, 返回归一化结果。子类必须实现。"""
        raise NotImplementedError

    def healthcheck(self) -> IntegrationHealth:  # pragma: no cover
        raise NotImplementedError


class AgentTeamAdapter(BaseAdapter):
    """外部 Agent 团队 adapter (如 TradingAgents / ai-hedge-fund)。"""

    CATEGORY = IntegrationCategory.AGENT

    def analyze(self, symbols: list[str], **kw: Any) -> list[NormalizedAgentOpinion]:
        """对给定标的/主题返回一组归一化 Agent 观点。子类必须实现。"""
        raise NotImplementedError

    def healthcheck(self) -> IntegrationHealth:  # pragma: no cover
        raise NotImplementedError
