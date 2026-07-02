"""替代因子 — 纯函数 + API 契约测试 + Finnhub 凭证兼容性。"""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.api.main import app

    return TestClient(app)


# ---------------- 纯函数 ----------------


def test_normalize_sentiment_net_bull():
    from backend.alternative_factors import normalize_sentiment

    assert normalize_sentiment({"bullPercent": 0.7, "bearishPercent": 0.2}) == pytest.approx(0.5)
    # 净空
    assert normalize_sentiment({"bullPercent": 0.2, "bearishPercent": 0.6}) == pytest.approx(-0.4)
    # 夹断
    assert normalize_sentiment({"bullPercent": 0.9, "bearishPercent": 0.0}) == pytest.approx(0.9)
    # 无数据
    assert normalize_sentiment({}) is None
    assert normalize_sentiment(None) is None
    assert normalize_sentiment("garbage") is None


def test_score_insider_net_buy():
    from backend.alternative_factors import score_insider

    # 净买入
    pos = score_insider([{"change": 5000}, {"change": -1000}, {"change": 3000}])
    assert pos is not None and pos > 0
    # 净卖出
    neg = score_insider([{"change": -8000}, {"change": 2000}])
    assert neg is not None and neg < 0
    # 无数据
    assert score_insider([]) is None
    assert score_insider(None) is None


def test_score_macro_overview():
    from backend.alternative_factors import score_macro_overview

    # 高利率 + 高失业 → 偏空
    bearish = score_macro_overview({
        "10_Years_Treasury_Rate": {"value": "4.5"},
        "Unemployment_Rate": {"value": "6.5"},
        "CPI": {"value": "5.0"},
    })
    assert bearish is not None and bearish < 0
    # 低利率 + 低失业 → 偏多
    bullish = score_macro_overview({
        "GS10": {"value": "2.0"},
        "UNRATE": {"value": "3.5"},
        "CPIAUCSL": {"value": "1.5"},
    })
    assert bullish is not None and bullish > 0
    # 无数据
    assert score_macro_overview({}) is None
    assert score_macro_overview(None) is None


def test_build_vector_structure_without_credentials():
    """无 FRED/finnhub 凭证时:返回结构完整, 因子 None + degraded, 不抛。"""
    from backend.alternative_factors import build_vector

    vec = build_vector("AAPL")
    assert "macro_risk_appetite" in vec
    assert "us_sentiment" in vec
    assert "available_providers" in vec
    assert "degraded" in vec
    assert isinstance(vec["available_providers"], list)


# ---------------- API 契约 ----------------


def test_api_alternative_factors(client):
    r = client.get("/api/factors/alternative/AAPL")
    assert r.status_code == 200
    body = r.json()["data"]
    assert "macro_risk_appetite" in body
    assert "us_sentiment" in body


def test_api_alternative_macro_only(client):
    r = client.get("/api/factors/alternative")
    assert r.status_code == 200
    body = r.json()["data"]
    assert "macro_risk_appetite" in body


def test_alt_factors_registered_in_registry():
    from backend.quant.factor_registry import get_factor

    assert get_factor("macro_risk_appetite") is not None
    assert get_factor("us_sentiment") is not None


# ---------------- Finnhub 凭证兼容性 ----------------


def test_finnhub_accepts_both_env_vars(monkeypatch):
    """FINNHUB_TOKEN(datasource_config 预设写入)与 FINNHUB_API_KEY 都应能激活 provider。"""
    from backend.providers.finnhub_provider import FinnhubProvider

    # 清掉两个变量
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_TOKEN", raising=False)
    assert FinnhubProvider()._api_key == ""

    # 设置 FINNHUB_TOKEN(数据源 UI 保存的变量名)
    monkeypatch.setenv("FINNHUB_TOKEN", "test_token_via_ui")
    assert FinnhubProvider()._api_key == "test_token_via_ui"

    # FINNHUB_API_KEY 优先
    monkeypatch.setenv("FINNHUB_API_KEY", "test_token_canonical")
    assert FinnhubProvider()._api_key == "test_token_canonical"

    # 清理
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB_TOKEN", raising=False)
