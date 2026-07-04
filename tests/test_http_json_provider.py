"""TickFlow HTTP/JSON 自定义数据表测试 — 纯函数组 + 注入 fetcher(不触网)+ 临时目录隔离。"""

from __future__ import annotations

import pytest

import backend.providers.http_json_provider as hj


# ----------------------------- 纯函数组 -----------------------------


class TestExtractRecords:
    def test_root_array(self):
        payload = [{"d": "2026-01-01"}, {"d": "2026-01-02"}]
        assert len(hj.extract_records(payload, "")) == 2

    def test_nested_path(self):
        payload = {"data": {"klines": [{"d": 1}, {"d": 2}, {"d": 3}]}}
        assert len(hj.extract_records(payload, "data.klines")) == 3

    def test_index_in_path(self):
        payload = {"results": [{"bars": [{"x": 1}]}, {"bars": [{"y": 2}, {"z": 3}]}]}
        assert len(hj.extract_records(payload, "results.1.bars")) == 2

    def test_path_not_found(self):
        assert hj.extract_records({"a": 1}, "b.c") == []

    def test_non_array_target(self):
        assert hj.extract_records({"data": {"x": 1}}, "data") == []

    def test_filters_non_records(self):
        payload = [{"a": 1}, "junk", 5, [1, 2]]
        recs = hj.extract_records(payload, "")
        assert len(recs) == 2  # dict + list 保留, 标量丢弃


class TestNormDate:
    def test_string_date(self):
        assert hj._norm_date("2026-06-27 10:00") == "2026-06-27"

    def test_seconds_timestamp(self):
        # 2021-01-01 ≈ 1609459200
        assert hj._norm_date(1609459200).startswith("2021-01-01")

    def test_ms_timestamp(self):
        assert hj._norm_date(1609459200000).startswith("2021-01-01")

    def test_empty(self):
        assert hj._norm_date(None) == ""


class TestApplyFieldMap:
    def test_dict_records(self):
        records = [
            {"t": "2026-01-02", "o": 10, "h": 12, "l": 9, "c": 11, "v": 1000},
            {"t": "2026-01-01", "o": 9, "h": 11, "l": 8, "c": 10, "v": 900},
        ]
        fm = {
            "date": "t",
            "open": "o",
            "high": "h",
            "low": "l",
            "close": "c",
            "volume": "v",
        }
        bars = hj.apply_field_map(records, fm, symbol="600519")
        assert len(bars) == 2
        assert bars[0]["date"] == "2026-01-01"  # 升序
        assert bars[0]["close"] == 10.0
        assert bars[0]["source"] == "http_json"
        assert bars[0]["user_provided"] is True
        assert bars[0]["symbol"] == "600519"

    def test_list_records_by_index(self):
        records = [["2026-01-01", 9, 11, 8, 10, 900]]
        fm = {"date": 0, "open": 1, "high": 2, "low": 3, "close": 4, "volume": 5}
        bars = hj.apply_field_map(records, fm)
        assert len(bars) == 1 and bars[0]["high"] == 11.0

    def test_missing_required_returns_empty(self):
        records = [{"t": "2026-01-01", "c": 10}]
        assert hj.apply_field_map(records, {"date": "t"}) == []  # 缺 OHLC

    def test_skips_invalid_close(self):
        records = [
            {"t": "2026-01-01", "o": 1, "h": 1, "l": 1, "c": 0},
            {"t": "2026-01-02", "o": 1, "h": 1, "l": 1, "c": 5},
        ]
        fm = {"date": "t", "open": "o", "high": "h", "low": "l", "close": "c"}
        bars = hj.apply_field_map(records, fm)
        assert len(bars) == 1 and bars[0]["close"] == 5.0

    def test_limit(self):
        records = [{"t": f"2026-01-{i:02d}", "o": 1, "h": 1, "l": 1, "c": 1} for i in range(1, 11)]
        fm = {"date": "t", "open": "o", "high": "h", "low": "l", "close": "c"}
        bars = hj.apply_field_map(records, fm, limit=3)
        assert len(bars) == 3 and bars[-1]["date"] == "2026-01-10"


class TestInferFieldMap:
    def test_dict_sample(self):
        fm = hj.infer_field_map({"日期": "x", "开盘": 1, "收盘": 2, "最高": 3, "最低": 4})
        assert fm["date"] == "日期" and fm["close"] == "收盘"

    def test_list_sample_empty(self):
        fm = hj.infer_field_map([1, 2, 3])
        assert all(v is None for v in fm.values())


class TestNormalizeSource:
    def test_defaults_and_clamp(self):
        s = hj.normalize_source(
            {
                "name": "我的源",
                "method": "delete",
                "field_map": {"date": "t", "bad": "x"},
            }
        )
        assert s["method"] == "GET"  # 非法方法回退
        assert s["id"]  # 自动 slug
        assert "bad" not in s["field_map"]  # 过滤非法字段
        assert s["field_map"]["date"] == "t"

    def test_symbol_normalized(self):
        s = hj.normalize_source({"name": "x", "symbol": "SH600519"})
        assert s["symbol"] == "600519"


# ----------------------------- 注入 fetcher + 临时目录隔离 -----------------------------


@pytest.fixture
def store(tmp_path, monkeypatch):
    """把 _root_dir 指向临时目录, 完全隔离注册表与物化缓存。"""
    root = tmp_path / "tickflow"
    (root / "data").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(hj, "_root_dir", lambda: root)
    yield hj


def _good_fetcher(payload):
    def _f(**kwargs):
        return {"ok": True, "status": 200, "payload": payload, "error": None}

    return _f


