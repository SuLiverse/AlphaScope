"""OpenBB Adapter — 全球金融数据路由器 (Phase 2 第二个真实 adapter).

OpenBB (MIT) 是开源金融数据平台, 聚合了 FMP / Polygon / Alpha Vantage / Yahoo /
FRED 等数十个数据源。本 adapter 把它接入 AlphaScope 的 Integration Registry,
补齐 AlphaScope 偏重 A 股的短板, 扩展到**美股 / ETF / 宏观 / 加密**等全球品种
(对应战略规划「OpenBBProvider 增强」「扩展美股、ETF、宏观」)。

设计要点 (延续项目「确定性 · 失败安全 · 可溯源」基线):
- **可选依赖 + 优雅降级**: ``openbb`` 用 import-guard 包裹, 没装不影响其余功能
  (healthcheck 报 UNAVAILABLE)。安装并配置至少一个 provider 凭证后即生效。
- **只读数据源**: OpenBB 只取数据, 无任何交易能力; ``allow_live_order=False``。
- **失败安全**: 凭证缺失 / 网络错误 / 字段不匹配 → 返回空列表 + DEGRADED, 不抛。
- **纯函数可单测**: ``normalize_ohlcv_df`` 把 OpenBB 返回的 dataframe (polars 或
  pandas, 各 provider 字段名略有差异) 归一化成 AlphaScope 标准 OHLCV dict,
  不依赖 openbb 即可单测。

合规: 本 adapter 仅检索历史行情数据, 不预测、不荐股、不构成投资建议。
"""

from __future__ import annotations

from typing import Any

# ----- 可选依赖: openbb 缺失时优雅降级 -----
try:
    from openbb import obb  # type: ignore[import-untyped]

    _OBB_AVAILABLE = True
except Exception:  # ImportError / 副作用失败都不致命
    obb = None  # type: ignore[assignment]
    _OBB_AVAILABLE = False

from backend.integrations.base import DataAdapter
from backend.integrations.schemas import (
    HealthStatus,
    IntegrationHealth,
    IntegrationMetadata,
    IntegrationMode,
    LicenseSafety,
)
from backend.integrations.registry import register

# OpenBB 各 provider 返回的字段名略有差异; 这里覆盖常见命名, 归一化时按优先级匹配。
_DATE_KEYS = ("date", "Date", "datetime", "timestamp", "time")
_OPEN_KEYS = ("open", "Open", "o")
_HIGH_KEYS = ("high", "High", "h")
_LOW_KEYS = ("low", "Low", "l")
_CLOSE_KEYS = ("close", "Close", "c", "adj_close", "adjClose")
_VOLUME_KEYS = ("volume", "Volume", "v")


# ============================================================
# 纯函数 (无需 openbb 即可单测)
# ============================================================


def _pick(row: Any, keys: tuple[str, ...], default: float = 0.0) -> float:
    """从 dict-like row 按优先级取第一个存在的键, 转 float; 失败返回 default。"""
    for k in keys:
        if hasattr(row, "get"):
            if k in row:
                try:
                    return float(row[k])
                except (TypeError, ValueError):
                    continue
        else:  # polars/pandas Series
            try:
                if k in getattr(row, "index", ()):  # type: ignore[operator]
                    return float(row[k])
            except (TypeError, ValueError, KeyError):
                continue
    return default


def _pick_date(row: Any) -> str:
    """取日期字段并归一化成字符串 (各 provider 口径不一, 统一成 str)。

    pandas 把 None 转成 NaN; 字符串 'nan'/'NaT'/'None' 也视为缺失。
    """
    for k in _DATE_KEYS:
        val = None
        if hasattr(row, "get"):
            if k in row:
                val = row[k]
        else:
            try:
                if k in getattr(row, "index", ()):  # type: ignore[operator]
                    val = row[k]
            except (TypeError, ValueError, KeyError):
                continue
        if val is None:
            continue
        s = str(val)
        if s.lower() in ("nan", "nat", "none", ""):
            continue
        return s
    return ""


def normalize_ohlcv_df(df: Any, symbol: str, market: str = "US") -> list[dict[str, Any]]:
    """把 OpenBB 返回的 dataframe 归一化成 AlphaScope 标准 OHLCV dict 列表。

    兼容 pandas / polars DataFrame, 以及各 provider 的字段名差异。
    纯函数, 失败安全: 空 df / 全缺字段 → 空列表。
    输出每条形如 {symbol, market, date, open, high, low, close, volume, source}。
    """
    if df is None:
        return []
    # 统一成迭代行: pandas / polars 都支持 .iterrows()
    iter_fn = getattr(df, "iterrows", None)
    if iter_fn is None:
        return []
    out: list[dict[str, Any]] = []
    for _, row in iter_fn():
        date = _pick_date(row)
        if not date:
            continue  # 无日期的行无意义, 跳过
        out.append(
            {
                "symbol": symbol,
                "market": market,
                "date": date,
                "open": _pick(row, _OPEN_KEYS),
                "high": _pick(row, _HIGH_KEYS),
                "low": _pick(row, _LOW_KEYS),
                "close": _pick(row, _CLOSE_KEYS),
                "volume": _pick(row, _VOLUME_KEYS),
                "source": "openbb",
            }
        )
    return out


