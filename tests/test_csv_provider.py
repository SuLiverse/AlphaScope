"""CSV/Excel 上传数据源测试(v1.9.4, compass §7.2)。

验证:
- discover_schema 认中英文表头 + 单位后缀
- schema_is_valid 要求 date+OHLC
- parse_rows 升序、跳无效行、标注来源
- CsvUploadProvider.get_prices 按代码匹配文件并解析
- save_upload / list_datasets 概览
- capability() 在新 provider 上正常
"""

from __future__ import annotations

import backend.providers.csv_provider as cp
from backend.providers.csv_provider import (
    CsvUploadProvider,
    discover_schema,
    parse_rows,
    schema_is_valid,
)


def test_discover_schema_english():
    schema = discover_schema(["Date", "Open", "High", "Low", "Close", "Volume"])
    assert schema["date"] == "Date"
    assert schema["open"] == "Open"
    assert schema["close"] == "Close"
    assert schema["volume"] == "Volume"
    assert schema_is_valid(schema)


def test_discover_schema_chinese_with_unit_suffix():
    schema = discover_schema(["日期", "开盘价", "最高", "最低", "收盘价", "成交额(元)"])
    assert schema["date"] == "日期"
    assert schema["open"] == "开盘价"
    assert schema["close"] == "收盘价"
    assert schema["amount"] == "成交额(元)"
    assert schema_is_valid(schema)


def test_schema_invalid_when_missing_ohlc():
    schema = discover_schema(["日期", "收盘价"])  # 缺 open/high/low
    assert not schema_is_valid(schema)


def test_parse_rows_sorted_and_tagged():
    schema = discover_schema(["date", "open", "high", "low", "close", "volume"])
    rows = [
        {
            "date": "2026-01-03",
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10.5",
            "volume": "1000",
        },
        {
            "date": "2026-01-01",
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "10.2",
            "volume": "900",
        },
        {
            "date": "2026-01-02",
            "open": "10",
            "high": "11",
            "low": "9",
            "close": "0",
            "volume": "0",
        },  # 无效收盘, 跳过
    ]
    bars = parse_rows(rows, schema, symbol="600519.SH")
    assert len(bars) == 2  # 跳过 close<=0 行
    assert bars[0]["date"] == "2026-01-01"  # 升序
    assert bars[-1]["date"] == "2026-01-03"
    assert bars[0]["source"] == "csv_upload"
    assert bars[0]["user_upload"] is True
    assert bars[0]["symbol"] == "600519"


def test_parse_rows_respects_limit():
    schema = discover_schema(["date", "open", "high", "low", "close"])
    rows = [
        {
            "date": f"2026-01-{i:02d}",
            "open": "1",
            "high": "2",
            "low": "0.5",
            "close": "1.5",
        }
        for i in range(1, 21)
    ]
    bars = parse_rows(rows, schema, limit=5)
    assert len(bars) == 5
    assert bars[-1]["date"] == "2026-01-20"  # 取最近 5 根


def test_provider_get_prices_from_file(tmp_path, monkeypatch):
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    (csv_dir / "600519.csv").write_text(
        "date,open,high,low,close,volume\n2026-01-02,1680,1700,1670,1690,12000\n2026-01-01,1660,1685,1650,1675,11000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cp, "_csv_dir", lambda: csv_dir)

    prov = CsvUploadProvider()
    assert prov.is_available() is True
    bars = prov.get_prices({"symbol": "600519.SH"})
    assert len(bars) == 2
    assert bars[0]["date"] == "2026-01-01"
    assert bars[-1]["close"] == 1690.0
    assert bars[0]["source"] == "csv_upload"

    # 不存在的代码 → 空
    assert prov.get_prices({"symbol": "000001"}) == []


def test_save_upload_and_list_datasets(tmp_path, monkeypatch):
    csv_dir = tmp_path / "csv"
    csv_dir.mkdir()
    monkeypatch.setattr(cp, "_csv_dir", lambda: csv_dir)

    content = b"date,open,high,low,close\n2026-01-01,1,2,0.5,1.5\n"
    summary = cp.save_upload("000001.csv", content)
    assert summary["valid"] is True
    assert summary["symbol"] == "000001"
    assert "close" in summary["mapped"]

    datasets = cp.list_datasets()
    assert len(datasets) == 1
    assert datasets[0]["filename"] == "000001.csv"


def test_save_upload_rejects_bad_extension(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "_csv_dir", lambda: tmp_path)
    try:
        cp.save_upload("evil.exe", b"x")
        assert False, "应拒绝非 csv/excel 扩展名"
    except ValueError:
        pass


def test_provider_capability_ok():
    cap = CsvUploadProvider().capability()
    assert cap["name"] == "csv_upload"
    assert "prices" in cap["data_types"]
    assert cap["requires_key"] is False
    assert cap["cost_tier"] == "free"