class TestRegistry:
    def test_save_list_get_delete(self, store):
        saved = store.save_source({"name": "测试源", "url": "https://x/{symbol}", "symbol": "600519"})
        assert saved is not None
        sid = saved["id"]
        assert len(store.list_sources()) == 1
        assert store.get_source(sid)["name"] == "测试源"
        assert store.delete_source(sid) is True
        assert store.list_sources() == []

    def test_update_by_id(self, store):
        s1 = store.save_source({"id": "fixed", "name": "v1", "url": "https://x"})
        s2 = store.save_source({"id": "fixed", "name": "v2", "url": "https://x"})
        assert s1["id"] == s2["id"] == "fixed"
        sources = store.list_sources()
        assert len(sources) == 1 and sources[0]["name"] == "v2"


class TestRefreshAndQuery:
    def _save(self, store):
        return store.save_source(
            {
                "id": "src1",
                "name": "K线源",
                "url": "https://example.com/api/{symbol}",
                "symbol": "600519",
                "records_path": "data.klines",
                "field_map": {
                    "date": "t",
                    "open": "o",
                    "high": "h",
                    "low": "l",
                    "close": "c",
                    "volume": "v",
                },
            }
        )

    def test_refresh_materializes_and_query(self, store):
        self._save(store)
        payload = {
            "data": {
                "klines": [
                    {"t": "2026-01-01", "o": 9, "h": 11, "l": 8, "c": 10, "v": 900},
                    {"t": "2026-01-02", "o": 10, "h": 12, "l": 9, "c": 11, "v": 1000},
                ]
            }
        }
        res = store.refresh_source("src1", fetcher=_good_fetcher(payload))
        assert res["ok"] is True
        assert res["bar_count"] == 2
        assert res["date_range"] == ["2026-01-01", "2026-01-02"]
        # 物化后离线可读
        bars = store.materialized_bars("600519")
        assert len(bars) == 2
        # Provider 读取
        prov = store.HttpJsonProvider()
        got = prov.get_prices({"symbol": "600519"})
        assert len(got) == 2 and got[0]["source"] == "http_json"
        # 源状态更新为 ok
        assert store.get_source("src1")["last_status"] == "ok"

    def test_refresh_failure_keeps_cache(self, store):
        self._save(store)
        ok_payload = {"data": {"klines": [{"t": "2026-01-01", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]}}
        store.refresh_source("src1", fetcher=_good_fetcher(ok_payload))
        assert len(store.materialized_bars("600519")) == 1

        # 抓取失败
        def _bad(**kwargs):
            return {"ok": False, "status": 0, "payload": None, "error": "timeout"}

        res = store.refresh_source("src1", fetcher=_bad)
        assert res["ok"] is False
        assert res.get("kept_cache") is True
        # 既有缓存未被清空
        assert len(store.materialized_bars("600519")) == 1
        assert store.get_source("src1")["last_status"] == "error"

    def test_refresh_bad_records_path(self, store):
        store.save_source(
            {
                "id": "s2",
                "name": "x",
                "url": "https://x",
                "symbol": "000001",
                "records_path": "nope.nope",
                "field_map": {
                    "date": "t",
                    "open": "o",
                    "high": "h",
                    "low": "l",
                    "close": "c",
                },
            }
        )
        res = store.refresh_source("s2", fetcher=_good_fetcher({"data": []}))
        assert res["ok"] is False
        assert "记录路径" in res["error"]

    def test_refresh_unknown_source(self, store):
        res = store.refresh_source("ghost", fetcher=_good_fetcher({}))
        assert res["ok"] is False

    def test_url_symbol_placeholder(self, store):
        store.save_source(
            {
                "id": "s3",
                "name": "x",
                "url": "https://api/{symbol}.json",
                "symbol": "600000",
                "records_path": "",
                "field_map": {
                    "date": "t",
                    "open": "o",
                    "high": "h",
                    "low": "l",
                    "close": "c",
                },
            }
        )
        captured = {}

        def _cap(**kwargs):
            captured["url"] = kwargs.get("url")
            return {
                "ok": True,
                "payload": [{"t": "2026-01-01", "o": 1, "h": 1, "l": 1, "c": 1}],
                "error": None,
            }

        store.refresh_source("s3", fetcher=_cap)
        assert captured["url"] == "https://api/600000.json"


class TestPreviewFetch:
    def test_preview_returns_sample_and_map(self, store):
        payload = {"data": [{"日期": "2026-01-01", "开盘": 1, "收盘": 2, "最高": 3, "最低": 0.5}]}
        res = store.preview_fetch("https://x", records_path="data", fetcher=_good_fetcher(payload))
        assert res["ok"] is True
        assert res["record_count"] == 1
        assert res["inferred_field_map"]["close"] == "收盘"

    def test_preview_failure_safe(self, store):
        def _bad(**kwargs):
            return {"ok": False, "error": "boom"}

        res = store.preview_fetch("https://x", fetcher=_bad)
        assert res["ok"] is False


class TestFetchJsonGuard:
    def test_rejects_bad_url(self):
        # 不触网:非法 URL 直接被拒
        res = hj.fetch_json("ftp://x")
        assert res["ok"] is False

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1:8000/x",
            "http://localhost:8000/x",
            "http://10.0.0.1/x",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    def test_rejects_ssrf_targets(self, url):
        # 不触网:内网/环回/元数据目标在入口校验即被拒(审计 C4)
        res = hj.fetch_json(url)
        assert res["ok"] is False
        assert "not allowed" in res["error"] or "Localhost" in res["error"]
