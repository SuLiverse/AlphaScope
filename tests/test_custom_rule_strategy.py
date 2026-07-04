"""低代码自定义规则策略测试(v1.9.4)。

验证:
- compute_fields 产出 FIELD_CATALOG 全字段、与 bars 等长、warmup 段为 NaN
- _eval_rules 的 and/or/NaN/空规则语义
- 策略已注册进 StrategyRegistry
- generate_signals 规则触发买卖; 空规则 → 无信号
- 端到端走 BacktestEngine 不报错且能成交
"""

from __future__ import annotations

import math

from backend.quant.strategies import StrategyRegistry
from backend.quant.strategies.custom_rule import (
    FIELD_CATALOG,
    CustomRuleStrategy,
    _eval_rules,
    compute_fields,
)


def _bars(closes, vols=None):
    vols = vols or [1000] * len(closes)
    out = []
    for i, c in enumerate(closes):
        out.append(
            {
                "date": f"2026-01-{i + 1:02d}",
                "symbol": "TEST",
                "open": c,
                "high": c * 1.01,
                "low": c * 0.99,
                "close": c,
                "volume": vols[i],
            }
        )
    return out


def test_registered_in_registry():
    assert StrategyRegistry.get("custom_rule") is not None
    names = {s["name"] for s in StrategyRegistry.list_strategies()}
    assert "custom_rule" in names


def test_compute_fields_complete_and_aligned():
    bars = _bars([10 + i * 0.1 for i in range(80)])
    fields = compute_fields(bars)
    # 全字段齐全
    assert set(fields.keys()) == set(FIELD_CATALOG.keys())
    # 每个序列与 bars 等长
    for k, series in fields.items():
        assert len(series) == len(bars), k
    # warmup: MA60 相关字段前 59 根应为 NaN
    assert math.isnan(fields["close_vs_ma60_pct"][0])
    assert not math.isnan(fields["close_vs_ma60_pct"][-1])
    # close 字段始终有效
    assert fields["close"][0] == 10.0


def test_eval_rules_logic():
    ctx = {"rsi": 25.0, "vol_ratio": 2.0}
    assert _eval_rules([{"field": "rsi", "op": "<", "value": 30}], ctx, "and") is True
    # and: 一条假 → 假
    assert (
        _eval_rules(
            [
                {"field": "rsi", "op": "<", "value": 30},
                {"field": "vol_ratio", "op": ">", "value": 3},
            ],
            ctx,
            "and",
        )
        is False
    )
    # or: 一条真 → 真
    assert (
        _eval_rules(
            [
                {"field": "rsi", "op": "<", "value": 30},
                {"field": "vol_ratio", "op": ">", "value": 3},
            ],
            ctx,
            "or",
        )
        is True
    )
    # NaN 字段 → 该条不成立
    assert _eval_rules([{"field": "rsi", "op": "<", "value": 30}], {"rsi": float("nan")}, "and") is False
    # 空规则 → False
    assert _eval_rules([], ctx, "and") is False
    # 未知字段 → False
    assert _eval_rules([{"field": "nope", "op": "<", "value": 1}], ctx, "and") is False


def test_empty_rules_no_signals():
    bars = _bars([10, 11, 12, 13])
    sig = CustomRuleStrategy({}).generate_signals(bars)
    assert sig == []


def test_buy_rule_triggers():
    # 一直上涨 → pct_change>0 持续触发买入
    bars = _bars([10 + i for i in range(10)])
    strat = CustomRuleStrategy({"buy_rules": [{"field": "pct_change", "op": ">", "value": 0}]})
    sigs = strat.generate_signals(bars, {"equity": 100000})
    assert len(sigs) == len(bars)
    assert any(s.action == "buy" for s in sigs)


def test_end_to_end_backtest_runs():
    from backend.quant.engine import BacktestEngine

    # 先跌后涨: RSI<35 买入, RSI>65 卖出
    closes = [20 - i * 0.4 for i in range(20)] + [12 + i * 0.5 for i in range(30)]
    bars = _bars(closes)
    strat = CustomRuleStrategy(
        {
            "buy_rules": [{"field": "rsi", "op": "<", "value": 35}],
            "sell_rules": [{"field": "rsi", "op": ">", "value": 65}],
            "logic": "and",
            "position_size_pct": 30,
        }
    )
    engine = BacktestEngine(initial_capital=100000, commission_rate=0.001)
    result = engine.run(strat, bars, "TEST")
    # 不抛异常, 有净值曲线, assumptions 存在(防未来函数等)
    assert result.equity_curve
    assert isinstance(result.trades, list)
    assert getattr(result, "assumptions", None) is not None
