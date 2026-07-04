from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


class FakeEastmoneyResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_fund_flow_timeout_returns_degraded_success(client):
    with patch("backend.api.fund_flow.call_with_timeout", side_effect=TimeoutError("slow")):
        resp = await client.get("/api/fund-flow/600519?days=30")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["error_code"] == "FUND_FLOW_DEGRADED"
    assert data["data"]["symbol"] == "600519"
    assert data["data"]["records"] == []
    assert data["data"]["summary"]["main_total_yi"] == 0.0
    assert data["data"]["degraded"] is True
    assert data["data"]["source_status"] == "timeout"


def test_eastmoney_individual_fund_flow_parses_standard_columns(tmp_path):
    from backend import fund_flow

    payload = {
        "data": {
            "klines": [
                "2026-05-26,100000000,-30000000,-20000000,50000000,50000000,2.5,-0.7,-0.5,1.2,1.3,1280.50,1.25,0,0",
                "2026-05-27,392363504,-988281,-391375104,-410721104,803084608,3.71,-0.01,-3.70,-3.88,7.59,1303.00,2.33,0,0",
            ]
        }
    }

    with (
        patch.object(fund_flow, "FUND_FLOW_CACHE_DIR", tmp_path),
        patch(
            "backend.fund_flow._eastmoney_get",
            return_value=FakeEastmoneyResponse(payload),
        ) as mock_get,
        patch("backend.fund_flow.ak.stock_individual_fund_flow") as mock_ak,
    ):
        df = fund_flow.fetch_individual_fund_flow("600519", days=1)

    assert df is not None
    assert len(df) == 1
    assert df.attrs["source"] == "eastmoney"
    assert df.iloc[0]["主力净流入-净额"] == 392363504
    assert df.iloc[0]["收盘价"] == 1303.0
    mock_get.assert_called_once()
    mock_ak.assert_not_called()


@pytest.mark.anyio
async def test_fund_flow_uses_cached_records_when_provider_empty(client, tmp_path):
    from backend import fund_flow

    fresh_df = pd.DataFrame(
        [
            {
                "日期": "2026-05-21",
                "收盘价": 1280,
                "涨跌幅": 1.2,
                "主力净流入-净额": 120000000,
                "主力净流入-净占比": 3.5,
                "超大单净流入-净额": 80000000,
                "大单净流入-净额": 40000000,
                "中单净流入-净额": -20000000,
                "小单净流入-净额": -100000000,
            }
        ]
    )

    with (
        patch.object(fund_flow, "FUND_FLOW_CACHE_DIR", tmp_path),
        patch(
            "backend.fund_flow._fetch_individual_fund_flow_eastmoney",
            return_value=fresh_df,
        ),
    ):
        seeded = fund_flow.fetch_individual_fund_flow("600519", days=30)
    assert seeded is not None

    with (
        patch.object(fund_flow, "FUND_FLOW_CACHE_DIR", tmp_path),
        patch(
            "backend.fund_flow._fetch_individual_fund_flow_eastmoney",
            return_value=pd.DataFrame(),
        ),
    ):
        resp = await client.get("/api/fund-flow/600519?days=30")

    data = resp.json()
    assert data["success"] is True
    assert data["error_code"] == "FUND_FLOW_DEGRADED"
    assert data["data"]["degraded"] is True
    assert data["data"]["source"] == "eastmoney"
    assert data["data"]["source_status"] == "cache"
    assert data["data"]["records"][0]["main_net_yi"] == 1.2
