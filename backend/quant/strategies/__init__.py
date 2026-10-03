"""Strategy package: one file per strategy, auto-discovered on first registry use.

To add a strategy, drop a new module in this package that defines a
``BaseStrategy`` subclass and calls ``StrategyRegistry.register(...)`` at import
time — it will appear in ``/api/quant/strategies`` with no central edit.

This package replaces the legacy monolithic ``strategies.py``. The public names
that ``backend.quant.__init__`` and ``engine.py`` import are re-exported here so
existing call sites keep working unchanged.
"""

from .base import BaseStrategy, Signal, StrategyRegistry

# Concrete strategies are imported here so they are registered when the package
# is imported (and also picked up by the registry's own auto-discovery).
from .macd_momentum import MACDMomentumStrategy  # noqa: F401
from .ma_crossover import MAStrategy  # noqa: F401
from .rsi_reversal import RSIStrategy  # noqa: F401
from .boll_break import BollingerBreakStrategy  # noqa: F401
from .momentum_topn import MomentumStrategy  # noqa: F401
from .dip_reversal import DipReversalStrategy  # noqa: F401
from .volume_break import VolumeBreakStrategy  # noqa: F401
from .turtle import TurtleBreakoutStrategy  # noqa: F401
from .chanlun_structure import ChanlunStructureStrategy  # noqa: F401

__all__ = [
    "BaseStrategy",
    "Signal",
    "StrategyRegistry",
    "MACDMomentumStrategy",
    "MAStrategy",
    "RSIStrategy",
    "BollingerBreakStrategy",
    "MomentumStrategy",
    "DipReversalStrategy",
    "VolumeBreakStrategy",
    "TurtleBreakoutStrategy",
    "ChanlunStructureStrategy",
]
