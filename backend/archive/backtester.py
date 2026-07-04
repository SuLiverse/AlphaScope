"""
Backtester: 后验验证框架。

职责：
- 追踪已归档分析报告的后续表现
- 计算 3/5/10/20 日收益率
- 记录最大回撤
- 监控 invalid_if 触发
- 按 Agent/专家团/模型组合统计表现

这是架构文档要求的"核心壁垒"：不只是让 AI 给建议，
而是持续评估"哪个 Agent/专家团更靠谱"。
"""

import json
import time
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

try:
    from project_paths import CACHE_DIR
except ImportError:
    from backend.project_paths import CACHE_DIR

TRACKING_PATH = CACHE_DIR / "backtest_tracking.jsonl"


@dataclass
class TrackedDecision:
    """被追踪的投资决策"""

    decision_id: str
    symbol: str
    stock_name: str
    signal: str  # 买入/卖出/观望
    confidence: int
    price_at_decision: float
    timestamp: float
    mode: str = ""
    agent_signals: Dict[str, str] = field(default_factory=dict)
    invalid_if: str = ""
    # 后验数据
    price_3d: float = 0.0
    price_5d: float = 0.0
    price_10d: float = 0.0
    price_20d: float = 0.0
    max_drawdown: float = 0.0
    invalid_triggered: bool = False
    evaluated: bool = False


