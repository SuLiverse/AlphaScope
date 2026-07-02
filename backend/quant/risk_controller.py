"""Risk controller for local backtests.

Validates trades against risk rules before execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RiskConfig:
    """Risk control configuration."""

    max_position_pct: float = 30.0  # Max single position as % of equity
    max_total_exposure_pct: float = 80.0  # Max total exposure as % of equity
    stop_loss_pct: float = -10.0  # Stop loss trigger (%)
    max_drawdown_pct: float = -20.0  # Max portfolio drawdown (%)
    daily_loss_limit_pct: float = -5.0  # Daily loss circuit breaker (%)
    max_concentration_pct: float = 50.0  # Max concentration in one sector


@dataclass
class RiskCheckResult:
    """Result of a risk check."""

    allowed: bool
    reason: str
    rule: str = ""


class RiskController:
    """Risk controller with configurable rules."""

    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()
        self.violations: list[dict[str, Any]] = []

    def validate_buy(
        self,
        symbol: str,
        shares: int,
        price: float,
        equity: float,
        current_positions: dict[str, Any],
    ) -> RiskCheckResult:
        """Validate a buy order against all risk rules."""
        cost = shares * price

        # Check position size limit
        position_pct = (cost / equity * 100) if equity > 0 else 100
        if position_pct > self.config.max_position_pct:
            return RiskCheckResult(
                allowed=False,
                reason=f"单笔仓位 {position_pct:.1f}% 超过限制 {self.config.max_position_pct}%",
                rule="max_position_pct",
            )

        # Check total exposure
        current_exposure = sum(
            p.shares * p.current_price for p in current_positions.values()
        )
        new_exposure = current_exposure + cost
        exposure_pct = (new_exposure / equity * 100) if equity > 0 else 100
        if exposure_pct > self.config.max_total_exposure_pct:
            return RiskCheckResult(
                allowed=False,
                reason=f"总仓位 {exposure_pct:.1f}% 超过限制 {self.config.max_total_exposure_pct}%",
                rule="max_total_exposure_pct",
            )

        return RiskCheckResult(allowed=True, reason="通过")

    def validate_sell(
        self,
        symbol: str,
        shares: int,
        current_positions: dict[str, Any],
    ) -> RiskCheckResult:
        """Validate a sell order."""
        if symbol not in current_positions:
            return RiskCheckResult(
                allowed=False, reason=f"无持仓: {symbol}", rule="no_position"
            )

        pos = current_positions[symbol]
        if shares > pos.shares:
            return RiskCheckResult(
                allowed=False,
                reason=f"卖出数量 {shares} 超过持仓 {pos.shares}",
                rule="insufficient_shares",
            )

        return RiskCheckResult(allowed=True, reason="通过")

    def check_stop_loss(
        self,
        symbol: str,
        entry_price: float,
        current_price: float,
    ) -> RiskCheckResult:
        """Check if position hits stop loss."""
        if entry_price <= 0:
            # 入场价为 0/负是数据异常(如分红除权未处理), 不能除零; 标记为数据异常不崩。
            return RiskCheckResult(
                allowed=False,
                reason=f"止损检查失败: {symbol} 入场价 {entry_price} 异常(<=0), 无法计算盈亏",
                rule="invalid_entry_price",
            )
        pnl_pct = (current_price - entry_price) / entry_price * 100
        if pnl_pct <= self.config.stop_loss_pct:
            return RiskCheckResult(
                allowed=False,
                reason=f"止损触发: {symbol} 亏损 {pnl_pct:.1f}% 超过阈值 {self.config.stop_loss_pct}%",
                rule="stop_loss",
            )
        return RiskCheckResult(allowed=True, reason="通过")

    def check_drawdown(self, equity_curve: list[float]) -> RiskCheckResult:
        """Check if portfolio drawdown exceeds limit."""
        if len(equity_curve) < 2:
            return RiskCheckResult(allowed=True, reason="通过")

        peak = equity_curve[0]
        for val in equity_curve:
            if val > peak:
                peak = val

        current_dd = (equity_curve[-1] - peak) / peak * 100 if peak > 0 else 0
        if current_dd <= self.config.max_drawdown_pct:
            return RiskCheckResult(
                allowed=False,
                reason=f"最大回撤 {current_dd:.1f}% 超过阈值 {self.config.max_drawdown_pct}%",
                rule="max_drawdown",
            )
        return RiskCheckResult(allowed=True, reason="通过")

    def check_daily_loss(
        self, start_equity: float, current_equity: float
    ) -> RiskCheckResult:
        """Check daily loss circuit breaker."""
        if start_equity <= 0:
            return RiskCheckResult(allowed=True, reason="通过")

        daily_return = (current_equity - start_equity) / start_equity * 100
        if daily_return <= self.config.daily_loss_limit_pct:
            return RiskCheckResult(
                allowed=False,
                reason=f"日亏损 {daily_return:.1f}% 触发熔断 (阈值 {self.config.daily_loss_limit_pct}%)",
                rule="daily_loss_limit",
            )
        return RiskCheckResult(allowed=True, reason="通过")

    def record_violation(self, rule: str, details: str, timestamp: str = "") -> None:
        """Record a risk violation for audit."""
        self.violations.append(
            {
                "rule": rule,
                "details": details,
                "timestamp": timestamp,
            }
        )
