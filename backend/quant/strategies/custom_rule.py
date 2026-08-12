"""低代码自定义规则策略(v1.9.4, 1.txt + deep-research)。

让用户用「字段 + 操作符 + 阈值」无代码地组合买卖信号, 前端低代码编辑器把规则编译成
本策略的 ``params``, 复用现有 ``StrategyRegistry`` + ``BacktestEngine`` 跑回测——
**不新建回测引擎**, 只是多一个规则驱动的策略插件(与其余 8 个内置策略同走自动发现)。

参数 schema::

    {
      "buy_rules":  [{"field": "rsi", "op": "<", "value": 30}, ...],
      "sell_rules": [{"field": "rsi", "op": ">", "value": 70}, ...],
      "logic": "and",            # 多条规则间的组合: and / or
      "position_size_pct": 20,
    }

可用字段(与前端 FIELD_CATALOG 对齐)由 :data:`FIELD_CATALOG` 定义, 全部按 bar 索引
对齐、仅用 ≤i 的数据计算(配合引擎的 i→i+1 成交, 天然防未来函数)。
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List

from .base import BaseStrategy, Signal, StrategyRegistry

# 字段目录: key -> 中文标签(前端低代码下拉用同一套 key)。
FIELD_CATALOG: Dict[str, str] = {
    "close": "收盘价",
    "pct_change": "当日涨跌幅%",
    "rsi": "RSI(14)",
    "macd_hist": "MACD 柱(DIF-DEA)",
    "dif": "DIF",
    "dea": "DEA",
    "vol_ratio": "量比(量/5日均量)",
    "close_vs_ma5_pct": "现价距MA5 %",
    "close_vs_ma20_pct": "现价距MA20 %",
    "close_vs_ma60_pct": "现价距MA60 %",
    "ma5_vs_ma20_pct": "MA5距MA20 %(>0为金叉态)",
    "ma10_vs_ma20_pct": "MA10距MA20 %",
    "drawdown_from_high_pct": "距区间高点回撤 %",
}

# 允许的操作符 -> 比较函数
_OPS: Dict[str, Callable[[float, float], bool]] = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}

_NAN = float("nan")


def _sma(values: List[float], period: int) -> List[float]:
    out: List[float] = []
    for i in range(len(values)):
        if i < period - 1:
            out.append(_NAN)
        else:
            out.append(sum(values[i - period + 1 : i + 1]) / period)
    return out


def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    out = [values[0]]
    k = 2.0 / (period + 1)
    for i in range(1, len(values)):
        out.append(values[i] * k + out[-1] * (1 - k))
    return out


def _rsi_series(closes: List[float], period: int = 14) -> List[float]:
    """按 bar 索引对齐的 RSI(前 period 根为 NaN)。"""
    n = len(closes)
    out = [_NAN] * n
    if n < period + 1:
        return out
    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(0.0, d) for d in deltas]
    losses = [max(0.0, -d) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # deltas[j] 对应 closes[j+1]; 第一个 RSI 落在 closes[period]
    for j in range(period, len(deltas) + 1):
        if j > period:
            avg_gain = (avg_gain * (period - 1) + gains[j - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[j - 1]) / period
        rsi = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
        out[j] = rsi  # closes[j]
    return out


def _safe_div_pct(a: float, b: float) -> float:
    """(a/b - 1)*100, b 无效则 NaN。"""
    if b is None or b == 0 or math.isnan(b) or math.isnan(a):
        return _NAN
    return (a / b - 1.0) * 100.0


def compute_fields(bars: List[dict]) -> Dict[str, List[float]]:
    """计算 FIELD_CATALOG 所有字段, 每个字段是与 bars 等长、按索引对齐的序列。

    纯函数, 便于单测;仅用 ≤i 数据(running-max/均线/RSI 均无未来信息)。
    """
    closes = [float(b.get("close", 0) or 0) for b in bars]
    vols = [float(b.get("volume", 0) or 0) for b in bars]
    n = len(bars)

    ma5, ma10, ma20, ma60 = (_sma(closes, p) for p in (5, 10, 20, 60))
    vol_ma5 = _sma(vols, 5)
    ema12, ema26 = _ema(closes, 12), _ema(closes, 26)
    dif = [ema12[i] - ema26[i] for i in range(n)] if n else []
    dea = _ema(dif, 9) if dif else []

    # 距区间高点回撤: 用 running max(到 i 为止), 无未来信息。
    run_max: List[float] = []
    cur = _NAN
    for c in closes:
        cur = c if math.isnan(cur) else max(cur, c)
        run_max.append(cur)

    f: Dict[str, List[float]] = {
        "close": closes,
        "pct_change": [
            _NAN if i == 0 or closes[i - 1] == 0 else (closes[i] / closes[i - 1] - 1) * 100 for i in range(n)
        ],
        "rsi": _rsi_series(closes, 14),
        "macd_hist": [(dif[i] - dea[i]) * 2 if i < len(dea) else _NAN for i in range(n)],
        "dif": dif,
        "dea": dea,
        "vol_ratio": [_NAN if math.isnan(vol_ma5[i]) or vol_ma5[i] == 0 else vols[i] / vol_ma5[i] for i in range(n)],
        "close_vs_ma5_pct": [_safe_div_pct(closes[i], ma5[i]) for i in range(n)],
        "close_vs_ma20_pct": [_safe_div_pct(closes[i], ma20[i]) for i in range(n)],
        "close_vs_ma60_pct": [_safe_div_pct(closes[i], ma60[i]) for i in range(n)],
        "ma5_vs_ma20_pct": [_safe_div_pct(ma5[i], ma20[i]) for i in range(n)],
        "ma10_vs_ma20_pct": [_safe_div_pct(ma10[i], ma20[i]) for i in range(n)],
        "drawdown_from_high_pct": [_safe_div_pct(closes[i], run_max[i]) for i in range(n)],
    }
    return f


def _eval_rules(rules: List[dict], ctx: Dict[str, float], logic: str) -> bool:
    """对一根 bar 的字段上下文评估一组规则。

    无效字段/NaN 视为该条不成立;and 全真、or 任一真。空规则 → False。
    """
    valid = []
    for r in rules:
        field = r.get("field")
        op = _OPS.get(str(r.get("op", "")))
        if field not in ctx or op is None:
            valid.append(False)
            continue
        val = ctx[field]
        try:
            threshold = float(r.get("value"))
        except (TypeError, ValueError):
            valid.append(False)
            continue
        if val is None or math.isnan(val):
            valid.append(False)
        else:
            valid.append(op(val, threshold))
    if not valid:
        return False
    return all(valid) if logic == "and" else any(valid)


class CustomRuleStrategy(BaseStrategy):
    """低代码规则策略: 字段+操作符+阈值组合买卖信号。"""

    name = "custom_rule"
    description = "低代码自定义规则: 字段+操作符+阈值组合信号(前端可视化编辑)"
    default_params: dict[str, Any] = {
        "buy_rules": [],
        "sell_rules": [],
        "logic": "and",
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        buy_rules = self.params.get("buy_rules") or []
        sell_rules = self.params.get("sell_rules") or []
        logic = str(self.params.get("logic", "and")).lower()
        if logic not in ("and", "or"):
            logic = "and"

        fields = compute_fields(bars)
        signals: list[Signal] = []
        for i, bar in enumerate(bars):
            ctx = {k: series[i] for k, series in fields.items()}
            sym = bar.get("symbol", "")
            # 空规则:与 bars 等长的 hold(引擎侧等同无信号),不破坏长度契约。
            if not buy_rules and not sell_rules:
                signals.append(Signal("hold", sym, reason="无规则"))
            elif _eval_rules(buy_rules, ctx, logic):
                shares = self._calc_shares(bar.get("close", 0), portfolio_state)
                signals.append(Signal("buy", sym, shares=shares, reason="规则买入触发"))
            elif _eval_rules(sell_rules, ctx, logic):
                signals.append(Signal("sell", sym, reason="规则卖出触发"))
            else:
                signals.append(Signal("hold", sym, reason="无信号"))
        assert len(signals) == len(bars)
        return signals


StrategyRegistry.register(CustomRuleStrategy.name, CustomRuleStrategy)
