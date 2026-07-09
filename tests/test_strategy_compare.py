"""策略横向对比榜测试 — 一次取数跑全部内置策略并排名。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from unittest.mock import patch


def _make_bars(n: int = 180):
    base = datetime(2024, 1, 1)
    bars = []
    for i in range(n):
        c = max(1.0, 100 + 0.2 * i + 6.0 * math.sin(i / 9.0))
        bars.append(
            {
                "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": round(c - 0.3, 2),
                "high": round(c + 2, 2),
                "low": round(max(0.5, c - 2), 2),
                "close": round(c, 2),
                "volume": 10000 + (i % 6) * 1200,
            }
        )
    return bars


def _run(rank_by="sharpe_ratio"):
    from backend.api.quant import (
        StrategyCompareRequestBody,
        _run_strategy_comparison_local,
    )

    body = StrategyCompareRequestBody(
        symbol="600519",
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_capital=1000000.0,
        rank_by=rank_by,
    )
    with patch(
        "backend.api.quant_core._load_local_bars",
        return_value=(_make_bars(), "local_price_store"),
    ):
        return _run_strategy_comparison_local(body)


class TestStrategyComparison:
    def test_ranking_shape_and_skip(self):
        p = _run()
        assert p["mode"] == "strategy_compare"
        assert p["run_id"].startswith("cmp-")
        assert p["evaluated"] >= 5
        # custom_rule 是模板策略, 应被跳过
        assert "custom_rule" in p["skipped"]
        assert all(row["strategy_id"] != "custom_rule" for row in p["ranking"])

    def test_ranks_are_sequential(self):
        p = _run()
        ranks = [row["rank"] for row in p["ranking"]]
        assert ranks == list(range(1, len(ranks) + 1))

    def test_sorted_desc_by_rank_key(self):
        p = _run(rank_by="total_return")
        vals = [row["total_return"] for row in p["ranking"]]
        assert vals == sorted(vals, reverse=True)
        assert p["rank_by"] == "total_return"

    def test_invalid_rank_by_falls_back(self):
        p = _run(rank_by="__nope__")
        assert p["rank_by"] == "sharpe_ratio"

    def test_rows_have_metric_keys(self):
        p = _run()
        row = p["ranking"][0]
        for key in (
            "strategy_id",
            "total_return",
            "annual_return",
            "sharpe_ratio",
            "max_drawdown",
            "win_rate",
            "trade_count",
        ):
            assert key in row

    def test_determinism(self):
        a = _run()
        b = _run()
        assert a["ranking"] == b["ranking"]

    def test_disclaimer_and_assumptions(self):
        p = _run()
        assert "不构成投资建议" in p["disclaimer"]
        assert p["assumptions"].get("t_plus_1") is True
        assert p["data_source"] == "local_price_store"

    def test_route_registered(self):
        import backend.api.quant as q

        paths = [r.path for r in q.router.routes]
        assert "/api/quant/compare-strategies" in paths
