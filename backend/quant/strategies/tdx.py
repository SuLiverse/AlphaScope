"""通达信(TDX)公式策略 — 把用户 TDX 公式编译成买卖信号回测。

复用 `backend.quant.tdx_compiler` 把公式求值成逐 bar 买/卖布尔序列,再按既有
策略约定逐 bar 发 Signal(买入用 _calc_shares 定仓)。不新建引擎、防未来函数。
坏公式 → 无信号(回测 0 交易),失败安全。
"""

from __future__ import annotations

from typing import Any

from .base import BaseStrategy, Signal, StrategyRegistry


class TdxStrategy(BaseStrategy):
    """通达信公式策略: ENTERLONG/EXITLONG(或 BUY/SELL)条件编译回测。"""

    name = "tdx"
    description = "通达信(TDX)公式: 编译 ENTERLONG/EXITLONG 条件为买卖信号(需传 formula 参数)"
    default_params: dict[str, Any] = {
        "formula": "",
        "position_size_pct": 20,
    }

    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        formula = str(self.params.get("formula") or "").strip()
        if not formula or not bars:
            return []

        from ..tdx_compiler import evaluate_formula

        result = evaluate_formula(formula, bars)
        if not result.ok:
            # 坏公式:不产生任何信号(失败安全,绝不伪造交易)。
            return []

        buy, sell = result.buy, result.sell
        signals: list[Signal] = []
        for i, bar in enumerate(bars):
            sym = bar.get("symbol", "")
            if i < len(buy) and buy[i]:
                shares = self._calc_shares(bar.get("close", 0), portfolio_state)
                signals.append(Signal("buy", sym, shares=shares, reason="TDX 买入信号"))
            elif i < len(sell) and sell[i]:
                signals.append(Signal("sell", sym, reason="TDX 卖出信号"))
            else:
                signals.append(Signal("hold", sym, reason="无信号"))
        return signals


StrategyRegistry.register(TdxStrategy.name, TdxStrategy)
