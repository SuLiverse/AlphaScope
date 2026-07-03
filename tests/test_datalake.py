"""DuckDB/Parquet 数据湖测试 — 纯函数组(无需 duckdb)+ duckdb 往返组(importorskip)。"""

from __future__ import annotations

import pytest

import backend.quant.datalake as dl


# ----------------------------- 纯函数组(无需 duckdb) -----------------------------


class TestNormalizeBars:
    def test_dedup_sort_and_types(self):
        bars = [
            {
                "date": "2026-01-02",
                "open": "10",
                "high": "12",
                "low": "9",
                "close": "11",
                "volume": "1000",
            },
            {
                "date": "2026-01-01",
                "open": 9,
                "high": 11,
                "low": 8,
                "close": 10,
                "volume": 900,
            },
            {
                "date": "2026-01-02",
                "open": 10.5,
                "high": 12.5,
                "low": 9.5,
                "close": 11.5,
                "volume": 1100,
            },  # 同日覆盖
        ]
        rows = dl.normalize_bars(bars, "600519")
        assert len(rows) == 2
        assert rows[0]["date"] == "2026-01-01"  # 升序
        assert rows[1]["close"] == 11.5  # 后者覆盖
        assert rows[0]["symbol"] == "600519"
        assert isinstance(rows[0]["open"], float)

    def test_skips_invalid(self):
        bars = [
            {"date": "", "close": 10},
            {"date": "2026-01-01", "close": 0},
            {"date": "2026-01-02", "close": 5},
        ]
        rows = dl.normalize_bars(bars, "x")
        assert len(rows) == 1 and rows[0]["close"] == 5.0


class TestBuildScreenSql:
    def test_valid_filters(self):
        where, params = dl.build_screen_sql(
            [{"field": "close", "op": ">", "value": 100}]
        )
        assert where == "close > ?" and params == [100.0]

    def test_op_aliases(self):
        where, _ = dl.build_screen_sql([{"field": "volume", "op": "==", "value": 1}])
        assert "volume = ?" == where
        where2, _ = dl.build_screen_sql([{"field": "close", "op": "!=", "value": 1}])
        assert "close <> ?" == where2

    def test_rejects_unknown_field_and_op(self):
        # 非白名单字段 / 操作符被跳过(防注入)
        where, params = dl.build_screen_sql(
            [
                {"field": "close); drop table x;--", "op": ">", "value": 1},
                {"field": "close", "op": "LIKE", "value": 1},
                {"field": "open", "op": ">", "value": "notnum"},
            ]
        )
        assert where == "1=1" and params == []

    def test_multiple_anded(self):
        where, params = dl.build_screen_sql(
            [
                {"field": "close", "op": ">=", "value": 10},
                {"field": "volume", "op": ">", "value": 1000},
            ]
        )
        assert where == "close >= ? AND volume > ?"
        assert params == [10.0, 1000.0]


class TestIsSelectOnly:
    def test_allows_select_and_with(self):
        assert dl.is_select_only("SELECT * FROM prices") is True
        assert dl.is_select_only("WITH t AS (SELECT 1) SELECT * FROM t") is True
        assert dl.is_select_only("select symbol from prices;") is True  # 尾分号 ok

    def test_rejects_dml_ddl(self):
        assert dl.is_select_only("DROP TABLE prices") is False
        assert dl.is_select_only("INSERT INTO prices VALUES (1)") is False
        assert dl.is_select_only("COPY prices TO 'x'") is False

    def test_rejects_multistatement(self):
        assert dl.is_select_only("SELECT 1; DROP TABLE prices") is False

    def test_rejects_empty(self):
        assert dl.is_select_only("") is False

    def test_rejects_file_read_functions(self):
        """DuckDB 文件读取表函数可读服务器任意文件, 必须拦截(审计 C5 PoC)。"""
        assert dl.is_select_only(
            "SELECT * FROM read_csv_auto('C:/Windows/System32/drivers/etc/hosts')"
        ) is False
        assert dl.is_select_only("SELECT * FROM read_json_auto('/etc/passwd')") is False
        assert dl.is_select_only("SELECT * FROM read_parquet('/secret/data.parquet')") is False
        # read_csv / read_text 同族也要拦
        assert dl.is_select_only("SELECT * FROM read_csv('/etc/passwd')") is False
        assert dl.is_select_only("SELECT * FROM read_text('/etc/passwd')") is False
        # 大小写混合
        assert dl.is_select_only("select * from READ_CSV_AUTO('x')") is False
        # 空白绕过:函数名与括号间有空格仍命中
        assert dl.is_select_only("SELECT * FROM read_csv_auto ('x')") is False

    def test_file_read_func_not_false_positive(self):
        """文件读函数名作为列名/别名不应误判(词边界 + 括号要求)。"""
        # 无括号不算函数调用
        assert dl.is_select_only("SELECT read_parquet FROM prices") is True
        # 嵌在标识符里(read_parquet 作为列名一部分)
        assert dl.is_select_only("SELECT my_read_parquet_col FROM prices") is True

    def test_set_word_boundary(self):
        """set 关键字词边界精确匹配:独立 set 被拒, 含 set 子串的标识符不误判。"""
        assert dl.is_select_only("SELECT set FROM prices") is False
        # tab/换行绕过旧 "set " 子串匹配
        assert dl.is_select_only("SELECT 1\nset\nx") is False
        # 含 set 子串的标识符不应误判
        assert dl.is_select_only("SELECT offset, dataset, asset FROM prices") is True


