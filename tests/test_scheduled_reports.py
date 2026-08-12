"""自选股监控告警 — scheduled_reports 告警检查回归测试。

全部 mock 行情(get_recent_bars),不依赖网络。覆盖计划 021 修复的
"get_price_range 缺参 TypeError + 按 dict 访问元组" 缺陷路径。
"""

from __future__ import annotations

from unittest.mock import patch


def _item(symbol: str = "600519", name: str = "测试股", conditions: dict | None = None):
    from backend.ingestion.scheduled_reports import WatchListItem

    return WatchListItem(
        symbol=symbol,
        name=name,
        alert_conditions=conditions or {},
    )


def _bars(closes, volumes=None):
    """构造 get_recent_bars 返回形状: 按日期升序的 [{date, close, volume}, ...]"""
    volumes = volumes or [1000.0] * len(closes)
    return [
        {
            "date": f"2026-07-{20 + i:02d}",
            "close": float(c),
            "volume": float(v),
        }
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


def test_check_item_alerts_price_change_fires():
    """close 10.0 → 11.0 (+10% ≥ 默认 5% 阈值) 触发 price_change 告警。"""
    from backend.ingestion.scheduled_reports import ScheduledReportManager

    bars = _bars([10.0, 10.0, 10.0, 10.0, 11.0])
    with patch("backend.price_fetcher.get_recent_bars", return_value=bars):
        alerts = ScheduledReportManager()._check_item_alerts(_item())

    assert len(alerts) >= 1
    assert any(a.alert_type == "price_change" for a in alerts)
    assert "600519" in alerts[0].message


def test_check_item_alerts_no_alert_within_threshold():
    """close 波动 <5% 且成交量平稳 → 返回空列表。"""
    from backend.ingestion.scheduled_reports import ScheduledReportManager

    bars = _bars([10.0, 10.1, 10.05, 10.2, 10.15])
    with patch("backend.price_fetcher.get_recent_bars", return_value=bars):
        alerts = ScheduledReportManager()._check_item_alerts(_item())

    assert alerts == []


def test_check_item_alerts_volume_spike_fires():
    """volume 前 4 天 100、最后 1 天 300(>2× 均值)→ volume_spike 告警。"""
    from backend.ingestion.scheduled_reports import ScheduledReportManager

    bars = _bars([10.0] * 5, [100.0, 100.0, 100.0, 100.0, 300.0])
    with patch("backend.price_fetcher.get_recent_bars", return_value=bars):
        alerts = ScheduledReportManager()._check_item_alerts(_item())

    assert len(alerts) >= 1
    assert any(a.alert_type == "volume_spike" for a in alerts)


def test_check_item_alerts_empty_data_ok():
    """行情为空 → 返回空列表、不抛异常。"""
    from backend.ingestion.scheduled_reports import ScheduledReportManager

    with patch("backend.price_fetcher.get_recent_bars", return_value=[]):
        alerts = ScheduledReportManager()._check_item_alerts(_item())

    assert alerts == []


def test_check_alerts_persists_through_store():
    """check_alerts(persist=True) 全链路: watchlist_store 读取 → 告警检查 → alert_store 落库。"""
    from backend import alert_store
    from backend import watchlist_store
    from backend.ingestion.scheduled_reports import ScheduledReportManager

    alert_store.clear_all()
    watchlist_store.add_watchlist("600519", "测试股")
    bars = _bars([10.0, 10.0, 10.0, 10.0, 11.0])
    try:
        with patch("backend.price_fetcher.get_recent_bars", return_value=bars):
            new_alerts = ScheduledReportManager().check_alerts(persist=True)
        assert len(new_alerts) >= 1
    finally:
        watchlist_store.remove_watchlist("600519")
        alert_store.clear_all()