def has_any_provider_credentials() -> bool:
    """探测是否配置了至少一个 OpenBB provider 凭证。

    OpenBB 大部分 provider 需要API key; 没配置时取数据会失败。本函数检查环境变量里
    常见的几个 (FMP/Polygon/AlphaVantage/Yahoo 不需要 key 但仍算可用)。
    纯函数, 不依赖 openbb 实例, 仅看环境变量。
    """
    import os

    cred_keys = (
        "OPENBB_API_KEY",
        "OPENBB_FMP_API_KEY",
        "OPENBB_POLYGON_API_KEY",
        "OPENBB_ALPHAVANTAGE_API_KEY",
        "OPENBB_TIINGO_API_KEY",
        "FMP_API_KEY",
        "POLYGON_API_KEY",
        "ALPHAVANTAGE_API_KEY",
    )
    return any(os.getenv(k) for k in cred_keys)


# ============================================================
# Adapter
# ============================================================


@register
class OpenbbAdapter(DataAdapter):
    """OpenBB 全球金融数据 adapter (Phase 2)。

    扩展 AlphaScope 到美股 / ETF / 宏观 / 加密等全球品种。只读数据源, 无任何交易能力。
    所需凭证通过环境变量配置; 缺失时 healthcheck 报 DEGRADED, 取数返回空。
    """

    NAME = "openbb"
    # CATEGORY 继承自 DataAdapter.DATA

    def _metadata(self) -> IntegrationMetadata:
        return IntegrationMetadata(
            name=self.NAME,
            category=self.CATEGORY,
            mode=IntegrationMode.PYTHON_ADAPTER,
            version="0.1.0",
            display_name="OpenBB 全球数据",
            description=(
                "开源金融数据平台, 聚合 FMP/Polygon/AlphaVantage/Yahoo/FRED 等数十源,"
                "扩展 AlphaScope 到美股/ETF/宏观/加密。只读数据源, 可选依赖, 缺失时降级。"
            ),
            homepage="https://github.com/OpenBB-finance/OpenBB",
            package="openbb",
            capabilities=[
                {
                    "name": "get_ohlcv",
                    "description": "取全球品种历史 OHLCV (美股/ETF/宏观等)",
                },
            ],
            license_name="MIT",
            license_safety=LicenseSafety.SAFE,
            code_copy_allowed=True,
            allow_live_order=False,
        )

    def healthcheck(self) -> IntegrationHealth:
        if not _OBB_AVAILABLE:
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.UNAVAILABLE,
                message="openbb 未安装。安装后生效: pip install openbb",
            )
        if not has_any_provider_credentials():
            return IntegrationHealth(
                name=self.NAME,
                status=HealthStatus.DEGRADED,
                message=(
                    "openbb 已安装但未检测到 provider 凭证 (OPENBB_FMP_API_KEY 等)。"
                    "Yahoo 等免 key 源仍可用, 但 FMP/Polygon 等需配置。"
                ),
            )
        return IntegrationHealth(
            name=self.NAME,
            status=HealthStatus.HEALTHY,
            message="openbb 就绪 (全球数据路由器, 已配置 provider 凭证)",
        )

    def get_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        **kw: Any,
    ) -> list[dict[str, Any]]:
        """取全球品种历史 OHLCV。

        参数:
        - symbol: 标的代码 (如 "AAPL" / "SPY" / "BTC-USD")
        - start / end: "YYYY-MM-DD"
        - market: "US"(默认) / "crypto" / ...
        - provider: 指定 OpenBB provider (默认让 OpenBB 自选, 如 "fmp"/"yfinance")

        失败安全: openbb 不可用 / 凭证缺失 / 网络错误 → 返回空列表, 不抛。
        本方法是 OpenBB 相对 A 股 provider 的差异化能力 (全球品种), 故单独实现。
        """
        if not _OBB_AVAILABLE:
            return []
        market = str(kw.get("market", "US"))
        provider = kw.get("provider")
        try:
            call = obb.equity.price.historical  # type: ignore[union-attr]
            kwargs: dict[str, Any] = {"start_date": start, "end_date": end}
            if provider:
                kwargs["provider"] = provider
            df = call(symbol, **kwargs).to_df()
            return normalize_ohlcv_df(df, symbol=symbol, market=market)
        except Exception:
            # 任何失败 (凭证/网络/字段/品种不支持) 都失败安全返回空
            return []
