"""遗传算法参数寻优测试 (v1.9.11)。

覆盖:参数空间推断、样本不足/未知策略失败安全、基本寻优可用、**确定性**
(同 seed 同结果)、显式空间被尊重、寻优不劣于默认参数、报告结构与免责。
全部离线、确定性(固定 base date 与 seed)。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from backend.quant.evolution import (
    infer_param_space,
    run_evolution,
)


def _make_bars(n: int, start_close: float = 100.0, drift: float = 0.3, wobble: float = 6.0):
    """确定性 OHLCV:温和上行 + 正弦扰动, 固定 base date(可复现)。"""
    base = datetime(2024, 1, 1)
    bars = []
    for i in range(n):
        close = max(1.0, start_close + drift * i + wobble * math.sin(i / 7.0))
        openp = close - 0.4
        high = max(openp, close) + 1.0
        low = min(openp, close) - 1.0
        bars.append(
            {
                "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
                "open": round(openp, 2),
                "high": round(high, 2),
                "low": round(max(0.5, low), 2),
                "close": round(close, 2),
                "volume": 10000 + (i % 5) * 1000,
            }
        )
    return bars


class TestParamSpace:
    def test_infer_numeric_only(self):
        space = infer_param_space("ma_crossover")
        assert space, "ma_crossover 应当有可寻优的数值参数"
        for name, spec in space.items():
            assert spec["type"] in {"int", "float"}
            assert spec["min"] < spec["max"]

    def test_template_strategies_skipped(self):
        assert infer_param_space("tdx") == {}
        assert infer_param_space("custom_rule") == {}

    def test_unknown_strategy_space_empty(self):
        assert infer_param_space("does_not_exist") == {}


class TestFailSafe:
    def test_insufficient_data(self):
        report = run_evolution("ma_crossover", _make_bars(20), symbol="T")
        assert report.status == "insufficient"
        assert report.best is None
        # 永不抛出, to_dict 仍然良构
        assert report.to_dict()["disclaimer"]

    def test_unknown_strategy(self):
        report = run_evolution("nope_strategy", _make_bars(120), symbol="T")
        assert report.status == "error"
        assert report.best is None

    def test_empty_sanitized_space_degrades(self):
        # 显式但非法的空间(min>max)→ 清洗后为空 → 退化为仅评估默认参数
        report = run_evolution(
            "ma_crossover",
            _make_bars(120),
            symbol="T",
            param_space={"x": {"type": "int", "min": 5, "max": 1}},
        )
        assert report.status == "degraded"
        assert report.baseline is not None
        assert report.param_space == {}


class TestEvolution:
    def test_basic_run_ok(self):
        report = run_evolution(
            "ma_crossover",
            _make_bars(260),
            symbol="T",
            population_size=8,
            generations=3,
            seed=1,
        )
        assert report.status == "ok"
        assert report.best is not None
        assert math.isfinite(report.best.fitness)
        assert report.evaluations > 0
        assert report.param_space
        assert report.baseline is not None
        # gen 0 + 3 代 = 4 条历史
        assert len(report.history) == 4

    def test_determinism_same_seed(self):
        a = run_evolution(
            "ma_crossover",
            _make_bars(260),
            symbol="T",
            population_size=8,
            generations=3,
            seed=7,
        )
        b = run_evolution(
            "ma_crossover",
            _make_bars(260),
            symbol="T",
            population_size=8,
            generations=3,
            seed=7,
        )
        assert a.best is not None and b.best is not None
        assert a.best.genome == b.best.genome
        assert a.best.fitness == b.best.fitness
        assert [h.best_fitness for h in a.history] == [h.best_fitness for h in b.history]

    def test_best_not_worse_than_default(self):
        # 默认参数落在推断空间内 → 初始种群含「默认投影」个体, 精英保留 →
        # 全局最优至少不劣于基线(默认参数)。
        report = run_evolution(
            "ma_crossover",
            _make_bars(260),
            symbol="T",
            population_size=10,
            generations=4,
            seed=3,
        )
        assert report.best is not None and report.baseline is not None
        assert report.best.fitness >= report.baseline.fitness - 1e-9

    def test_explicit_space_respected(self):
        space = infer_param_space("ma_crossover")
        one_key = sorted(space.keys())[0]
        spec = space[one_key]
        explicit = {one_key: {"type": spec["type"], "min": spec["min"], "max": spec["max"]}}
        report = run_evolution(
            "ma_crossover",
            _make_bars(200),
            symbol="T",
            param_space=explicit,
            population_size=6,
            generations=2,
            seed=5,
        )
        assert report.status == "ok"
        assert report.best is not None
        # 只进化这一个键
        assert set(report.best.genome.keys()) == {one_key}
        val = report.best.genome[one_key]
        assert spec["min"] <= val <= spec["max"]

    def test_to_dict_shape(self):
        report = run_evolution(
            "ma_crossover",
            _make_bars(200),
            symbol="600519",
            population_size=6,
            generations=2,
            seed=2,
        )
        d = report.to_dict()
        for key in (
            "status",
            "strategy_id",
            "symbol",
            "fitness_metric",
            "population_size",
            "generations",
            "seed",
            "evaluations",
            "best",
            "baseline",
            "improvement",
            "history",
            "param_space",
            "message",
            "disclaimer",
        ):
            assert key in d
        assert d["strategy_id"] == "ma_crossover"
        assert d["symbol"] == "600519"
        assert isinstance(d["history"], list)
        assert d["best"] and "genome" in d["best"] and "metrics" in d["best"]

    def test_invalid_metric_falls_back_to_sharpe(self):
        report = run_evolution(
            "ma_crossover",
            _make_bars(160),
            symbol="T",
            fitness_metric="not_a_metric",
            population_size=6,
            generations=2,
            seed=1,
        )
        assert report.fitness_metric == "sharpe_ratio"

    def test_experiment_summary_for_evolution(self):
        # experiment_store._summarize 的 evolution 分支抽出紧凑摘要(供实验记录列表)
        from backend.quant.experiment_store import _summarize

        report = run_evolution(
            "ma_crossover",
            _make_bars(160),
            symbol="T",
            population_size=6,
            generations=2,
            seed=1,
        )
        payload = report.to_dict()
        payload["mode"] = "evolution"
        summary = _summarize("evolution", payload)
        assert summary["fitness_metric"] == "sharpe_ratio"
        assert summary["generations"] == report.generations
        assert "best_fitness" in summary
        assert "improvement" in summary
        assert "evaluations" in summary
