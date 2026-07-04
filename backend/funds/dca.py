"""定投模拟引擎 — 基于历史净值的真实模拟"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.schemas.funds import DCAFrequency, DCASimulationResult


def _generate_dates(start_date: str, end_date: str, frequency: DCAFrequency) -> list[str]:
    """生成定投日期序列"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    freq_days = {
        DCAFrequency.WEEKLY: 7,
        DCAFrequency.BIWEEKLY: 14,
        DCAFrequency.MONTHLY: 30,
        DCAFrequency.QUARTERLY: 90,
    }
    delta = freq_days.get(frequency, 30)

    dates = []
    current = start
    while current <= end:
        dates.append(current.strftime("%Y-%m-%d"))
        current = __import__("datetime").timedelta(days=delta)
        current = start + __import__("datetime").timedelta(days=delta * (len(dates)))
    return dates


def _find_nearest_nav(nav_records: list[dict[str, Any]], target_date: str) -> float | None:
    """找到最接近目标日期的净值"""
    if not nav_records:
        return None

    # 先尝试精确匹配
    for r in nav_records:
        if r["date"] == target_date:
            return r["nav"]

    # 找最近的（向前找）
    best = None
    best_diff = float("inf")
    for r in nav_records:
        diff = abs((datetime.strptime(r["date"], "%Y-%m-%d") - datetime.strptime(target_date, "%Y-%m-%d")).days)
        if diff < best_diff:
            best_diff = diff
            best = r["nav"]
    return best


class DCASimulator:
    """定投模拟器

    基于历史净值序列，模拟定期定额投资的收益情况。
    不使用随机数，所有结果基于真实历史数据。
    """

    def simulate(
        self,
        nav_records: list[dict[str, Any]],
        amount: float,
        frequency: DCAFrequency,
        start_date: str,
        end_date: str,
    ) -> DCASimulationResult:
        """执行定投模拟

        Args:
            nav_records: 历史净值记录 [{"date": "2024-01-01", "nav": 1.0}, ...]
            amount: 每期定投金额
            frequency: 定投频率
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DCASimulationResult 模拟结果
        """
        if not nav_records or amount <= 0:
            return DCASimulationResult(
                fund_code="",
                total_invested=0,
                final_value=0,
                total_return=0,
                annualized_return=0,
                max_drawdown=0,
                investment_count=0,
                avg_cost=0,
                records=[],
            )

        # 生成定投日期
        dates = _generate_dates(start_date, end_date, frequency)

        # 模拟定投
        total_shares = 0.0
        total_invested = 0.0
        records = []

        for date in dates:
            nav = _find_nearest_nav(nav_records, date)
            if nav is None or nav <= 0:
                continue

            shares = amount / nav
            total_shares += shares
            total_invested += amount

            records.append(
                {
                    "date": date,
                    "nav": round(nav, 4),
                    "amount": amount,
                    "shares": round(shares, 4),
                    "total_shares": round(total_shares, 4),
                    "total_invested": round(total_invested, 2),
                }
            )

        if not records or total_shares <= 0:
            return DCASimulationResult(
                fund_code="",
                total_invested=0,
                final_value=0,
                total_return=0,
                annualized_return=0,
                max_drawdown=0,
                investment_count=0,
                avg_cost=0,
                records=[],
            )

        # 计算最终价值
        final_nav = nav_records[-1]["nav"]
        final_value = total_shares * final_nav
        total_return = (final_value / total_invested - 1) if total_invested > 0 else 0

        # 计算年化收益
        start_dt = datetime.strptime(records[0]["date"], "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        days = (end_dt - start_dt).days
        annualized_return = (1 + total_return) ** (365.0 / days) - 1 if days > 0 else 0

        # 计算最大回撤（基于持仓市值）
        equity_curve = []
        cumulative_shares = 0.0
        for rec in records:
            cumulative_shares += rec["shares"]
            equity = cumulative_shares * rec["nav"]
            equity_curve.append(equity)

        max_dd = 0.0
        peak = equity_curve[0] if equity_curve else 0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                if dd > max_dd:
                    max_dd = dd

        avg_cost = total_invested / total_shares if total_shares > 0 else 0

        return DCASimulationResult(
            fund_code="",
            total_invested=round(total_invested, 2),
            final_value=round(final_value, 2),
            total_return=round(total_return, 6),
            annualized_return=round(annualized_return, 6),
            max_drawdown=round(max_dd, 6),
            investment_count=len(records),
            avg_cost=round(avg_cost, 4),
            records=records,
        )
