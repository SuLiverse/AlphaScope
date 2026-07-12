"""Trading Boundary / 交易边界 — No-Live-Order 的工程化执行.

AlphaScope 的核心合规红线是 **不连接真实券商下单链路、不自动执行交易**。
本模块把这条红线从 README 文字变成:

1. **可加载**: 从 ``config/legal_boundaries.yaml`` 读取边界标志。
2. **可断言**: 启动时校验所有 ``allow_live_*`` / ``allow_auto_*`` 标志为 False,
   否则立即抛 ``BoundaryViolation`` 拒绝启动。
3. **可扫描**: ``scan_forbidden_symbols()`` 静态扫描 ``backend/`` 源码,
   发现 ``submit_order`` / ``place_order`` 等被定义为函数/类/方法名时报告。
4. **可守卫**: ``assert_no_live_order(action)`` 供任何「接近交易」的代码路径
   在入口处显式自证, 双保险。

设计原则: 默认拒绝、失败安全、零例外。本模块 **绝不** 输出买卖指令,
只负责阻止越界。
"""

from __future__ import annotations

import ast
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from backend.project_paths import CONFIG_DIR

# 必须恒为 False 的标志 (改动即违背项目定位)。
# 这里的名字与 legal_boundaries.yaml 的键一一对应。
_MUST_BE_FALSE_FLAGS: tuple[str, ...] = (
    "allow_live_broker_order",
    "allow_llm_direct_order",
    "allow_auto_execution",
    "allow_real_api_secret_for_trading",
)

# 默认禁止的「已定义符号名」词表; 运行时从 yaml 覆盖。
FORBIDDEN_SYMBOL_NAMES: tuple[str, ...] = (
    "submit_order",
    "place_order",
    "execute_trade",
    "auto_trade",
    "live_gateway",
)

# 默认边界 (yaml 缺失/读失败时回落, 且仍保持 live 全部 False)。
_DEFAULT_FLAGS: dict[str, bool] = {
    "allow_paper_trading": True,
    "allow_backtest": True,
    "allow_manual_ticket_export": True,
    "allow_research_report": True,
    "allow_watchlist": True,
    "allow_live_broker_order": False,
    "allow_llm_direct_order": False,
    "allow_auto_execution": False,
    "allow_real_api_secret_for_trading": False,
}

_CONFIG_PATH = CONFIG_DIR / "legal_boundaries.yaml"


class BoundaryViolation(RuntimeError):
    """交易边界被违反 — 程序应拒绝启动或中止该代码路径。"""


@dataclass(frozen=True)
class TradingBoundary:
    """已加载的交易边界快照。不可变, 进程级缓存。"""

    flags: dict[str, bool] = field(default_factory=lambda: dict(_DEFAULT_FLAGS))
    forbidden_symbol_names: tuple[str, ...] = FORBIDDEN_SYMBOL_NAMES

    # ----- 查询 -----
    def is_allowed(self, capability: str) -> bool:
        """能力是否被边界允许。未知能力默认 False (默认拒绝)。"""
        return bool(self.flags.get(capability, False))

    @property
    def live_order_blocked(self) -> bool:
        """所有 live/auto 下单路径是否都被阻断。"""
        return all(self.flags.get(name) is False for name in _MUST_BE_FALSE_FLAGS)

    # ----- 校验 -----
    def assert_invariant(self) -> None:
        """启动期不变量: 所有 ``allow_live_*`` / ``allow_auto_*`` 必须为 False。"""
        for name in _MUST_BE_FALSE_FLAGS:
            if self.flags.get(name) is not False:
                raise BoundaryViolation(
                    f"交易边界违规: {name} 必须为 False, 当前为 {self.flags.get(name)!r}. "
                    f"AlphaScope 不连接真实券商下单链路, 不自动执行交易。"
                )

    def assert_no_live_order(self, action: str = "unknown") -> None:
        """运行期守卫: 任何接近实盘下单的代码路径应在入口处调用。"""
        if not self.live_order_blocked:
            raise BoundaryViolation(f"交易边界守卫触发 (action={action!r}): live-order 路径已被永久关闭。")
        # live_order_blocked == True 表示边界正常; 这里 *不* 抛错,
        # 因为调用本函数代表「自证这条路径不是 live order」。真正越界的是
        # 边界本身被改坏 (上面那段会抛)。
        return


# ----------------------------- 加载与缓存 -----------------------------

_boundary_cache: TradingBoundary | None = None
_lock = threading.Lock()


def get_boundary(reload: bool = False) -> TradingBoundary:
    """获取进程级单例边界。首次调用加载 yaml 并执行启动期断言。"""
    global _boundary_cache
    with _lock:
        if _boundary_cache is not None and not reload:
            return _boundary_cache
        boundary = _load_boundary()
        boundary.assert_invariant()  # 启动期硬断言
        _boundary_cache = boundary
        return boundary


def _load_boundary() -> TradingBoundary:
    """从 yaml 加载边界; 读失败回落到安全默认 (live 全 False)。"""
    flags = dict(_DEFAULT_FLAGS)
    forbidden = FORBIDDEN_SYMBOL_NAMES
    try:
        if _CONFIG_PATH.exists():
            raw = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8")) or {}
            for k, v in raw.items():
                if k == "forbidden_symbol_names":
                    forbidden = tuple(str(v) for v in v) if isinstance(v, list) else forbidden
                elif isinstance(v, bool):
                    flags[k] = v
    except (OSError, yaml.YAMLError):
        # 读失败: 保持安全默认, 不抛 (让系统能启动), 但 live 仍全部 False。
        pass
    return TradingBoundary(flags=flags, forbidden_symbol_names=forbidden)


def assert_no_live_order(action: str = "unknown") -> None:
    """便捷守卫: 等价于 ``get_boundary().assert_no_live_order(action)``。"""
    get_boundary().assert_no_live_order(action)


# ----------------------------- 静态扫描 -----------------------------


def scan_forbidden_symbols(
    root: Path | str | None = None,
    forbidden: tuple[str, ...] | None = None,
) -> list[tuple[Path, str, int]]:
    """静态扫描 ``backend/`` 下 .py 源码, 报告被定义为「禁止符号名」的位置。

    返回 [(file, name, lineno), ...]。用 AST 解析, 只看 *定义名* (函数/类/方法/
    AsyncFunction), 不误报字符串/变量/调用。

    用于 tests/security/test_no_live_order_path.py 与 CI。
    """
    boundary = get_boundary()
    forbidden_set = set(forbidden if forbidden is not None else boundary.forbidden_symbol_names)
    base = Path(root).resolve() if root else Path(__file__).resolve().parents[2] / "backend"

    findings: list[tuple[Path, str, int]] = []
    if not base.exists():
        return findings

    for py in base.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            name = getattr(node, "name", None)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and name in forbidden_set:
                findings.append((py, name, getattr(node, "lineno", 0)))
    return findings


def describe_capabilities() -> dict[str, Any]:
    """供 /api/integrations 等暴露当前边界概览 (供 UI「安全边界」面板)。"""
    b = get_boundary()
    return {
        "flags": dict(b.flags),
        "forbidden_symbol_names": list(b.forbidden_symbol_names),
        "live_order_blocked": b.live_order_blocked,
        "config_path": str(_CONFIG_PATH),
    }
