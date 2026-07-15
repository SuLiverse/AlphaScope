"""
Model Registry: 模型注册与管理增强。

职责：
- 多 Key 轮询
- Token 预算/配额管理
- 模型能力标签
- 成本分配

架构文档要求的模型网关增强功能。
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_BUDGET_PATH_LOCKS: dict[Path, threading.RLock] = {}
_BUDGET_PATH_LOCKS_GUARD = threading.Lock()


def _today_key() -> str:
    return date.today().isoformat()


def _month_key() -> str:
    return _today_key()[:7]


def _budget_state_path() -> Optional[Path]:
    if os.getenv("ALPHASCOPE_BUDGET_PERSIST_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        return None
    override = os.getenv("ALPHASCOPE_BUDGET_STATE_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    try:
        from backend.project_paths import DATA_DIR

        return DATA_DIR / "runtime" / "model_budget.json"
    except Exception:
        return Path("data/runtime/model_budget.json")


def _budget_process_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _BUDGET_PATH_LOCKS_GUARD:
        return _BUDGET_PATH_LOCKS.setdefault(resolved, threading.RLock())


@contextmanager
def _budget_file_lock(path: Optional[Path]):
    """Serialize a budget read-modify-write across registry instances and processes."""
    if path is None:
        yield
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with _budget_process_lock(path), lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)

        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@dataclass
class ModelCapability:
    """模型能力标签"""

    text: bool = True
    vision: bool = False
    tool_call: bool = False
    json_mode: bool = False
    embedding: bool = False
    reasoning: bool = False


@dataclass
class TokenBudget:
    """Token 预算"""

    daily_limit: int = 1000000  # 每日 token 限制
    monthly_limit: int = 30000000  # 每月 token 限制
    used_today: int = 0
    used_this_month: int = 0
    cost_limit_usd: float = 100.0  # 每日成本限制（美元）
    cost_today_usd: float = 0.0
    day_key: str = field(default_factory=_today_key)
    month_key: str = field(default_factory=_month_key)


@dataclass
class KeyPool:
    """Key 池（多 Key 轮询）"""

    provider: str
    keys: List[str] = field(default_factory=list)
    current_index: int = 0
    failed_keys: Dict[str, float] = field(default_factory=dict)  # key -> failed_at

    def get_next_key(self) -> str:
        """获取下一个可用 Key（轮询）"""
        if not self.keys:
            return ""

        # 跳过失败的 Key（5 分钟冷却）
        now = time.time()
        for _ in range(len(self.keys)):
            key = self.keys[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.keys)

            failed_at = self.failed_keys.get(key, 0)
            if now - failed_at > 300:  # 5 分钟冷却
                return key

        # 所有 Key 都在冷却，返回第一个
        return self.keys[0]

    def mark_failed(self, key: str):
        """标记 Key 为失败"""
        self.failed_keys[key] = time.time()

    def mark_success(self, key: str):
        """标记 Key 为成功"""
        self.failed_keys.pop(key, None)


class ModelRegistry:
    """模型注册中心"""

    def __init__(self):
        self._capabilities: Dict[str, ModelCapability] = {}
        self._key_pools: Dict[str, KeyPool] = {}
        self._budgets: Dict[str, TokenBudget] = {}
        self._usage: Dict[str, Dict[str, int]] = defaultdict(lambda: {"input": 0, "output": 0, "cost": 0})
        self._budget_lock = threading.RLock()
        self._budget_path = _budget_state_path()

        self._register_default_capabilities()

    def _register_default_capabilities(self):
        """注册默认模型能力"""
        self._capabilities = {
            "deepseek-chat": ModelCapability(text=True, json_mode=True),
            "claude-sonnet-4-5": ModelCapability(
                text=True, vision=True, tool_call=True, json_mode=True, reasoning=True
            ),
            "claude-opus-4-7": ModelCapability(text=True, vision=True, tool_call=True, json_mode=True, reasoning=True),
            "gpt-5.2": ModelCapability(text=True, vision=True, tool_call=True, json_mode=True, reasoning=True),
            "mimo-v2.5-pro": ModelCapability(text=True),
            "deepseek-v4-flash": ModelCapability(text=True, json_mode=True),
        }

    def register_capability(self, model: str, cap: ModelCapability):
        """注册模型能力"""
        self._capabilities[model] = cap

    def get_capability(self, model: str) -> ModelCapability:
        """获取模型能力"""
        return self._capabilities.get(model, ModelCapability())

    def supports_vision(self, model: str) -> bool:
        """检查模型是否支持视觉"""
        return self.get_capability(model).vision

    def supports_tool_call(self, model: str) -> bool:
        """检查模型是否支持工具调用"""
        return self.get_capability(model).tool_call

    # ============== 多 Key 轮询 ==============

    def register_key_pool(self, provider: str, keys: List[str]):
        """注册 Key 池"""
        self._key_pools[provider] = KeyPool(provider=provider, keys=keys)

    def get_key(self, provider: str) -> str:
        """获取 Provider 的下一个可用 Key"""
        pool = self._key_pools.get(provider)
        if pool:
            return pool.get_next_key()
        # 从环境变量获取单个 Key
        env_key = os.getenv(f"{provider.upper()}_API_KEY", "")
        return env_key

    def report_key_result(self, provider: str, key: str, success: bool):
        """报告 Key 使用结果"""
        pool = self._key_pools.get(provider)
        if pool:
            if success:
                pool.mark_success(key)
            else:
                pool.mark_failed(key)

    # ============== Token 预算 ==============

    def _read_budget_state(self) -> dict[str, Any]:
        path = self._budget_path
        if path is None or not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to read budget state from %s: %s", path, exc)
            return {}

    def _persist_budget_state(self, existing: Optional[dict[str, Any]] = None) -> None:
        path = self._budget_path
        if path is None:
            return
        payload = dict(existing or {})
        persisted_budgets = dict(payload.get("budgets") or {})
        persisted_budgets.update(
            {
                scope: {
                    "used_today": budget.used_today,
                    "used_this_month": budget.used_this_month,
                    "cost_today_usd": budget.cost_today_usd,
                    "day_key": budget.day_key,
                    "month_key": budget.month_key,
                }
                for scope, budget in self._budgets.items()
            }
        )
        payload.update({"version": 1, "budgets": persisted_budgets})
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to persist budget state to %s: %s", path, exc)

    @staticmethod
    def _restore_budget_usage(budget: TokenBudget, state: Any) -> None:
        if not isinstance(state, dict):
            return
        budget.day_key = str(state.get("day_key") or budget.day_key)
        budget.month_key = str(state.get("month_key") or budget.month_key)
        if budget.day_key == _today_key():
            budget.used_today = max(0, int(state.get("used_today") or 0))
            budget.cost_today_usd = max(0.0, float(state.get("cost_today_usd") or 0.0))
        if budget.month_key == _month_key():
            budget.used_this_month = max(0, int(state.get("used_this_month") or 0))

    @staticmethod
    def _rollover_budget(budget: TokenBudget) -> bool:
        changed = False
        today = _today_key()
        month = _month_key()
        if budget.month_key != month:
            budget.used_this_month = 0
            budget.month_key = month
            changed = True
        if budget.day_key != today:
            budget.used_today = 0
            budget.cost_today_usd = 0.0
            budget.day_key = today
            changed = True
        return changed

    def set_budget(self, scope: str, budget: TokenBudget, *, restore: bool = False):
        """设置 Token 预算"""
        with self._budget_lock:
            with _budget_file_lock(self._budget_path):
                persisted = self._read_budget_state()
                if restore:
                    state = (persisted.get("budgets") or {}).get(scope)
                    self._restore_budget_usage(budget, state)
                self._rollover_budget(budget)
                self._budgets[scope] = budget
                self._persist_budget_state(persisted)

    def check_budget(self, scope: str = "global") -> Dict[str, Any]:
        """检查预算是否充足"""
        with self._budget_lock:
            budget = self._budgets.get(scope)
            if not budget:
                return {"ok": True, "message": "无预算限制"}
            with _budget_file_lock(self._budget_path):
                persisted = self._read_budget_state()
                state = (persisted.get("budgets") or {}).get(scope)
                self._restore_budget_usage(budget, state)
                if self._rollover_budget(budget):
                    self._persist_budget_state(persisted)

            if budget.used_today >= budget.daily_limit:
                return {
                    "ok": False,
                    "message": f"已达到每日 Token 限制 ({budget.daily_limit:,})",
                    "used": budget.used_today,
                    "limit": budget.daily_limit,
                }

            if budget.cost_today_usd >= budget.cost_limit_usd:
                return {
                    "ok": False,
                    "message": f"已达到每日成本限制 (${budget.cost_limit_usd:.2f})",
                    "cost": budget.cost_today_usd,
                    "limit": budget.cost_limit_usd,
                }

            if budget.used_this_month >= budget.monthly_limit:
                return {
                    "ok": False,
                    "message": f"已达到每月 Token 限制 ({budget.monthly_limit:,})",
                    "used": budget.used_this_month,
                    "limit": budget.monthly_limit,
                }

            token_ratio = (budget.used_today / budget.daily_limit) if budget.daily_limit else 0.0
            cost_ratio = (budget.cost_today_usd / budget.cost_limit_usd) if budget.cost_limit_usd else 0.0
            used_ratio = max(token_ratio, cost_ratio)
            return {
                "ok": True,
                "remaining_tokens": budget.daily_limit - budget.used_today,
                "remaining_cost": budget.cost_limit_usd - budget.cost_today_usd,
                "used_ratio": round(used_ratio, 4),
                "used_today": budget.used_today,
                "daily_limit": budget.daily_limit,
                "cost_today_usd": round(budget.cost_today_usd, 4),
                "cost_limit_usd": budget.cost_limit_usd,
            }

    def record_usage(self, model: str, input_tokens: int, output_tokens: int, cost_usd: float = 0):
        """记录使用量"""
        with self._budget_lock:
            self._usage[model]["input"] += input_tokens
            self._usage[model]["output"] += output_tokens
            self._usage[model]["cost"] += int(cost_usd * 1000000)  # 微美元
            with _budget_file_lock(self._budget_path):
                persisted = self._read_budget_state()
                persisted_budgets = persisted.get("budgets") or {}

                # Rebase on the latest persisted counters before applying this request.
                for scope, budget in self._budgets.items():
                    self._restore_budget_usage(budget, persisted_budgets.get(scope))
                    self._rollover_budget(budget)
                    budget.used_today += input_tokens + output_tokens
                    budget.used_this_month += input_tokens + output_tokens
                    budget.cost_today_usd += cost_usd
                self._persist_budget_state(persisted)

    def get_usage_summary(self) -> Dict[str, Any]:
        """获取使用量摘要"""
        with self._budget_lock:
            with _budget_file_lock(self._budget_path):
                persisted = self._read_budget_state()
                persisted_budgets = persisted.get("budgets") or {}
                changed = False
                for scope, budget in self._budgets.items():
                    self._restore_budget_usage(budget, persisted_budgets.get(scope))
                    changed = self._rollover_budget(budget) or changed
                if changed:
                    self._persist_budget_state(persisted)
            return {
                "by_model": {
                    model: {
                        "input_tokens": usage["input"],
                        "output_tokens": usage["output"],
                        "cost_usd": round(usage["cost"] / 1000000, 6),
                    }
                    for model, usage in self._usage.items()
                },
                "budgets": {
                    scope: {
                        "daily_limit": b.daily_limit,
                        "used_today": b.used_today,
                        "cost_limit": b.cost_limit_usd,
                        "cost_today": round(b.cost_today_usd, 4),
                        "day": b.day_key,
                        "month": b.month_key,
                    }
                    for scope, b in self._budgets.items()
                },
            }


# 单例
_registry: Optional[ModelRegistry] = None


def ensure_default_budget(registry: Optional[ModelRegistry] = None) -> TokenBudget:
    """武装全局预算(仅当尚未 set_budget)。环境变量可覆盖:

    ALPHASCOPE_DAILY_TOKEN_LIMIT (默认 1_000_000)
    ALPHASCOPE_DAILY_COST_USD (默认 20)
    ALPHASCOPE_BUDGET_DISABLED=1 则设极大限额
    """
    reg = registry or get_model_registry()
    if "global" in reg._budgets:
        return reg._budgets["global"]
    if os.getenv("ALPHASCOPE_BUDGET_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        budget = TokenBudget(daily_limit=10**12, monthly_limit=10**15, cost_limit_usd=1e9)
    else:
        try:
            daily = int(os.getenv("ALPHASCOPE_DAILY_TOKEN_LIMIT", "1000000"))
        except ValueError:
            daily = 1_000_000
        try:
            cost = float(os.getenv("ALPHASCOPE_DAILY_COST_USD", "20"))
        except ValueError:
            cost = 20.0
        budget = TokenBudget(daily_limit=max(1000, daily), cost_limit_usd=max(0.5, cost))
    reg.set_budget("global", budget, restore=True)
    logger.info(
        "Token budget armed: daily_tokens=%s cost_usd=%s",
        budget.daily_limit,
        budget.cost_limit_usd,
    )
    return budget


def get_model_registry() -> ModelRegistry:
    """获取全局模型注册中心"""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
        try:
            ensure_default_budget(_registry)
        except Exception as exc:  # noqa: BLE001
            logger.debug("default budget arm skipped: %s", exc)
    return _registry
