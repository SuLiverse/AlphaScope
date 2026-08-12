"""定投模拟测试"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from backend.funds.dca import DCASimulator, _generate_dates
from backend.schemas.funds import DCAFrequency


def _reference_xirr(cashflows: list[tuple[date, float]]) -> float:
    """独立参考实现（Newton 迭代），用于交叉验证 dca._xirr 的二分结果"""
    t0 = cashflows[0][0]
    days = [(d - t0).days for d, _ in cashflows]
    amounts = [a for _, a in cashflows]

    def npv(r):
        return sum(a / (1 + r) ** (dy / 365.0) for a, dy in zip(amounts, days))

    r = 0.1
    for _ in range(200):
        h = max(1e-6, abs(r) * 1e-6)
        f = npv(r)
        df = (npv(r + h) - npv(r - h)) / (2 * h)
        if df == 0:
            break
        r_next = r - f / df
        if abs(r_next - r) < 1e-12:
            return r_next
        r = r_next
    return r


def _make_nav_records(start: float = 1.0, count: int = 120, trend: float = 0.001) -> list[dict]:
    """生成测试用净值序列"""
    records = []
    nav = start
    for i in range(count):
        day = 1 + (i % 28)  # 简化日期
        month = 1 + (i // 28) % 12
        year = 2024 + (i // 336)
        records.append(
            {
                "date": f"{year}-{month:02d}-{day:02d}",
                "nav": round(nav, 4),
            }
        )
        nav *= 1 + trend
    return records


class TestDCASimulator:
    """定投模拟器测试"""

    def test_basic_simulation(self):
        navs = _make_nav_records(start=1.0, count=120, trend=0.001)
        sim = DCASimulator()
        result = sim.simulate(
            nav_records=navs,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert result.total_invested > 0
        assert result.final_value > 0
        assert result.investment_count > 0
        assert result.records

    def test_declining_market(self):
        navs = _make_nav_records(start=1.0, count=120, trend=-0.001)
        sim = DCASimulator()
        result = sim.simulate(
            nav_records=navs,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert result.total_invested > 0
        # 下跌市场定投可能亏损
        assert result.total_return <= 0

    def test_empty_navs(self):
        sim = DCASimulator()
        result = sim.simulate(
            nav_records=[],
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert result.total_invested == 0
        assert result.investment_count == 0

    def test_zero_amount(self):
        navs = _make_nav_records()
        sim = DCASimulator()
        result = sim.simulate(
            nav_records=navs,
            amount=0,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert result.total_invested == 0

    def test_different_frequencies(self):
        navs = _make_nav_records(start=1.0, count=120, trend=0.001)
        sim = DCASimulator()
        for freq in [
            DCAFrequency.WEEKLY,
            DCAFrequency.BIWEEKLY,
            DCAFrequency.MONTHLY,
            DCAFrequency.QUARTERLY,
        ]:
            result = sim.simulate(
                nav_records=navs,
                amount=1000,
                frequency=freq,
                start_date="2024-01-01",
                end_date="2024-12-31",
            )
            assert result.total_invested > 0

    def test_avg_cost(self):
        navs = _make_nav_records(start=1.0, count=60, trend=0.002)
        sim = DCASimulator()
        result = sim.simulate(
            nav_records=navs,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert result.avg_cost > 0
        # 平均成本应该在起始净值和最终净值之间
        assert 1.0 <= result.avg_cost <= navs[-1]["nav"]

    def test_future_nav_forbidden(self):
        # 旧逻辑用 abs() 日期差会选到未来净值（2024-01-10 距目标日 1 天 < 7 天）
        navs = [
            {"date": "2024-01-02", "nav": 1.0},
            {"date": "2024-01-10", "nav": 9.9},
        ]
        result = DCASimulator().simulate(
            nav_records=navs,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-09",
            end_date="2024-01-09",
        )
        assert result.investment_count == 1
        assert result.records[0]["nav"] == 1.0
        assert result.records[0]["shares"] == pytest.approx(1000.0)
        assert result.final_value == pytest.approx(1000.0)
        assert result.total_return == 0.0

    def test_xirr_annualized_matches_independent_calculation(self):
        # 月定投 1000、净值单边上涨 12 期
        buy_dates = _generate_dates("2024-01-01", "2024-12-01", DCAFrequency.MONTHLY)
        assert len(buy_dates) == 12
        navs = [{"date": d, "nav": round(1.0 + 0.05 * i, 4)} for i, d in enumerate(buy_dates)]
        navs.append({"date": "2024-12-31", "nav": 9.99})
        result = DCASimulator().simulate(
            nav_records=navs,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-12-01",
        )
        assert result.investment_count == 12
        expected_shares = sum(1000 / record["nav"] for record in navs[:-1])
        assert result.final_value == pytest.approx(round(expected_shares * 1.55, 2))
        # 与独立 Newton 实现的 XIRR 一致
        cashflows = [(datetime.strptime(rec["date"], "%Y-%m-%d").date(), -rec["amount"]) for rec in result.records]
        cashflows.append((datetime.strptime("2024-12-01", "%Y-%m-%d").date(), result.final_value))
        assert result.annualized_return == pytest.approx(_reference_xirr(cashflows), abs=1e-4)
        # 上涨市：新 XIRR 口径 > 旧简单口径（(final/invested-1) 按全程年化，低估）
        days = (datetime.strptime("2024-12-01", "%Y-%m-%d") - datetime.strptime("2024-01-01", "%Y-%m-%d")).days
        old_annualized = (result.final_value / result.total_invested) ** (365.0 / days) - 1
        assert result.annualized_return > old_annualized

    def test_drawdown_not_diluted_by_contributions(self):
        # 净值先跌 30% 再回升，期间持续扣款；旧市值口径回撤被入金摊薄为 0
        buy_dates = _generate_dates("2024-01-01", "2024-05-30", DCAFrequency.MONTHLY)
        assert len(buy_dates) == 5
        nav_values = [1.0, 1.0, 0.8, 0.7, 1.0]
        navs = [{"date": d, "nav": v} for d, v in zip(buy_dates, nav_values)]
        navs.append({"date": "2024-06-30", "nav": 1.0})
        result = DCASimulator().simulate(
            nav_records=navs,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-05-30",
        )
        assert result.investment_count == 5
        assert result.max_drawdown == pytest.approx(0.30, abs=0.01)

    def test_single_nav_point_no_error(self):
        navs = [{"date": "2024-01-01", "nav": 1.0}]
        result = DCASimulator().simulate(
            nav_records=navs,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        assert result.investment_count == 1
        assert result.max_drawdown == 0.0
        assert result.total_invested == pytest.approx(1000.0)

    def test_drawdown_in_between_contribution_dates_is_captured(self):
        navs = [
            {"date": "2024-01-01", "nav": 1.0},
            {"date": "2024-01-15", "nav": 0.5},
            {"date": "2024-01-31", "nav": 1.0},
        ]
        result = DCASimulator().simulate(
            nav_records=navs,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        assert result.investment_count == 1
        assert result.max_drawdown == pytest.approx(0.5)


class TestDCAGoldenValues:
    """精确值回归网 —— 手算期望值锁定 plan 004 修复后的行为（表征测试）。

    锁定的是修复后的语义：真实日历月 / 净值只向前匹配（禁止未来净值）/
    XIRR 资金加权年化 / 单位净值口径回撤。期望值全部按新口径手算；
    若再改动公式必须同步重推下方数值——期望值过时即本测试失败。
    """

    NAV_RECORDS = [
        # 前置记录：2024-01-01 首笔只向前找时的确定性回退（旧数据无 ≤01-01 的记录）
        {"date": "2023-12-31", "nav": 1.00},
        {"date": "2024-01-02", "nav": 1.00},
        {"date": "2024-01-03", "nav": 1.02},
        {"date": "2024-01-04", "nav": 1.04},
        {"date": "2024-01-05", "nav": 1.06},
        {"date": "2024-01-06", "nav": 1.08},
        {"date": "2024-01-07", "nav": 1.09},
        {"date": "2024-01-08", "nav": 1.10},
        {"date": "2024-01-09", "nav": 1.10},
    ]

    def test_golden_monthly_run(self):
        result = DCASimulator().simulate(
            nav_records=self.NAV_RECORDS,
            amount=1000,
            frequency=DCAFrequency.MONTHLY,
            start_date="2024-01-01",
            end_date="2024-01-31",
        )
        # 手算推导（dca.py plan 004 修复后语义）:
        # Calendar-month scheduling contributes once on Jan 1; Jan 31 is the
        # valuation date. The latest known NAV is Jan 9 at 1.10.
        assert result.investment_count == 1
        assert result.total_invested == pytest.approx(1000.0)
        assert result.final_value == pytest.approx(1100.0)
        assert result.total_return == pytest.approx(0.10)
        assert result.annualized_return == pytest.approx(2.188680, rel=1e-6)
        assert result.max_drawdown == pytest.approx(0.0)
        assert result.avg_cost == pytest.approx(1.0)
        assert result.records == [
            {
                "date": "2024-01-01",
                "nav": 1.0,
                "amount": 1000,
                "shares": 1000.0,
                "total_shares": 1000.0,
                "total_invested": 1000.0,
            }
        ]

    def test_generate_dates_sequence(self):
        from backend.funds.dca import _generate_dates

        assert _generate_dates("2024-01-01", "2024-01-31", DCAFrequency.MONTHLY) == ["2024-01-01"]
        assert _generate_dates("2024-01-31", "2024-04-30", DCAFrequency.MONTHLY) == [
            "2024-01-31",
            "2024-02-29",
            "2024-03-31",
            "2024-04-30",
        ]
        assert _generate_dates("2024-01-01", "2024-01-22", DCAFrequency.WEEKLY) == [
            "2024-01-01",
            "2024-01-08",
            "2024-01-15",
            "2024-01-22",
        ]
        assert _generate_dates("2024-01-01", "2024-01-31", DCAFrequency.BIWEEKLY) == [
            "2024-01-01",
            "2024-01-15",
            "2024-01-29",
        ]
        assert _generate_dates("2024-01-31", "2024-07-31", DCAFrequency.QUARTERLY) == [
            "2024-01-31",
            "2024-04-30",
            "2024-07-31",
        ]
