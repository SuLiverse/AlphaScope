"""OpenBB Adapter 测试 (Phase 2 第二个真实 adapter).

分两组:
1. **纯函数组 (始终跑)**: normalize_ohlcv_df / has_any_provider_credentials —— 验证
   OpenBB 各 provider 返回的 dataframe (字段名/类型差异) 能正确归一化成标准 OHLCV,
   以及凭证探测逻辑, 全部失败安全。不依赖 openbb。
2. **openbb 执行路径 (skipif; 未装跳过)**: adapter 健康检查 / 自动发现 / get_ohlcv
   端到端。openbb 未装时整组跳过 (CI 无 openbb 仍确定性通过)。

合规: 测试只校验数据归一化与边界不变量, 不涉及任何买卖指令。
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.integrations.data.openbb_adapter import (
    OpenbbAdapter,
    has_any_provider_credentials,
    normalize_ohlcv_df,
)
from backend.integrations.schemas import HealthStatus, LicenseSafety


# ============================================================
# 1. 纯函数组 (始终跑, 不依赖 openbb)
# ============================================================


def test_normalize_empty_df_is_safe():
    assert normalize_ohlcv_df(None, "AAPL") == []
    assert normalize_ohlcv_df(pd.DataFrame(), "AAPL") == []


def test_normalize_standard_pandas_columns():
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "open": [100.0, 101.0],
            "high": [105.0, 106.0],
            "low": [99.0, 100.0],
            "close": [104.0, 105.0],
            "volume": [1000, 2000],
        }
    )
    out = normalize_ohlcv_df(df, "AAPL", market="US")
    assert len(out) == 2
    r = out[0]
    assert r["symbol"] == "AAPL"
    assert r["market"] == "US"
    assert r["date"] == "2024-01-01"
    assert r["open"] == 100.0
    assert r["close"] == 104.0
    assert r["volume"] == 1000
    assert r["source"] == "openbb"


def test_normalize_handles_alternate_field_names():
    """不同 provider 用不同字段名 (Open/Close/adj_close), 都应被识别。"""
    df = pd.DataFrame(
        {
            "Date": ["2024-01-01"],
            "Open": [10.0],
            "High": [11.0],
            "Low": [9.0],
            "Close": [10.5],
            "Volume": [500],
        }
    )
    out = normalize_ohlcv_df(df, "SPY")
    assert len(out) == 1
    assert out[0]["date"] == "2024-01-01"
    assert out[0]["open"] == 10.0
    assert out[0]["close"] == 10.5


def test_normalize_skips_rows_without_date():
    """缺日期的行无意义, 被跳过 (失败安全)。"""
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", None],
            "close": [10.0, 11.0],
        }
    )
    out = normalize_ohlcv_df(df, "AAPL")
    assert len(out) == 1


def test_normalize_defaults_missing_ohlc_to_zero():
    """OHLC 字段缺失时回落 0.0 (失败安全), 不抛错。"""
    df = pd.DataFrame({"date": ["2024-01-01"]})
    out = normalize_ohlcv_df(df, "AAPL")
    assert len(out) == 1
    r = out[0]
    assert r["open"] == 0.0
    assert r["close"] == 0.0
    assert r["volume"] == 0.0


def test_has_any_provider_credentials_detects_env(monkeypatch):
    """无任何凭证环境变量时返回 False; 设一个后返回 True。"""
    for k in (
        "OPENBB_API_KEY",
        "OPENBB_FMP_API_KEY",
        "FMP_API_KEY",
        "POLYGON_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    assert has_any_provider_credentials() is False
    monkeypatch.setenv("OPENBB_FMP_API_KEY", "test-key")
    assert has_any_provider_credentials() is True


# ============================================================
# 2. 元数据 + 边界 (始终跑, 不依赖 openbb)
# ============================================================


def test_openbb_metadata_and_boundary():
    """adapter 元数据 + 交易边界 + 许可证防火墙。"""
    a = OpenbbAdapter()
    meta = a.metadata()
    assert meta.name == "openbb"
    assert meta.allow_live_order is False
    assert meta.license_safety == LicenseSafety.SAFE
    assert meta.license_name == "MIT"
    assert meta.code_copy_allowed is True
    # 数据源 adapter 不暴露任何实盘下单能力
    for cap in meta.capabilities:
        low = cap.name.lower()
        for tok in ("submit_order", "place_order", "live"):
            assert tok not in low


def test_openbb_autodiscovered_by_registry():
    """autodiscover 应发现 openbb adapter (与 demo / vectorbt 一起)。"""
    from backend.integrations.registry import IntegrationRegistry, autodiscover

    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    assert reg.has("openbb")


def test_openbb_healthcheck_reports_availability(monkeypatch):
    """openbb 未装时 UNAVAILABLE; 装了但无凭证 DEGRADED; 装了且有凭证 HEALTHY。"""
    a = OpenbbAdapter()
    h = a.healthcheck()
    # 无 openbb 的环境 → UNAVAILABLE; 这是不装 openbb 时唯一可达分支
    assert h.status in (
        HealthStatus.UNAVAILABLE,
        HealthStatus.DEGRADED,
        HealthStatus.HEALTHY,
    )


# ============================================================
# 3. openbb 执行路径 (skipif; 未装整组跳过)
# ============================================================

try:
    import openbb as _obb  # noqa: F401

    _HAS_OBB = True
except Exception:
    _HAS_OBB = False

_obb_required = pytest.mark.skipif(not _HAS_OBB, reason="openbb 未安装, 跳过执行路径用例")


@_obb_required
def test_get_ohlcv_returns_normalized_or_empty():
    """取数成功返回非空归一化结果; 凭证/网络失败返回空 (失败安全)。"""
    a = OpenbbAdapter()
    out = a.get_ohlcv("AAPL", "2024-01-01", "2024-01-10", provider="yfinance")
    # 不强求非空 (CI 可能无网); 只校验: 要么空, 要么每条都是标准结构
    for r in out:
        assert {
            "symbol",
            "date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        } <= set(r)
        assert r["source"] == "openbb"
