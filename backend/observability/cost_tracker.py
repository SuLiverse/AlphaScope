"""
Cost Tracker: Token 用量与成本追踪。

职责：
- 记录每次 LLM 调用的 token 用量
- 从 JSONL 日志文件加载历史记录（init 时）
- 按 agent/mode/model 维度统计
- 提供成本估算、当日成本、按模式成本查询
"""

import json
import time
import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from collections import defaultdict

try:
    from backend.project_paths import CACHE_DIR
except ImportError:
    from project_paths import CACHE_DIR  # type: ignore[no-redef]

COST_LOG_PATH = CACHE_DIR / "cost_log.jsonl"

# 每 1000 token 的成本（美元）
COST_PER_1K_TOKENS = {
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "claude-sonnet-4-5": {"input": 0.003, "output": 0.015},
    "claude-opus-4-7": {"input": 0.015, "output": 0.075},
    "gpt-5.2": {"input": 0.002, "output": 0.008},
    "mimo-v2.5-pro": {"input": 0.0001, "output": 0.0002},
    "deepseek-v4-flash": {"input": 0.00007, "output": 0.00014},
}


@dataclass
class CallRecord:
    """单次 LLM 调用记录"""

    timestamp: float
    agent_key: str
    model: str
    vendor: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    mode: str = ""
    conversation_id: str = ""


class CostTracker:
    """Token 成本追踪器"""

    def __init__(self):
        self._records: List[CallRecord] = []
        self._log_path = COST_LOG_PATH
        self._load_from_log()

    def _load_from_log(self):
        """从 JSONL 日志文件加载历史记录"""
        if not self._log_path.exists():
            return
        try:
            with open(self._log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        self._records.append(
                            CallRecord(
                                timestamp=entry.get("ts", 0),
                                agent_key=entry.get("agent", ""),
                                model=entry.get("model", ""),
                                vendor=entry.get("vendor", ""),
                                input_tokens=entry.get("in_tok", 0),
                                output_tokens=entry.get("out_tok", 0),
                                cost_usd=entry.get("cost", 0.0),
                                mode=entry.get("mode", ""),
                                conversation_id=entry.get("conv", ""),
                            )
                        )
                    except (json.JSONDecodeError, KeyError):
                        continue
        except Exception:
            pass

    def record_call(
        self,
        agent_key: str,
        model: str,
        vendor: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        mode: str = "",
        conversation_id: str = "",
    ):
        """记录一次 LLM 调用"""
        cost = self._estimate_cost(model, input_tokens, output_tokens)
        record = CallRecord(
            timestamp=time.time(),
            agent_key=agent_key,
            model=model,
            vendor=vendor,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            mode=mode,
            conversation_id=conversation_id,
        )
        self._records.append(record)
        self._append_to_log(record)

    def _estimate_cost(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """估算成本（美元）"""
        rates = COST_PER_1K_TOKENS.get(model, {"input": 0.001, "output": 0.002})
        return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1000

    def _append_to_log(self, record: CallRecord):
        """追加到日志文件"""
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(
                    json.dumps(
                        {
                            "ts": record.timestamp,
                            "agent": record.agent_key,
                            "model": record.model,
                            "vendor": record.vendor,
                            "in_tok": record.input_tokens,
                            "out_tok": record.output_tokens,
                            "cost": record.cost_usd,
                            "mode": record.mode,
                            "conv": record.conversation_id,
                        }
                    )
                    + "\n"
                )
        except Exception:
            pass

    def get_summary(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """获取成本摘要"""
        records = self._records
        if mode:
            records = [r for r in records if r.mode == mode]

        total_cost = sum(r.cost_usd for r in records)
        total_input = sum(r.input_tokens for r in records)
        total_output = sum(r.output_tokens for r in records)

        by_agent = defaultdict(float)
        by_model = defaultdict(float)
        for r in records:
            by_agent[r.agent_key] += r.cost_usd
            by_model[r.model] += r.cost_usd

        return {
            "total_calls": len(records),
            "total_cost_usd": round(total_cost, 6),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "by_agent": dict(by_agent),
            "by_model": dict(by_model),
        }

    def get_session_cost(self) -> float:
        """获取当前会话总成本"""
        return sum(r.cost_usd for r in self._records)

    def get_today_cost(self) -> Dict[str, Any]:
        """获取今日成本统计（按本地时区零点划分）"""
        today_start = (
            datetime.datetime.now()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .timestamp()
        )
        today_records = [r for r in self._records if r.timestamp >= today_start]

        total_cost = sum(r.cost_usd for r in today_records)
        total_input = sum(r.input_tokens for r in today_records)
        total_output = sum(r.output_tokens for r in today_records)

        by_model = defaultdict(float)
        for r in today_records:
            by_model[r.model] += r.cost_usd

        return {
            "date": datetime.date.today().isoformat(),
            "total_calls": len(today_records),
            "total_cost_usd": round(total_cost, 6),
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "by_model": dict(by_model),
        }

    def get_cost_by_mode(self, mode: Optional[str] = None) -> Dict[str, Any]:
        """按 mode 维度获取成本统计。

        如果指定 mode，返回该 mode 的详细统计；
        否则返回所有 mode 的汇总字典。
        """
        if mode is not None:
            filtered = [r for r in self._records if r.mode == mode]
            total_cost = sum(r.cost_usd for r in filtered)
            total_input = sum(r.input_tokens for r in filtered)
            total_output = sum(r.output_tokens for r in filtered)
            return {
                "mode": mode,
                "total_calls": len(filtered),
                "total_cost_usd": round(total_cost, 6),
                "total_input_tokens": total_input,
                "total_output_tokens": total_output,
            }

        # 汇总所有 mode
        by_mode: Dict[str, Dict[str, Any]] = defaultdict(
            lambda: {"calls": 0, "cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0}
        )
        for r in self._records:
            m = r.mode or "(no mode)"
            by_mode[m]["calls"] += 1
            by_mode[m]["cost_usd"] += r.cost_usd
            by_mode[m]["input_tokens"] += r.input_tokens
            by_mode[m]["output_tokens"] += r.output_tokens

        # 四舍五入
        result = {}
        for k, v in by_mode.items():
            v["cost_usd"] = round(v["cost_usd"], 6)
            result[k] = v
        return result


# 单例
_tracker: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """获取全局成本追踪器"""
    global _tracker
    if _tracker is None:
        _tracker = CostTracker()
    return _tracker