def test_degraded_when_unavailable(monkeypatch):
    """duckdb 不可用时所有 duckdb-gated 入口优雅降级, 绝不抛出。"""
    monkeypatch.setattr(dl, "is_available", lambda: False)
    assert (
        dl.ingest_prices("x", [{"date": "2026-01-01", "close": 1}])["available"]
        is False
    )
    assert dl.query("SELECT 1")["available"] is False
    assert dl.screen([])["available"] is False
    assert dl.stats()["available"] is False


# ----------------------------- duckdb 往返组 -----------------------------

duckdb = pytest.importorskip("duckdb")


@pytest.fixture
def lake(tmp_path, monkeypatch):
    """把数据湖目录指向 tmp, 完全隔离。"""
    d = tmp_path / "datalake" / "prices"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dl, "_lake_dir", lambda: d)
    return dl


def _bars(symbol, base=10.0, n=5):
    return [
        {
            "date": f"2026-01-{i:02d}",
            "open": base + i,
            "high": base + i + 1,
            "low": base + i - 1,
            "close": base + i,
            "volume": 1000 + i * 10,
        }
        for i in range(1, n + 1)
    ]


class TestRoundTrip:
    def test_ingest_then_stats(self, lake):
        assert lake.ingest_prices("600519", _bars("600519"))["ok"] is True
        assert lake.ingest_prices("000001", _bars("000001", base=5.0))["ok"] is True
        st = lake.stats()
        assert st["available"] is True
        assert st["symbol_count"] == 2
        assert st["row_count"] == 10
        assert st["date_range"] == ["2026-01-01", "2026-01-05"]
        assert set(lake.list_symbols()) == {"600519", "000001"}

    def test_latest_snapshot(self, lake):
        lake.ingest_prices("600519", _bars("600519"))
        snap = lake.latest_snapshot()
        assert snap["ok"] is True and snap["row_count"] == 1
        assert snap["rows"][0]["date"] == "2026-01-05"  # 最新

    def test_screen_filters(self, lake):
        lake.ingest_prices("600519", _bars("600519", base=100.0))  # latest close = 105
        lake.ingest_prices("000001", _bars("000001", base=5.0))  # latest close = 10
        res = lake.screen([{"field": "close", "op": ">", "value": 50}])
        assert res["ok"] is True
        assert res["matched"] == 1
        assert res["rows"][0]["symbol"] == "600519"
        assert "disclaimer" in res

    def test_query_readonly(self, lake):
        lake.ingest_prices("600519", _bars("600519"))
        res = lake.query("SELECT symbol, COUNT(*) AS n FROM prices GROUP BY symbol")
        assert res["ok"] is True
        assert res["rows"][0]["n"] == 5

    def test_query_rejects_non_select(self, lake):
        lake.ingest_prices("600519", _bars("600519"))
        res = lake.query("DROP TABLE prices")
        assert res["ok"] is False

    def test_query_empty_lake(self, lake):
        res = lake.query("SELECT * FROM prices")
        assert res["ok"] is True and res["row_count"] == 0

    def test_clear_symbol_and_all(self, lake):
        lake.ingest_prices("600519", _bars("600519"))
        lake.ingest_prices("000001", _bars("000001"))
        assert lake.clear_symbol("600519") is True
        assert lake.list_symbols() == ["000001"]
        assert lake.clear_all() == 1
        assert lake.list_symbols() == []
