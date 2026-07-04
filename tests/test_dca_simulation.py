"""定投模拟测试"""

from __future__ import annotations

from backend.funds.dca import DCASimulator
from backend.schemas.funds import DCAFrequency


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
