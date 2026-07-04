"""数据核验 Agent 测试(v1.9.4, compass §7.3)。

验证确定性数据完整性预检:
- 维度齐全 → COMPLETE, 不产生简报警示
- 价格缺失 → INSUFFICIENT
- 补充维度缺失 → MISSING + 简报「严禁编造」提示
- 数值异常(RSI 越界/高低倒挂) → ANOMALY
- 过期日期 → STALE
- 任意脏输入不抛异常
"""

from __future__ import annotations

from backend.agents.data_verifier import (
    ANOMALY,
    COMPLETE,
    INSUFFICIENT,
    MISSING,
    OK,
    PARTIAL,
    STALE,
    verify_data,
)


def _full_stock_data() -> dict:
    return {
        "symbol": "600519",
        "name": "贵州茅台",
        "close": 1680.0,
        "period_high": 1720.0,
        "period_low": 1600.0,
        "ma5": 1675.0,
        "ma20": 1650.0,
        "rsi": 56.0,
        "macd": 1.2,
        "fundamentals": "PE 28x, ROE 30%",
        "stock_fund_brief": "主力净流入 2.3 亿",
        "related_news_brief": "公司发布提价公告",
    }


def test_complete_data_passes_clean():
    v = verify_data(_full_stock_data())
    assert v.overall == COMPLETE
    # 全部维度可用时不污染简报
    assert v.brief_warning() == ""
    assert "通过" in v.headline()


def test_missing_price_is_insufficient():
    sd = _full_stock_data()
    sd["close"] = 0
    v = verify_data(sd)
    assert v.overall == INSUFFICIENT
    price = next(d for d in v.dimensions if d.dimension == "price")
    assert price.status == MISSING
    assert "仅供参考" in v.headline()


def test_missing_supplementary_dims_flagged():
    sd = {
        "close": 100.0,
        "ma5": 99.0,
        "rsi": 50.0,
        # 无 fundamentals / fund_flow / news
    }
    v = verify_data(sd)
    assert v.overall == PARTIAL
    labels = {d.dimension: d.status for d in v.dimensions}
    assert labels["fundamental"] == MISSING
    assert labels["fund_flow"] == MISSING
    assert labels["news"] == MISSING
    warn = v.brief_warning()
    assert "严禁" in warn
    assert "基本面" in warn
    assert "不得臆造" in warn


def test_rsi_out_of_range_is_anomaly():
    sd = _full_stock_data()
    sd["rsi"] = 150.0
    v = verify_data(sd)
    tech = next(d for d in v.dimensions if d.dimension == "technical")
    assert tech.status == ANOMALY
    assert any("RSI" in a for a in v.anomalies)


def test_high_low_inverted_is_anomaly():
    sd = _full_stock_data()
    sd["period_high"] = 1500.0
    sd["period_low"] = 1700.0
    v = verify_data(sd)
    price = next(d for d in v.dimensions if d.dimension == "price")
    assert price.status == ANOMALY
    assert any("倒挂" in d.detail for d in v.dimensions if d.dimension == "price")


def test_stale_date_downgrades_price():
    sd = _full_stock_data()
    sd["as_of"] = "2020-01-01"  # 远早于今天
    v = verify_data(sd)
    price = next(d for d in v.dimensions if d.dimension == "price")
    assert price.status == STALE
    assert "数据可能过期" in v.brief_warning()


def test_evidence_pool_included_when_provided():
    sd = _full_stock_data()
    v_with = verify_data(sd, evidence_pool=[{"evidence_id": "e1"}])
    assert any(d.dimension == "evidence" and d.status == OK for d in v_with.dimensions)
    v_empty = verify_data(sd, evidence_pool=[])
    assert any(d.dimension == "evidence" and d.status == MISSING for d in v_empty.dimensions)
    # 不提供时不纳入 evidence 维度
    v_none = verify_data(sd)
    assert not any(d.dimension == "evidence" for d in v_none.dimensions)


def test_to_dict_shape():
    v = verify_data(_full_stock_data())
    d = v.to_dict()
    for key in (
        "overall",
        "dimensions",
        "missing",
        "stale",
        "ok",
        "anomalies",
        "summary",
    ):
        assert key in d
    assert isinstance(d["dimensions"], list)
    assert all("label" in dim and "status" in dim for dim in d["dimensions"])


def test_garbage_input_never_throws():
    # None / 空 / 错误类型都应安全降级
    for bad in (None, {}, {"close": "abc"}, {"rsi": "NaN"}, []):
        v = verify_data(bad if isinstance(bad, dict) else {})
        assert v.overall in (COMPLETE, PARTIAL, INSUFFICIENT)
        assert isinstance(v.to_dict(), dict)