class Backtester:
    """后验验证器"""

    def __init__(self):
        self._tracking_path = TRACKING_PATH
        self._decisions: List[TrackedDecision] = []
        self._load_tracking()

    def _load_tracking(self):
        """加载追踪数据"""
        if not self._tracking_path.exists():
            return
        try:
            for line in self._tracking_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    data = json.loads(line)
                    self._decisions.append(TrackedDecision(**data))
        except Exception:
            pass

    def _save_tracking(self):
        """保存追踪数据"""
        try:
            self._tracking_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._tracking_path, "w", encoding="utf-8") as f:
                for d in self._decisions:
                    f.write(
                        json.dumps(
                            {
                                "decision_id": d.decision_id,
                                "symbol": d.symbol,
                                "stock_name": d.stock_name,
                                "signal": d.signal,
                                "confidence": d.confidence,
                                "price_at_decision": d.price_at_decision,
                                "timestamp": d.timestamp,
                                "mode": d.mode,
                                "agent_signals": d.agent_signals,
                                "invalid_if": d.invalid_if,
                                "price_3d": d.price_3d,
                                "price_5d": d.price_5d,
                                "price_10d": d.price_10d,
                                "price_20d": d.price_20d,
                                "max_drawdown": d.max_drawdown,
                                "invalid_triggered": d.invalid_triggered,
                                "evaluated": d.evaluated,
                            }
                        )
                        + "\n"
                    )
        except Exception:
            pass

    def track_decision(
        self,
        decision_id: str,
        symbol: str,
        stock_name: str,
        signal: str,
        confidence: int,
        price: float,
        mode: str = "",
        agent_signals: Optional[Dict[str, str]] = None,
        invalid_if: str = "",
    ):
        """记录一个待追踪的决策"""
        d = TrackedDecision(
            decision_id=decision_id,
            symbol=symbol,
            stock_name=stock_name,
            signal=signal,
            confidence=confidence,
            price_at_decision=price,
            timestamp=time.time(),
            mode=mode,
            agent_signals=agent_signals or {},
            invalid_if=invalid_if,
        )
        self._decisions.append(d)
        self._save_tracking()

    def update_prices(self, symbol: str, current_price: float):
        """更新指定股票的当前价格，计算收益率"""
        now = time.time()
        updated = False

        for d in self._decisions:
            if d.symbol != symbol or d.evaluated:
                continue

            days_elapsed = (now - d.timestamp) / 86400
            price_change = (current_price - d.price_at_decision) / d.price_at_decision * 100

            if d.price_3d == 0 and days_elapsed >= 3:
                d.price_3d = price_change
                updated = True
            if d.price_5d == 0 and days_elapsed >= 5:
                d.price_5d = price_change
                updated = True
            if d.price_10d == 0 and days_elapsed >= 10:
                d.price_10d = price_change
                updated = True
            if d.price_20d == 0 and days_elapsed >= 20:
                d.price_20d = price_change
                d.evaluated = True
                updated = True

            # 更新最大回撤
            if price_change < d.max_drawdown:
                d.max_drawdown = price_change
                updated = True

        if updated:
            self._save_tracking()

    def get_performance_stats(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """获取表现统计"""
        decisions = self._decisions
        if mode:
            decisions = [d for d in decisions if d.mode == mode]

        evaluated = [d for d in decisions if d.evaluated]
        if not evaluated:
            return {
                "total": len(decisions),
                "evaluated": 0,
                "message": "尚无已评估的决策",
            }

        # 按信号分组统计
        buy_decisions = [d for d in evaluated if d.signal == "买入"]
        sell_decisions = [d for d in evaluated if d.signal == "卖出"]
        hold_decisions = [d for d in evaluated if d.signal == "观望"]

        def avg_return(decs, period):
            vals = [getattr(d, f"price_{period}d", 0) for d in decs if getattr(d, f"price_{period}d", 0) != 0]
            return round(sum(vals) / len(vals), 2) if vals else 0

        return {
            "total": len(decisions),
            "evaluated": len(evaluated),
            "buy_signals": {
                "count": len(buy_decisions),
                "avg_return_3d": avg_return(buy_decisions, 3),
                "avg_return_5d": avg_return(buy_decisions, 5),
                "avg_return_10d": avg_return(buy_decisions, 10),
                "avg_return_20d": avg_return(buy_decisions, 20),
                "accuracy_5d": round(
                    sum(1 for d in buy_decisions if d.price_5d > 0) / max(len(buy_decisions), 1) * 100,
                    1,
                ),
            },
            "sell_signals": {
                "count": len(sell_decisions),
                "avg_return_3d": avg_return(sell_decisions, 3),
                "avg_return_5d": avg_return(sell_decisions, 5),
            },
            "hold_signals": {
                "count": len(hold_decisions),
            },
        }

    def get_agent_accuracy(self) -> Dict[str, Dict[str, Any]]:
        """按 Agent 统计准确率"""
        evaluated = [d for d in self._decisions if d.evaluated]
        if not evaluated:
            return {}

        agent_stats = {}
        for d in evaluated:
            for agent_key, signal in d.agent_signals.items():
                if agent_key not in agent_stats:
                    agent_stats[agent_key] = {"correct": 0, "total": 0, "returns": []}

                stats = agent_stats[agent_key]
                stats["total"] += 1

                # 判断是否正确：买入后涨 = 正确，卖出后跌 = 正确
                if signal == "买入" and d.price_5d > 0:
                    stats["correct"] += 1
                elif signal == "卖出" and d.price_5d < 0:
                    stats["correct"] += 1
                elif signal == "观望":
                    stats["correct"] += 1  # 观望默认正确

                if d.price_5d != 0:
                    stats["returns"].append(d.price_5d)

        # 计算准确率
        result = {}
        for agent_key, stats in agent_stats.items():
            result[agent_key] = {
                "accuracy": round(stats["correct"] / max(stats["total"], 1) * 100, 1),
                "total_decisions": stats["total"],
                "avg_return": round(sum(stats["returns"]) / max(len(stats["returns"]), 1), 2),
            }

        return result

    def get_pending_evaluations(self) -> List[Dict[str, Any]]:
        """获取待评估的决策"""
        return [
            {
                "decision_id": d.decision_id,
                "symbol": d.symbol,
                "signal": d.signal,
                "price": d.price_at_decision,
                "days_elapsed": round((time.time() - d.timestamp) / 86400, 1),
            }
            for d in self._decisions
            if not d.evaluated
        ]


# 单例
_backtester: Optional[Backtester] = None


def get_backtester() -> Backtester:
    """获取全局后验验证器"""
    global _backtester
    if _backtester is None:
        _backtester = Backtester()
    return _backtester
