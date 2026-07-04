"""遗传算法策略参数寻优 (v1.9.11)

用**确定性、可复现**的遗传算法在历史样本内搜索某个内置策略的**参数组合**,
适应度 = 复用现有 :class:`BacktestEngine` 跑一遍回测后的某项绩效指标(默认夏普)。

设计要点:
- **不进化代码、只进化参数**:遗传操作发生在数值参数空间(周期/阈值/仓位等),
  绝不生成或修改策略逻辑 —— 合规上等同「对历史做确定性参数搜索」。
- **确定性**:全程由 ``random.Random(seed)`` 驱动(采样/锦标赛/交叉/变异),
  同 seed + 同输入 → 完全相同结果, 可复现、可单测。
- **失败安全**:单个个体回测异常 → 适应度沉到极小值(被淘汰), 绝不抛出;
  样本不足 → ``insufficient``; 无可寻优数值参数 → ``degraded``(仅评估默认参数)。
- **算力有界**:种群/代数夹紧, 总评估数设预算上限并去重缓存, 避免 API 卡死。

合规红线:样本内寻优**极易过拟合**, 样本内最优 ≠ 未来有效。报告强制附免责并
建议对最优参数再做样本外走查([[walk_forward]])验证。不构成任何投资建议。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

# ---- 边界与预算 ----
_MIN_BARS = 40
_POP_MIN, _POP_MAX = 4, 40
_GEN_MIN, _GEN_MAX = 1, 20
_MAX_EVALS = 800  # 总回测评估预算(去重前的上限基准), 超出则压低代数

# ---- 遗传超参 ----
_ELITE = 2
_TOURNAMENT = 3
_CX_RATE = 0.7
_MUT_RATE = 0.25

_DEFAULT_METRIC = "sharpe_ratio"
_ALLOWED_METRICS = {
    "sharpe_ratio",
    "calmar_ratio",
    "sortino_ratio",
    "total_return",
    "annualized_return",
    "profit_factor",
    "win_rate",
}
_SNAPSHOT_KEYS = (
    "total_return",
    "annualized_return",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "max_drawdown",
    "win_rate",
    "profit_factor",
    "total_trades",
)
# 模板/公式型策略无可寻优的数值含义, 与策略榜一致跳过(由公式/规则定义信号)。
_SKIP_STRATEGIES = {"tdx", "custom_rule"}

_WORST = -1.0e9
_DISCLAIMER = (
    "遗传算法在历史样本内寻优参数,极易过拟合;样本内最优≠未来有效。"
    "强烈建议对最优参数再做样本外走查(walk-forward)验证,本结果不构成任何投资建议。"
)


@dataclass
class Individual:
    genome: dict[str, Any]  # 参数空间子集(被进化的键)
    params: dict[str, Any]  # 实际喂给策略的完整参数(默认 + genome)
    fitness: float
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "genome": self.genome,
            "params": self.params,
            "fitness": round(self.fitness, 6) if math.isfinite(self.fitness) else None,
            "metrics": self.metrics,
        }


@dataclass
class GenerationStat:
    generation: int
    best_fitness: float
    avg_fitness: float
    best_genome: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generation": self.generation,
            "best_fitness": round(self.best_fitness, 6) if math.isfinite(self.best_fitness) else None,
            "avg_fitness": round(self.avg_fitness, 6) if math.isfinite(self.avg_fitness) else None,
            "best_genome": self.best_genome,
        }


@dataclass
class EvolutionReport:
    status: str  # ok | insufficient | degraded | error
    strategy_id: str
    symbol: str
    fitness_metric: str
    population_size: int
    generations: int
    seed: int
    evaluations: int
    best: Individual | None
    baseline: Individual | None
    history: list[GenerationStat]
    param_space: dict[str, Any]
    message: str

    def improvement(self) -> float | None:
        if self.best is None or self.baseline is None:
            return None
        if not (math.isfinite(self.best.fitness) and math.isfinite(self.baseline.fitness)):
            return None
        return round(self.best.fitness - self.baseline.fitness, 6)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "fitness_metric": self.fitness_metric,
            "population_size": self.population_size,
            "generations": self.generations,
            "seed": self.seed,
            "evaluations": self.evaluations,
            "best": self.best.to_dict() if self.best else None,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "improvement": self.improvement(),
            "history": [g.to_dict() for g in self.history],
            "param_space": self.param_space,
            "message": self.message,
            "disclaimer": _DISCLAIMER,
        }


# ============== 参数空间 ==============


def infer_param_space(strategy_id: str) -> dict[str, dict[str, Any]]:
    """从策略 ``default_params`` 推断一个合理的数值搜索空间(仅 int/float)。

    规则:正整数 ``d`` → [max(1, 0.5d), 2d];正浮点 ``f`` → [0.5f, 2f]。
    布尔/字符串参数跳过。模板/公式型策略返回空(无可寻优数值参数)。
    """
    if strategy_id in _SKIP_STRATEGIES:
        return {}
    try:
        from backend.quant.strategies import StrategyRegistry

        cls = StrategyRegistry.get(strategy_id)
    except Exception:
        cls = None
    if cls is None:
        return {}
    defaults = dict(getattr(cls, "default_params", {}) or {})
    space: dict[str, dict[str, Any]] = {}
    for name, val in defaults.items():
        if isinstance(val, bool):
            continue
        if isinstance(val, int):
            d = int(val)
            if d >= 1:
                lo = max(1, round(d * 0.5))
                hi = max(lo + 1, round(d * 2))
            else:
                lo, hi = 0, max(5, abs(d) * 2)
            space[name] = {"type": "int", "min": lo, "max": hi, "step": 1, "default": d}
        elif isinstance(val, float):
            f = float(val)
            if f > 0:
                lo, hi = round(f * 0.5, 6), round(f * 2, 6)
            elif f == 0:
                lo, hi = 0.0, 1.0
            else:
                lo, hi = round(f * 2, 6), round(f * 0.5, 6)
            step = round((hi - lo) / 20, 6) or 1e-6
            space[name] = {
                "type": "float",
                "min": lo,
                "max": hi,
                "step": step,
                "default": f,
            }
    return space


def _sanitize_space(space: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """校验/规整外部传入的参数空间, 丢弃非法项(失败安全)。"""
    clean: dict[str, dict[str, Any]] = {}
    for name, spec in (space or {}).items():
        try:
            typ = str(spec.get("type", "float"))
            lo = float(spec["min"])
            hi = float(spec["max"])
            if hi <= lo:
                continue
            if typ == "int":
                ilo, ihi = int(round(lo)), int(round(hi))
                if ihi <= ilo:
                    ihi = ilo + 1
                clean[name] = {
                    "type": "int",
                    "min": ilo,
                    "max": ihi,
                    "step": int(spec.get("step", 1) or 1),
                }
            else:
                step = float(spec.get("step", (hi - lo) / 20) or 1e-6)
                clean[name] = {"type": "float", "min": lo, "max": hi, "step": step}
        except Exception:
            continue
    return clean


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clamp_int(value: int, lo: int, hi: int) -> int:
    return int(max(lo, min(hi, value)))


def _project(value: Any, spec: dict[str, Any]) -> Any:
    """把一个默认值投影进搜索空间(夹紧 + 取整);无效则取区间中点。"""
    lo, hi = spec["min"], spec["max"]
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = (lo + hi) / 2
    if spec["type"] == "int":
        return _clamp_int(int(round(v)), int(lo), int(hi))
    return round(_clamp(v, lo, hi), 6)


def _sample_one(rng: random.Random, spec: dict[str, Any]) -> Any:
    lo, hi = spec["min"], spec["max"]
    if spec["type"] == "int":
        return rng.randint(int(lo), int(hi))
    return round(lo + rng.random() * (hi - lo), 6)


def _sample(rng: random.Random, space: dict[str, Any]) -> dict[str, Any]:
    return {name: _sample_one(rng, spec) for name, spec in space.items()}


def _mutate_one(rng: random.Random, spec: dict[str, Any], value: Any) -> Any:
    lo, hi = spec["min"], spec["max"]
    if spec["type"] == "int":
        span = max(1, int(round((hi - lo) * 0.2)))
        return _clamp_int(int(value) + rng.randint(-span, span), int(lo), int(hi))
    sigma = (hi - lo) * 0.15 or 1e-6
    return round(_clamp(float(value) + rng.gauss(0, sigma), lo, hi), 6)


def _crossover(rng: random.Random, a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    return {k: (a[k] if rng.random() < 0.5 else b[k]) for k in a}


def _mutate(rng: random.Random, space: dict[str, Any], genome: dict[str, Any]) -> dict[str, Any]:
    out = dict(genome)
    for name, spec in space.items():
        if rng.random() < _MUT_RATE:
            out[name] = _mutate_one(rng, spec, out[name])
    return out


def _key(genome: dict[str, Any]) -> tuple:
    return tuple(sorted(genome.items()))


def _finite(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return _WORST
    return v if math.isfinite(v) else _WORST


# ============== 评估(适应度 = 引擎回测) ==============


def _safe_eval(
    strategy_id: str,
    genome: dict[str, Any],
    defaults: dict[str, Any],
    bars: list[dict[str, Any]],
    symbol: str,
    initial_capital: float,
    metric: str,
) -> Individual:
    full = {**defaults, **genome}
    try:
        from backend.quant.engine import BacktestEngine
        from backend.quant.strategies import StrategyRegistry

        strategy = StrategyRegistry.create(strategy_id, full)
        if strategy is None:
            return Individual(genome=genome, params=full, fitness=_WORST, metrics={})
        engine = BacktestEngine(initial_capital=initial_capital, commission_rate=0.001)
        result = engine.run(strategy, bars, symbol)
        perf = result.performance or {}
        fitness = _finite(perf.get(metric, 0.0))
        metrics = {k: perf.get(k, 0.0) for k in _SNAPSHOT_KEYS}
        return Individual(genome=genome, params=full, fitness=fitness, metrics=metrics)
    except Exception:
        return Individual(genome=genome, params=full, fitness=_WORST, metrics={})


def _tournament_select(rng: random.Random, pop: list[Individual]) -> Individual:
    k = min(_TOURNAMENT, len(pop))
    contenders = rng.sample(pop, k)
    return max(contenders, key=lambda ind: ind.fitness)


def _gen_stat(generation: int, pop: list[Individual]) -> GenerationStat:
    finite = [ind.fitness for ind in pop if math.isfinite(ind.fitness)]
    best = max(pop, key=lambda ind: ind.fitness)
    avg = sum(finite) / len(finite) if finite else _WORST
    return GenerationStat(
        generation=generation,
        best_fitness=best.fitness,
        avg_fitness=avg,
        best_genome=dict(best.genome),
    )


def run_evolution(
    strategy_id: str,
    bars: list[dict[str, Any]],
    symbol: str = "",
    param_space: dict[str, Any] | None = None,
    *,
    population_size: int = 16,
    generations: int = 8,
    fitness_metric: str = _DEFAULT_METRIC,
    initial_capital: float = 100000.0,
    seed: int = 42,
    base_params: dict[str, Any] | None = None,
) -> EvolutionReport:
    """对 ``strategy_id`` 的数值参数做确定性遗传算法寻优。

    Args:
        strategy_id: 内置策略注册名。
        bars: 历史 OHLCV(需 ≥ ``_MIN_BARS`` 根)。
        symbol: 标的(透传给引擎/报告)。
        param_space: 可选显式搜索空间;缺省则由 ``infer_param_space`` 推断。
        population_size / generations: 种群规模 / 进化代数(自动夹紧 + 预算约束)。
        fitness_metric: 适应度绩效键(夏普/卡玛/索提诺/收益/胜率等, 越大越好)。
        seed: 随机种子(决定可复现性)。
        base_params: 叠加在默认参数之上的固定基底(不被进化)。

    Returns:
        :class:`EvolutionReport`(永不抛出)。
    """
    metric = fitness_metric if fitness_metric in _ALLOWED_METRICS else _DEFAULT_METRIC

    try:
        from backend.quant.strategies import StrategyRegistry

        cls = StrategyRegistry.get(strategy_id)
    except Exception:
        cls = None
    if cls is None:
        return EvolutionReport(
            status="error",
            strategy_id=strategy_id,
            symbol=symbol,
            fitness_metric=metric,
            population_size=0,
            generations=0,
            seed=seed,
            evaluations=0,
            best=None,
            baseline=None,
            history=[],
            param_space={},
            message=f"未知策略: {strategy_id}",
        )

    if not bars or len(bars) < _MIN_BARS:
        return EvolutionReport(
            status="insufficient",
            strategy_id=strategy_id,
            symbol=symbol,
            fitness_metric=metric,
            population_size=0,
            generations=0,
            seed=seed,
            evaluations=0,
            best=None,
            baseline=None,
            history=[],
            param_space={},
            message=f"行情样本不足({len(bars) if bars else 0} < {_MIN_BARS} 根),无法寻优。",
        )

    space = _sanitize_space(param_space) if param_space else infer_param_space(strategy_id)
    defaults = dict(getattr(cls, "default_params", {}) or {})
    if base_params:
        defaults.update(base_params)

    # 基线:默认参数跑一遍, 作为「寻优是否真的更好」的对照。
    baseline = _safe_eval(strategy_id, {}, defaults, bars, symbol, initial_capital, metric)

    if not space:
        return EvolutionReport(
            status="degraded",
            strategy_id=strategy_id,
            symbol=symbol,
            fitness_metric=metric,
            population_size=0,
            generations=0,
            seed=seed,
            evaluations=1,
            best=baseline,
            baseline=baseline,
            history=[],
            param_space={},
            message="该策略无可寻优的数值参数,已仅评估默认参数。",
        )

    pop_size = _clamp_int(population_size, _POP_MIN, _POP_MAX)
    gens = _clamp_int(generations, _GEN_MIN, _GEN_MAX)
    # 预算约束: pop*(gens+1) 评估数压到上限内(去重前的保守估计)。
    while pop_size * (gens + 1) > _MAX_EVALS and gens > _GEN_MIN:
        gens -= 1

    rng = random.Random(seed)
    cache: dict[tuple, Individual] = {}

    def evaluate(genome: dict[str, Any]) -> Individual:
        key = _key(genome)
        cached = cache.get(key)
        if cached is not None:
            return cached
        ind = _safe_eval(strategy_id, genome, defaults, bars, symbol, initial_capital, metric)
        cache[key] = ind
        return ind

    # 初始种群: 默认值投影进空间(给搜索一个「靠谱起点」)+ 随机个体。
    seed_genome = {name: _project(defaults.get(name), spec) for name, spec in space.items()}
    genomes = [seed_genome] + [_sample(rng, space) for _ in range(pop_size - 1)]
    population = [evaluate(g) for g in genomes]

    history: list[GenerationStat] = [_gen_stat(0, population)]
    best = max(population, key=lambda ind: ind.fitness)

    for gen in range(1, gens + 1):
        ranked = sorted(population, key=lambda ind: ind.fitness, reverse=True)
        next_genomes: list[dict[str, Any]] = [dict(ind.genome) for ind in ranked[:_ELITE]]
        while len(next_genomes) < pop_size:
            parent_a = _tournament_select(rng, population)
            parent_b = _tournament_select(rng, population)
            if rng.random() < _CX_RATE:
                child = _crossover(rng, parent_a.genome, parent_b.genome)
            else:
                child = dict(parent_a.genome)
            child = _mutate(rng, space, child)
            next_genomes.append(child)

        population = [evaluate(g) for g in next_genomes]
        gen_best = max(population, key=lambda ind: ind.fitness)
        if gen_best.fitness > best.fitness:
            best = gen_best
        history.append(_gen_stat(gen, population))

    status = "ok" if math.isfinite(best.fitness) and best.fitness > _WORST else "error"
    message = (
        f"在 {gens} 代 × {pop_size} 种群中寻优 {metric},共 {len(cache)} 次去重回测评估。"
        if status == "ok"
        else "所有参数组合回测均失败,无有效结果。"
    )

    return EvolutionReport(
        status=status,
        strategy_id=strategy_id,
        symbol=symbol,
        fitness_metric=metric,
        population_size=pop_size,
        generations=gens,
        seed=seed,
        evaluations=len(cache),
        best=best if status == "ok" else None,
        baseline=baseline,
        history=history,
        param_space=space,
        message=message,
    )
