"""Integration Registry 测试 (Phase 1).

验证:
1. 自动发现 + demo adapter 注册成功
2. demo adapter 健康检查通过
3. demo adapter run_backtest 返回归一化结构
4. **Phase 0 第四道防线**: 注册表断言所有 adapter allow_live_order=False
5. 边界违规的 adapter 被拒绝注册
6. 许可证防火墙: copyleft + code_copy_allowed=True 被拒绝
"""

from __future__ import annotations

import pytest

from backend.integrations.base import BacktestEngineAdapter
from backend.integrations.registry import (
    IntegrationRegistry,
    assert_boundary_invariant,
    autodiscover,
)
from backend.integrations.schemas import (
    CapabilitySpec,
    HealthStatus,
    IntegrationCategory,
    IntegrationMetadata,
    IntegrationMode,
    LicenseSafety,
)


# ----------------------------- 1. 自动发现 -----------------------------


def test_autodiscover_registers_demo():
    """autodiscover 应至少发现 demo_adapter。"""
    reg = IntegrationRegistry()
    n = autodiscover(registry=reg)
    assert n >= 1
    assert reg.has("demo")


def test_demo_metadata_and_health():
    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    demo = reg.get("demo")
    meta = demo.metadata()
    assert meta.category == IntegrationCategory.BACKTEST
    assert meta.allow_live_order is False
    assert meta.license_safety == LicenseSafety.SAFE
    health = demo.healthcheck()
    assert health.status == HealthStatus.HEALTHY


def test_demo_run_backtest_returns_normalized_result():
    reg = IntegrationRegistry()
    autodiscover(registry=reg)
    demo = reg.get("demo")
    res = demo.run_backtest(
        strategy_id="s1",
        symbols=["000001"],
        start="2024-01-01",
        end="2024-06-30",
    )
    assert res.engine_name == "demo"
    assert res.research_only is True
    assert res.assumptions.engine_name == "demo"
    # 归一化结构字段齐
    assert hasattr(res.metrics, "sharpe")
    assert isinstance(res.equity_curve, list)


# ----------------------------- 4. 第四道防线 -----------------------------


def test_boundary_invariant_holds_for_all_registered():
    """所有已注册 adapter 都通过交易边界断言。"""
    # 触发自动发现 (单例)
    assert_boundary_invariant()  # 不抛即通过


# ----------------------------- 5. 违规 adapter 被拒 -----------------------------


def _bad_live_order_adapter():
    class _A(BacktestEngineAdapter):
        NAME = "evil_live"

        def _metadata(self):
            return IntegrationMetadata(
                name=self.NAME,
                category=IntegrationCategory.BACKTEST,
                allow_live_order=True,  # 违规
            )

        def healthcheck(self):
            from backend.integrations.schemas import IntegrationHealth

            return IntegrationHealth(name=self.NAME, status=HealthStatus.HEALTHY)

    return _A


def test_register_rejects_live_order_adapter():
    reg = IntegrationRegistry()
    with pytest.raises(ValueError, match="allow_live_order"):
        reg.register(_bad_live_order_adapter())


def test_register_rejects_forbidden_capability():
    class _C(BacktestEngineAdapter):
        NAME = "evil_cap"

        def _metadata(self):
            return IntegrationMetadata(
                name=self.NAME,
                category=IntegrationCategory.BACKTEST,
                allow_live_order=False,
                capabilities=[CapabilitySpec(name="place_order", description="违规")],
            )

        def healthcheck(self):
            from backend.integrations.schemas import IntegrationHealth

            return IntegrationHealth(name=self.NAME, status=HealthStatus.HEALTHY)

    reg = IntegrationRegistry()
    with pytest.raises(ValueError, match="禁止能力"):
        reg.register(_C)


# ----------------------------- 6. 许可证防火墙 -----------------------------


