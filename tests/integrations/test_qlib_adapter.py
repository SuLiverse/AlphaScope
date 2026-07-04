"""Qlib Adapter 测试 (Phase 2 第三个真实 adapter).

分两组:
1. **纯函数组 (始终跑)**: normalize_qlib_factor_df / has_qlib_data_initialized —— 验证
   Qlib 因子 dataframe 归一化成 AlphaScope 因子向量结构, 全部失败安全。不依赖 qlib。
2. **qlib 执行路径 (skipif; 未装跳过)**: adapter 健康检查 / 自动发现 / compute_factors
   端到端。qlib 未装时整组跳过 (CI 无 qlib 仍确定性通过)。

合规: 测试只校验因子归一化与边界不变量, 不涉及任何买卖指令。
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.integrations.factor.qlib_adapter import (
    QlibAdapter,
    _to_qlib_instrument,
    normalize_qlib_factor_df,
)
from backend.integrations.schemas import HealthStatus, LicenseSafety


# ============================================================
# 1. 纯函数组 (始终跑, 不依赖 qlib)
# ============================================================


def test_normalize_none_df_returns_empty_vector_safe():
    out = normalize_qlib_factor_df(None, "000001")
    assert out["symbol"] == "000001"
    assert out["factor_set"] == "alpha158"
    assert out["factors"] == {}
    assert out["source"] == "qlib"
    assert "disclaimer" in out


def test_normalize_takes_latest_row_and_filters_nan():
    """取最新行作为因子向量; NaN/inf 被过滤掉。"""
    df = pd.DataFrame(
        {
            "KBAR": [0.1, 0.2, 0.3],
            "OPEN0": [1.0, float("nan"), 1.5],
            "HIGH0": [2.0, 2.1, float("inf")],
        },
        index=["2024-01-01", "2024-01-02", "2024-01-03"],
    )
    out = normalize_qlib_factor_df(df, "AAPL", factor_set="alpha158")
    assert out["asof"] == "2024-01-03"
    # 最新行: KBAR=0.3, OPEN0=1.5, HIGH0=inf → inf 被过滤
    assert out["factors"]["KBAR"] == 0.3
    assert out["factors"]["OPEN0"] == 1.5
    assert "HIGH0" not in out["factors"]  # inf 过滤


def test_normalize_empty_df_is_safe():
    assert normalize_qlib_factor_df(pd.DataFrame(), "X")["factors"] == {}


def test_normalize_garbage_columns_are_skipped():
    """非数值列被跳过, 不抛错 (失败安全)。"""
    df = pd.DataFrame({"good": [1.0], "bad": ["not a number"]}, index=["2024-01-01"])
    out = normalize_qlib_factor_df(df, "X")
    assert out["factors"] == {"good": 1.0}


def test_normalize_factor_set_label_carried_through():
    df = pd.DataFrame({"f": [1.0]}, index=["2024-01-01"])
    out = normalize_qlib_factor_df(df, "X", factor_set="alpha360")
    assert out["factor_set"] == "alpha360"


def test_to_qlib_instrument_sh_sz_prefix():
    """A 股 6 位代码 → Qlib SH/SZ 口径; 已带前缀/非标准原样返回。"""
    assert _to_qlib_instrument("600000") == "SH600000"  # 沪市主板
    assert _to_qlib_instrument("688981") == "SH688981"  # 科创板
    assert _to_qlib_instrument("000001") == "SZ000001"  # 深市主板
    assert _to_qlib_instrument("300750") == "SZ300750"  # 创业板
    # 已是 Qlib 口径 → 原样
    assert _to_qlib_instrument("SH600000") == "SH600000"
    # 非标准/空 → 原样 (交给 Qlib 自行解析)
    assert _to_qlib_instrument("AAPL") == "AAPL"
    assert _to_qlib_instrument("") == ""


# ============================================================
# 2. 元数据 + 边界 (始终跑, 不依赖 qlib)
# ============================================================


def test_qlib_metadata_and_boundary():
    """adapter 元数据 + 交易边界 + 许可证防火墙。"""
    a = QlibAdapter()
    meta = a.metadata()
    assert meta.name == "qlib"
    assert meta.allow_live_order is False
    assert meta.license_safety == LicenseSafety.SAFE
    assert meta.license_name == "MIT"
    assert meta.code_copy_allowed is True
    # factor adapter 不暴露任何实盘下单能力
    for cap in meta.capabilities:
        low = cap.name.lower()
        for tok in ("submit_order", "place_order", "live"):
            assert tok not in low


def test_qlib_autodiscovered_by_registry():
    """autodiscover 应发现 qlib adapter (与 demo/vectorbt/openbb 一起)。"""
    from backend.integrations.registry import IntegrationRegistry, autodiscover

    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    assert reg.has("qlib")


def test_qlib_healthcheck_reports_availability():
    """qlib 未装时 UNAVAILABLE; 装了但数据未初始化 DEGRADED; 装了且初始化 HEALTHY。"""
    a = QlibAdapter()
    h = a.healthcheck()
    assert h.status in (
        HealthStatus.UNAVAILABLE,
        HealthStatus.DEGRADED,
        HealthStatus.HEALTHY,
    )


def test_compute_factors_failure_safe_returns_empty_vector():
    """qlib 不可用时 compute_factors 不抛, 返回空因子向量 (结构与正常一致)。

    symbol 经 _to_qlib_instrument 转成 Qlib 口径 (000001 → SZ000001)。
    """
    a = QlibAdapter()
    out = a.compute_factors(["000001"], bars=[])
    assert out["symbol"] == "SZ000001"
    assert out["factors"] == {}
    assert out["source"] == "qlib"


# ============================================================
# 3. qlib 执行路径 (skipif; 未装整组跳过)
# ============================================================

try:
    import qlib as _qlib  # noqa: F401

    _HAS_QLIB = True
except Exception:
    _HAS_QLIB = False

_qlib_required = pytest.mark.skipif(not _HAS_QLIB, reason="qlib 未安装, 跳过执行路径用例")


@_qlib_required
def test_compute_factors_with_real_qlib_returns_vector_or_empty():
    """qlib 装了但数据未初始化时仍失败安全返回空; 初始化过则返回非空因子向量。"""
    a = QlibAdapter()
    out = a.compute_factors(["000001"], factor_set="alpha158")
    # 不强求非空 (CI 可能未下数据); 只校验结构
    assert "factors" in out and isinstance(out["factors"], dict)
    assert out["source"] == "qlib"
