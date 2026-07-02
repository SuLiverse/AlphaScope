"""Tests for Price Store — 行情存储层 + API"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient

from backend.api.main import app


# ============== normalize_symbol 测试 ==============


class TestNormalizeSymbol:
    """测试股票代码标准化"""

    def test_plain_digits(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("600519") == "600519"

    def test_sh_suffix(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("600519.SH") == "600519"

    def test_sz_suffix(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("000001.SZ") == "000001"

    def test_bj_suffix(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("830799.BJ") == "830799"

    def test_prefix_format(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("SH600519") == "600519"
        assert normalize_symbol("SZ000001") == "000001"

    def test_dot_prefix_format(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("sh.600519") == "600519"

    def test_empty(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("") == ""
        assert normalize_symbol("  ") == ""

    def test_hk_stock(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("00700.HK") == "00700"

    def test_mixed_case(self):
        from backend.price_store import normalize_symbol

        assert normalize_symbol("600519.sh") == "600519"
        assert normalize_symbol("600519.Sh") == "600519"


# ============== get_market 测试 ==============


class TestGetMarket:
    """测试市场推断"""

    def test_sh(self):
        from backend.price_store import get_market

        assert get_market("600519") == "CN"

    def test_sz(self):
        from backend.price_store import get_market

        assert get_market("000001") == "CN"

    def test_bj(self):
        from backend.price_store import get_market

        assert get_market("830799") == "CN"

    def test_hk(self):
        from backend.price_store import get_market

        assert get_market("00700") == "HK"


# ============== validate_price_bar 测试 ==============


class TestValidatePriceBar:
    """测试数据质量校验"""

    def test_valid_bar(self):
        from backend.price_store import validate_price_bar

        bar = {"open": 100, "high": 105, "low": 98, "close": 103, "volume": 1000}
        ok, msg = validate_price_bar(bar)
        assert ok is True
        assert msg == ""

    def test_zero_price(self):
        from backend.price_store import validate_price_bar

        bar = {"open": 0, "high": 105, "low": 98, "close": 103, "volume": 1000}
        ok, msg = validate_price_bar(bar)
        assert ok is False
        assert "OHLC" in msg

    def test_high_below_low(self):
        from backend.price_store import validate_price_bar

        bar = {"open": 100, "high": 95, "low": 98, "close": 103, "volume": 1000}
        ok, msg = validate_price_bar(bar)
        assert ok is False
        assert "最高价" in msg

    def test_negative_volume(self):
        from backend.price_store import validate_price_bar

        bar = {"open": 100, "high": 105, "low": 98, "close": 103, "volume": -100}
        ok, msg = validate_price_bar(bar)
        assert ok is False
        assert "成交量" in msg

    def test_high_below_close(self):
        from backend.price_store import validate_price_bar

        bar = {"open": 100, "high": 103, "low": 98, "close": 105, "volume": 1000}
        ok, msg = validate_price_bar(bar)
        assert ok is False
        assert "最高价" in msg

    def test_low_above_open(self):
        from backend.price_store import validate_price_bar

        bar = {"open": 95, "high": 105, "low": 98, "close": 103, "volume": 1000}
        ok, msg = validate_price_bar(bar)
        assert ok is False
        assert "最低价" in msg


# ============== price_store CRUD 测试 ==============


class TestPriceStore:
    """测试 price_store CRUD"""

    @staticmethod
    def _patch_db():
        """mock 进程级单例 Database, 让 transaction() 上下文给出同一个 mock conn。

        CRUD 现在走 with Database().transaction() as conn:, 不再暴露 _get_conn。
        _ensure_schema 也用 transaction(), 因此同一个 mock conn 覆盖建表+CRUD。
        """
        conn = MagicMock()
        db_mock = MagicMock()
        db_mock.transaction.return_value.__enter__.return_value = conn
        db_mock.transaction.return_value.__exit__.return_value = False
        patcher = patch("backend.price_store.Database", return_value=db_mock)
        return patcher, conn

    def test_save_price_bar(self):
        from backend.price_store import save_price_bar

        patcher, conn = self._patch_db()
        with patcher:
            save_price_bar(
                {
                    "symbol": "600519",
                    "date": "2025-01-01",
                    "open": 100,
                    "high": 105,
                    "low": 98,
                    "close": 103,
                    "volume": 1000,
                }
            )
            assert conn.execute.called
            assert conn.commit.called

    def test_save_price_bars(self):
        from backend.price_store import save_price_bars

        patcher, conn = self._patch_db()
        with patcher:
            bars = [
                {
                    "symbol": "600519",
                    "date": "2025-01-01",
                    "open": 100,
                    "high": 105,
                    "low": 98,
                    "close": 103,
                },
                {
                    "symbol": "600519",
                    "date": "2025-01-02",
                    "open": 103,
                    "high": 108,
                    "low": 101,
                    "close": 106,
                },
            ]
            count = save_price_bars(bars)
            assert count == 2

    def test_get_prices(self):
        from backend.price_store import get_prices

        patcher, conn = self._patch_db()
        with patcher:
            conn.execute.return_value.fetchall.return_value = []
            result = get_prices("600519")
            assert isinstance(result, list)

    def test_get_latest_price_none(self):
        from backend.price_store import get_latest_price

        patcher, conn = self._patch_db()
        with patcher:
            conn.execute.return_value.fetchone.return_value = None
            result = get_latest_price("600519")
            assert result is None

    def test_delete_prices(self):
        from backend.price_store import delete_prices

        patcher, conn = self._patch_db()
        with patcher:
            conn.execute.return_value.rowcount = 10
            count = delete_prices("600519")
            assert count == 10

    def test_delete_prices_with_frequency(self):
        from backend.price_store import delete_prices

        patcher, conn = self._patch_db()
        with patcher:
            conn.execute.return_value.rowcount = 5
            count = delete_prices("600519", frequency="1d")
            assert count == 5


# ============== API 测试 ==============


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.anyio
async def test_normalize_endpoint(client):
    """GET /api/prices/normalize/{symbol}"""
    resp = await client.get("/api/prices/normalize/600519.SH")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["normalized"] == "600519"
    assert data["data"]["market"] == "CN"


@pytest.mark.anyio
async def test_get_prices(client):
    """GET /api/prices/{symbol}"""
    with (
        patch("backend.price_store.get_prices", return_value=[]),
        patch("backend.api.prices.fetch_prices") as mock_fetch,
    ):
        resp = await client.get("/api/prices/600519")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["total"] == 0
    mock_fetch.assert_awaited_once()


@pytest.mark.anyio
async def test_get_prices_returns_degraded_timeout_metadata(client):
    """GET /api/prices/{symbol} Provider 超时时返回结构化降级信息"""
    from backend.schemas.api import ApiResponse

    with (
        patch("backend.price_store.get_prices", return_value=[]),
        patch(
            "backend.api.prices.fetch_prices",
            return_value=ApiResponse(
                success=False,
                data={
                    "symbol": "600519",
                    "fetched": 0,
                    "degraded": True,
                    "source_status": "timeout",
                },
                error="行情源响应超时，请稍后重试",
                error_code="PRICE_PROVIDER_TIMEOUT",
            ),
        ),
    ):
        resp = await client.get("/api/prices/600519")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["error_code"] == "PRICE_PROVIDER_TIMEOUT"
    assert data["data"]["total"] == 0
    assert data["data"]["degraded"] is True
    assert data["data"]["source_status"] == "timeout"


@pytest.mark.anyio
async def test_fetch_prices_passes_symbol_to_provider(client):
    """POST /api/prices/{symbol}/fetch 使用 symbol 参数调用 Provider"""
    mock_registry = MagicMock()
    mock_registry.get.return_value = [
        {
            "symbol": "600519",
            "date": "2026-05-25",
            "open": 1287,
            "high": 1304,
            "low": 1277,
            "close": 1285,
        }
    ]
    with (
        patch("backend.providers.registry.get_registry", return_value=mock_registry),
        patch("backend.price_store.save_price_bars", return_value=1),
    ):
        resp = await client.post("/api/prices/600519/fetch?days=30")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    kwargs = mock_registry.get.call_args.kwargs
    assert kwargs["symbol"] == "600519"
    assert kwargs["adjust"] == ""
    assert "query" not in kwargs


@pytest.mark.anyio
async def test_fetch_prices_provider_timeout(client):
    """POST /api/prices/{symbol}/fetch Provider 超时不阻塞接口"""
    with (
        patch("backend.price_store.normalize_symbol", return_value="600519"),
        patch("backend.api.prices._fetch_provider_bars", side_effect=TimeoutError),
        patch("backend.price_store.save_price_bars") as mock_save,
    ):
        resp = await client.post("/api/prices/600519/fetch?days=30")

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == "PRICE_PROVIDER_TIMEOUT"
    assert data["data"]["source_status"] == "timeout"
    mock_save.assert_not_called()


@pytest.mark.anyio
async def test_get_latest_price_not_found(client):
    """GET /api/prices/{symbol}/latest 无数据"""
    with (
        patch("backend.price_periods.fetch_intraday_prices", return_value=[]),
        patch("backend.price_store.get_prices", return_value=[]),
        patch("backend.price_store.get_latest_price", return_value=None),
        patch("backend.api.prices.fetch_prices") as mock_fetch,
    ):
        resp = await client.get("/api/prices/600519/latest")
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    mock_fetch.assert_awaited_once()


@pytest.mark.anyio
async def test_get_latest_price_found(client):
    """GET /api/prices/{symbol}/latest 有数据"""
    mock_bar = {
        "symbol": "600519",
        "date": "2025-05-20",
        "open": 100,
        "high": 105,
        "low": 98,
        "close": 103,
        "volume": 1000,
    }
    with (
        patch("backend.price_periods.fetch_intraday_prices", return_value=[]),
        patch("backend.price_store.get_prices", return_value=[mock_bar]),
        patch("backend.price_store.get_latest_price", return_value=mock_bar),
        patch("backend.api.prices.fetch_prices") as mock_fetch,
    ):
        resp = await client.get("/api/prices/600519/latest")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["data"]["close"] == 103
    mock_fetch.assert_not_awaited()


@pytest.mark.anyio
async def test_fetch_prices_invalid_symbol(client):
    """POST /api/prices/{symbol}/fetch 无效代码"""
    with patch("backend.price_store.normalize_symbol", return_value=""):
        resp = await client.post("/api/prices/INVALID/fetch")
    assert resp.status_code == 200
    assert resp.json()["success"] is False


@pytest.mark.anyio
async def test_get_prices_weekly_aggregates_daily_bars(client):
    """GET /api/prices/{symbol}?frequency=1w 返回按周聚合的 K 线"""
    daily = [
        {
            "symbol": "600519",
            "date": "2026-05-04",
            "open": 10,
            "high": 13,
            "low": 9,
            "close": 12,
            "volume": 100,
            "amount": 1000,
        },
        {
            "symbol": "600519",
            "date": "2026-05-05",
            "open": 12,
            "high": 15,
            "low": 11,
            "close": 14,
            "volume": 200,
            "amount": 2000,
        },
    ]
    with patch("backend.price_store.get_prices", return_value=daily):
        resp = await client.get("/api/prices/600519?frequency=1w&limit=5")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frequency"] == "1w"
    assert data["total"] == 1
    assert data["bars"][0]["open"] == 10
    assert data["bars"][0]["high"] == 15
    assert data["bars"][0]["low"] == 9
    assert data["bars"][0]["close"] == 14


@pytest.mark.anyio
async def test_get_prices_intraday_uses_intraday_fetcher(client):
    """GET /api/prices/{symbol}?frequency=intraday 不用日线冒充分时"""
    intraday = [
        {
            "symbol": "600519",
            "date": "2026-05-25 09:31",
            "open": 10,
            "high": 10.2,
            "low": 9.9,
            "close": 10.1,
            "volume": 100,
            "frequency": "intraday",
        }
    ]
    with (
        patch(
            "backend.price_periods.fetch_intraday_prices", return_value=intraday
        ) as mock_fetch_intraday,
        patch("backend.price_store.get_prices") as mock_get_prices,
    ):
        resp = await client.get("/api/prices/600519?frequency=intraday&limit=240")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frequency"] == "intraday"
    assert data["total"] == 1
    assert data["bars"][0]["date"] == "2026-05-25 09:31"
    mock_fetch_intraday.assert_called_once()
    mock_get_prices.assert_not_called()


@pytest.mark.anyio
async def test_get_latest_price_prefers_daily_bar(client):
    """GET /api/prices/{symbol}/latest 不用周/月聚合数据污染顶部行情"""
    daily = {
        "symbol": "600519",
        "date": "2026-05-25",
        "open": 10,
        "high": 11,
        "low": 9,
        "close": 10.5,
        "change_pct": 5.0,
        "frequency": "1d",
    }
    monthly = {
        "symbol": "600519",
        "date": "2026-05-25",
        "open": 4,
        "high": 11,
        "low": 4,
        "close": 10.5,
        "change_pct": 160.0,
        "frequency": "1mo",
    }
    with (
        patch("backend.price_periods.fetch_intraday_prices", return_value=[]),
        patch(
            "backend.price_store.get_prices", return_value=[daily]
        ) as mock_get_prices,
        patch("backend.price_store.get_latest_price", return_value=monthly),
    ):
        resp = await client.get("/api/prices/600519/latest")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frequency"] == "1d"
    assert data["change_pct"] == 5.0
    mock_get_prices.assert_called_once_with(
        symbol="600519", frequency="1d", limit=20, include_incompatible=True
    )


@pytest.mark.anyio
async def test_get_latest_price_prefers_intraday_bar(client):
    """GET /api/prices/{symbol}/latest 盘中优先返回最新分时价格"""
    intraday = {
        "symbol": "600519",
        "date": "2026-05-25 14:59",
        "open": 10,
        "high": 10.8,
        "low": 9.9,
        "close": 10.7,
        "change_pct": 7.0,
        "frequency": "intraday",
        "source": "akshare_intraday",
    }
    with (
        patch("backend.price_store.get_market", return_value="CN"),
        patch("backend.price_periods.fetch_intraday_prices", return_value=[intraday]),
        patch("backend.price_store.get_prices") as mock_get_prices,
    ):
        resp = await client.get("/api/prices/600519/latest")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frequency"] == "intraday"
    assert data["close"] == 10.7
    mock_get_prices.assert_not_called()