def test_register_rejects_copyleft_with_code_copy():
    class _G(BacktestEngineAdapter):
        NAME = "agpl_evil"

        def _metadata(self):
            return IntegrationMetadata(
                name=self.NAME,
                category=IntegrationCategory.BACKTEST,
                mode=IntegrationMode.PYTHON_ADAPTER,
                allow_live_order=False,
                license_name="AGPL-3.0",
                license_safety=LicenseSafety.COPILEFT_RISK,
                code_copy_allowed=True,  # 违规: AGPL 不可拷码
            )

        def healthcheck(self):
            from backend.integrations.schemas import IntegrationHealth

            return IntegrationHealth(name=self.NAME, status=HealthStatus.HEALTHY)

    reg = IntegrationRegistry()
    with pytest.raises(ValueError, match="许可证"):
        reg.register(_G)


def test_register_accepts_copyleft_as_external_process():
    """AGPL 项目以 external_process + 仅协议兼容方式接入是允许的。"""

    class _OK(BacktestEngineAdapter):
        NAME = "agpl_ok"

        def _metadata(self):
            return IntegrationMetadata(
                name=self.NAME,
                category=IntegrationCategory.BACKTEST,
                mode=IntegrationMode.EXTERNAL_PROCESS,
                allow_live_order=False,
                license_name="AGPL-3.0",
                license_safety=LicenseSafety.COPILEFT_RISK,
                code_copy_allowed=False,  # 正确: 子进程隔离
            )

        def healthcheck(self):
            from backend.integrations.schemas import IntegrationHealth

            return IntegrationHealth(name=self.NAME, status=HealthStatus.HEALTHY)

    reg = IntegrationRegistry()
    reg.register(_OK)
    assert reg.has("agpl_ok")


# ----------------------------- API 烟测 -----------------------------


