"""定投模拟引擎 — 基于历史净值的真实模拟"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any

from backend.schemas.funds import DCAFrequency, DCASimulationResult


def _generate_dates(start_date: str, end_date: str, frequency: DCAFrequency) -> list[str]:
    """生成定投日期序列"""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    if frequency in {DCAFrequency.WEEKLY, DCAFrequency.BIWEEKLY}:
        step = 7 if frequency == DCAFrequency.WEEKLY else 14
        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=step)
        return dates

    month_step = 3 if frequency == DCAFrequency.QUARTERLY else 1
    dates = []
    month_offset = 0
    while True:
        month_index = start.month - 1 + month_offset
        year = start.year + month_index // 12
        month = month_index % 12 + 1
        day = min(start.day, calendar.monthrange(year, month)[1])
        current = start.replace(year=year, month=month, day=day)
        if current > end:
            break
        dates.append(current.strftime("%Y-%m-%d"))
        month_offset += month_step
    return dates


def _find_nearest_nav(nav_records: list[dict[str, Any]], target_date: str) -> float | None:
    """Return the latest positive NAV at or before ``target_date``."""
    best = None
    best_date = ""
    for r in nav_records:
        record_date = str(r.get("date") or "")[:10]
        try:
            nav = float(r.get("nav"))
        except (TypeError, ValueError):
            continue
        if nav > 0 and record_date <= target_date and record_date > best_date:
            best_date = record_date
            best = nav
    return best


def _xirr(cashflows: list[tuple[date, float]], guess: float = 0.1) -> float:
    """求解资金加权年化收益率：Σ amount_i / (1+r)^((d_i - d_0)/365) = 0

    用二分法（区间 [-0.9999, 10]，200 次迭代），避免 Newton 法在平坦现金流下发散。
    现金流不含正负两种符号时方程无内部解，返回 0.0；全部现金流在同一日
    （无时间跨度）时收益率无意义，也返回 0.0。
    """
    if not cashflows:
        return 0.0
    amounts = [a for _, a in cashflows]
    if not (any(a < 0 for a in amounts) and any(a > 0 for a in amounts)):
        return 0.0

    t0 = cashflows[0][0]
    days = [(d - t0).days for d, _ in cashflows]
    if max(days) <= 0:
        return 0.0

    def npv(r: float) -> float:
        return sum(a / (1 + r) ** (dy / 365.0) for a, dy in zip(amounts, days))

    lo, hi = -0.9999, 10.0
    f_lo, f_hi = npv(lo), npv(hi)
    if f_lo * f_hi > 0:
        return 0.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(mid)
        if f_mid == 0.0 or (hi - lo) / 2.0 < 1e-12:
            return mid
        if (f_lo > 0) == (f_mid > 0):
            lo, f_lo = mid, f_mid
        else:
            hi, f_hi = mid, f_mid
    return (lo + hi) / 2.0


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

        for buy_date in dates:
            nav = _find_nearest_nav(nav_records, buy_date)
            if nav is None or nav <= 0:
                continue

            shares = amount / nav
            total_shares += shares
            total_invested += amount

            records.append(
                {
                    "date": buy_date,
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

        # End-of-period valuation must use only information available by
        # end_date; nav_records may contain newer provider rows.
        final_nav = _find_nearest_nav(nav_records, end_date)
        if final_nav is None:
            final_nav = records[-1]["nav"]
        final_value = total_shares * final_nav
        total_return = (final_value / total_invested - 1) if total_invested > 0 else 0

        # 计算年化收益（资金加权口径 XIRR：每笔扣款 + 期末市值按实际日期折现）
        cashflows = [(datetime.strptime(rec["date"], "%Y-%m-%d").date(), -rec["amount"]) for rec in records]
        cashflows.append((datetime.strptime(end_date, "%Y-%m-%d").date(), final_value))
        annualized_return = _xirr(cashflows)

        # Use the complete NAV path during the simulation window. Looking only
        # at contribution dates misses drawdowns that recover before the next
        # scheduled purchase.
        nav_path = [records[0]["nav"]]
        for nav_record in sorted(nav_records, key=lambda item: str(item.get("date") or "")):
            nav_date = str(nav_record.get("date") or "")[:10]
            try:
                nav = float(nav_record.get("nav"))
            except (TypeError, ValueError):
                continue
            if start_date < nav_date <= end_date and nav > 0:
                nav_path.append(nav)

        max_dd = 0.0
        peak = nav_path[0] if nav_path else 0
        for nav in nav_path:
            if nav > peak:
                peak = nav
            if peak > 0:
                dd = (peak - nav) / peak
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
