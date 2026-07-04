"""Strategy base classes, signals, and the auto-discovering registry.

Each strategy lives in its own module under this package and registers itself
on import (see :func:`StrategyRegistry.register`). The package ``__init__``
imports every ``_strategy`` module so dropping a new file in the directory is
enough to make it appear in ``/api/quant/strategies`` — no central edit needed
(the same pattern used by ``backend.providers``).
"""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from typing import Any


class Signal:
    """A trading signal."""

    def __init__(self, action: str, symbol: str, shares: int = 0, reason: str = ""):
        self.action = action  # "buy", "sell", "hold"
        self.symbol = symbol
        self.shares = shares
        self.reason = reason

    def __repr__(self) -> str:
        return f"Signal({self.action}, {self.symbol}, shares={self.shares})"


class BaseStrategy(ABC):
    """Abstract base class for strategies.

    Subclasses set the class attributes ``name`` / ``description`` /
    ``default_params`` and implement :meth:`generate_signals`. They are expected
    to call ``StrategyRegistry.register(cls.name, cls)`` at module import time so
    that auto-discovery picks them up.
    """

    name: str = "base"
    description: str = ""
    default_params: dict[str, Any] = {}

    def __init__(self, params: dict[str, Any] | None = None):
        self.params = {**self.default_params, **(params or {})}

    @abstractmethod
    def generate_signals(self, bars: list[dict], portfolio_state: dict[str, Any] | None = None) -> list[Signal]:
        """Generate trading signals from price bars.

        Args:
            bars: List of OHLCV dicts with keys: date, open, high, low, close, volume
            portfolio_state: Optional current portfolio state for context

        Returns:
            List of Signal objects
        """
        ...

    # ------------------------------------------------------------------
    # Shared indicator helpers (used by most technical strategies)
    # ------------------------------------------------------------------

    def _closes(self, bars: list[dict]) -> list[float]:
        return [b["close"] for b in bars]

    def _volumes(self, bars: list[dict]) -> list[float]:
        return [float(b.get("volume", 0)) for b in bars]

    @staticmethod
    def _sma(values: list[float], period: int) -> list[float]:
        result = []
        for i in range(len(values)):
            if i < period - 1:
                result.append(float("nan"))
            else:
                result.append(sum(values[i - period + 1 : i + 1]) / period)
        return result

    @staticmethod
    def _ema(values: list[float], period: int) -> list[float]:
        if not values:
            return []
        result = [values[0]]
        multiplier = 2.0 / (period + 1)
        for i in range(1, len(values)):
            result.append(values[i] * multiplier + result[-1] * (1 - multiplier))
        return result

    def _calc_shares(self, price: float, state: dict[str, Any] | None) -> int:
        """Default lot-sizing helper: budget a configurable % of equity, round
        to the nearest 100-share lot (A-share minimum trading unit)."""
        if not state or price <= 0:
            return 0
        equity = state.get("equity", 100000)
        budget = equity * self.params.get("position_size_pct", 20) / 100
        return max(0, int(budget / price / 100) * 100)


class StrategyRegistry:
    """Registry for built-in and custom strategies.

    Strategies self-register on import; :func:`_autodiscover` imports every
    sibling ``_strategy`` module so a new file under this package is picked up
    automatically.
    """

    _strategies: dict[str, type[BaseStrategy]] = {}

    @classmethod
    def register(cls, name: str, strategy_class: type[BaseStrategy]) -> None:
        cls._strategies[name] = strategy_class

    @classmethod
    def get(cls, name: str) -> type[BaseStrategy] | None:
        cls._autodiscover()
        return cls._strategies.get(name)

    @classmethod
    def list_strategies(cls) -> list[dict[str, Any]]:
        cls._autodiscover()
        return [
            {
                "name": name,
                "description": s.description,
                "default_params": s.default_params,
            }
            for name, s in cls._strategies.items()
        ]

    @classmethod
    def create(cls, name: str, params: dict[str, Any] | None = None) -> BaseStrategy | None:
        strategy_class = cls.get(name)
        if strategy_class:
            return strategy_class(params)
        return None

    _discovered = False

    @classmethod
    def _autodiscover(cls) -> None:
        """Import every module in this package so strategies self-register.

        Runs once; idempotent. Imports the package's own modules by traversing
        its ``__path__`` rather than a hardcoded list, so new files need no edit.
        """
        if cls._discovered:
            return
        cls._discovered = True
        # This module lives at ``backend.quant.strategies.base``; the package to
        # scan is ``backend.quant.strategies`` (one level up).
        package_name = __name__.rsplit(".base", 1)[0] if __name__.endswith(".base") else __name__
        try:
            package = importlib.import_module(package_name)
        except Exception:
            return
        package_path = getattr(package, "__path__", None)
        if not package_path:
            return
        for _finder, modname, _ispkg in pkgutil.iter_modules(package_path):
            # Skip the base module itself; only load concrete strategy modules.
            if modname == "base":
                continue
            try:
                importlib.import_module(f"{package_name}.{modname}")
            except Exception:
                # A broken strategy module must not break the registry; the
                # healthy ones still register. (Errors surface in tests.)
                continue