def test_integrations_api_list_endpoint():
    """用 FastAPI TestClient 验证 /api/integrations 返回 demo。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.integrations import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    r = client.get("/api/integrations")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    names = [it["name"] for it in body["data"]["integrations"]]
    assert "demo" in names


def test_integrations_api_boundary_endpoint():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.api.integrations import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    r = client.get("/api/integrations/boundary")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["live_order_blocked"] is True


# ----------------------------- _dispatch 覆盖 -----------------------------


def test_dispatch_supports_all_category_capability_pairs():
    """_dispatch 必须覆盖每类 adapter 的核心能力 (审查回归: 防止新增 adapter 后
    忘了补 dispatch 分支, 导致 /run 端点对某些能力报 '不支持')。"""
    from backend.api.integrations import _dispatch, _default_capability
    from backend.integrations.registry import get_registry

    reg = get_registry()

    # demo (backtest/run_backtest) — 真实可跑
    demo = reg.get("demo")
    out = _dispatch(demo, "backtest", "run_backtest", {"symbols": ["000001"]})
    assert out["engine_name"] == "demo"

    # data/get_ohlcv — 用 stub adapter (openbb/vectorbt 未装时仍要保证 dispatch 分支存在)
    class _StubData:
        NAME = "stub_data"

        def __init__(self):
            self.kw = {}

        def get_ohlcv(self, symbol, start, end, **kw):
            self.kw = kw
            return [{"symbol": symbol, "date": start, "close": 1.0}]

    stub_data = _StubData()
    res = _dispatch(
        stub_data,
        "data",
        _default_capability("data"),
        {
            "symbol": "AAPL",
            "start": "2024-01-01",
            "end": "2024-01-02",
            "provider": "yfinance",
            "interval": "1d",
        },
    )
    assert isinstance(res, list) and res[0]["symbol"] == "AAPL"
    assert stub_data.kw == {"provider": "yfinance", "interval": "1d"}

    # backtest/param_sweep — stub (vectorbt 未装时仍要保证 dispatch 分支存在)
    class _StubSweep:
        NAME = "stub_sweep"

        def param_sweep(self, bars=None, param_grid=None, metric="sharpe", top_n=20, **kw):
            return [
                {
                    "params": {"fast": 5, "slow": 20},
                    "metric": metric,
                    "top_n": top_n,
                    "fees": kw.get("fees"),
                }
            ]

    res = _dispatch(
        _StubSweep(),
        "backtest",
        "param_sweep",
        {"metric": "sharpe", "top_n": 5, "fees": 0.001},
    )
    assert isinstance(res, list) and res[0]["top_n"] == 5
    assert res[0]["fees"] == 0.001

    class _StubAgent:
        NAME = "stub_agent"

        def analyze(self, symbols, **kw):
            return [{"symbols": symbols, "kwargs": kw}]

    agent_result = _dispatch(
        _StubAgent(),
        "agent",
        "analyze",
        {"symbols": ["600519"], "trade_date": "2026-07-15", "asset_type": "stock"},
    )
    assert agent_result[0]["kwargs"] == {
        "trade_date": "2026-07-15",
        "asset_type": "stock",
    }

    class _StubFactor:
        NAME = "stub_factor"

        def compute_factors(self, symbols, **kw):
            return {"symbols": symbols, "kwargs": kw}

    factor_result = _dispatch(
        _StubFactor(),
        "factor",
        "compute_factors",
        {
            "symbols": ["600519"],
            "start_time": "2025-01-01",
            "end_time": "2026-01-01",
            "factor_set": "alpha158",
        },
    )
    assert factor_result["kwargs"]["factor_set"] == "alpha158"

    # 未声明能力仍应抛 ValueError (守卫)
    import pytest

    with pytest.raises(ValueError, match="不支持能力"):
        _dispatch(demo, "backtest", "totally_unknown_cap", {})


def test_format_param_sweep_result_enriches_legacy_list():
    from backend.api.integrations import _format_param_sweep_result

    result = _format_param_sweep_result(
        [
            {
                "params": {"fast": 5, "slow": 20},
                "metrics": {"sharpe": 1.1},
                "returns": [0.01, -0.005, 0.008, 0.002],
            }
        ],
        symbol="600519",
        metric="sharpe",
        n_trials=6,
    )

    assert result["status"] == "ok"
    assert result["n_trials"] == 6
    assert result["returned"] == 1
    assert result["top"] == result["results"]
    row = result["results"][0]
    assert "returns" not in row
    assert row["metrics"]["n_trials_for_dsr"] == 6
    assert "probabilistic_sharpe" in row["metrics"]
    assert "deflated_sharpe" in row["metrics"]
    assert "不构成投资建议" in result["disclaimer"]


@pytest.mark.anyio
async def test_run_integration_dispatches_in_worker_and_keeps_agent_kwargs(monkeypatch):
    import backend.api.integrations as api

    class _StubAgent:
        NAME = "stub_agent"

        def metadata(self):
            return IntegrationMetadata(
                name=self.NAME,
                category=IntegrationCategory.AGENT,
                mode=IntegrationMode.PYTHON_ADAPTER,
                version="1",
                display_name="Stub Agent",
                description="test",
                capabilities=[CapabilitySpec(name="analyze", description="test")],
                allow_live_order=False,
            )

        def is_available(self):
            return True

        def analyze(self, symbols, **kw):
            return [{"symbols": symbols, "kwargs": kw}]

    adapter = _StubAgent()

    class _Registry:
        def has(self, name):
            return name == adapter.NAME

        def get(self, name):
            assert name == adapter.NAME
            return adapter

    worker_calls = []

    async def fake_to_thread(function, *args):
        worker_calls.append((function, args))
        return function(*args)

    monkeypatch.setattr(api, "get_registry", lambda: _Registry())
    monkeypatch.setattr(api, "assert_boundary_invariant", lambda: None)
    monkeypatch.setattr(api.asyncio, "to_thread", fake_to_thread)

    response = await api.run_integration(
        adapter.NAME,
        api.RunRequest(
            capability="analyze",
            params={
                "symbols": ["600519"],
                "trade_date": "2026-07-15",
                "asset_type": "stock",
            },
        ),
    )

    assert len(worker_calls) == 1
    result = response.data["result"]
    assert result[0]["kwargs"] == {
        "trade_date": "2026-07-15",
        "asset_type": "stock",
    }
