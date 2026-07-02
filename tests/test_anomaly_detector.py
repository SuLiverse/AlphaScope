"""anomaly_detector 单元测试 — 数据质量检测纯函数。

pipeline 已接线(check_price/check_news 在落库前调用), 这里覆盖检测器自身的
核心逻辑: 零负价/高低倒挂/涨跌停(主板 10% vs 创业板科创板 20%)/标题过短/乱码/
重复时间戳/批量/单例。纯函数, 快速, 锁住行为防回归。
"""

from __future__ import annotations

from backend.quality.anomaly_detector import AnomalyDetector, get_anomaly_detector


# ---------------- check_price ----------------


def test_check_price_clean_bar_no_anomalies():
    d = AnomalyDetector()
    bar = {"open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "date": "2025-01-01"}
    assert d.check_price(bar, history=None, symbol="600519") == []


def test_check_price_zero_and_negative_prices():
    d = AnomalyDetector()
    # 收盘 0 + 开盘负 + 最高负 + 最低负
    bar = {"open": -1, "high": -2, "low": -3, "close": 0, "volume": 100, "date": "x"}
    anomalies = d.check_price(bar, history=None, symbol="600519")
    assert any("收盘价异常" in a for a in anomalies)
    assert any("开盘价异常" in a for a in anomalies)
    assert any("最高价异常" in a for a in anomalies)
    assert any("最低价异常" in a for a in anomalies)


def test_check_price_high_below_low():
    d = AnomalyDetector()
    bar = {"open": 10, "high": 5, "low": 9, "close": 8, "volume": 100, "date": "x"}
    anomalies = d.check_price(bar, history=None, symbol="600519")
    assert any("最高价" in a and "最低价" in a for a in anomalies)


def test_check_price_limit_up_main_board_10pct():
    """主板涨跌停 10%: 涨 11% 报异常, 涨 9% 不报。"""
    d = AnomalyDetector()
    history = [{"close": 10}]
    bar_up = {"open": 10, "high": 12, "low": 10, "close": 11.1, "volume": 100, "date": "x"}
    anomalies = d.check_price(bar_up, history=history, symbol="600519")
    assert any("涨跌停" in a or "涨跌幅" in a for a in anomalies)

    bar_ok = {"open": 10, "high": 12, "low": 10, "close": 10.9, "volume": 100, "date": "x"}
    assert d.check_price(bar_ok, history=history, symbol="600519") == []


def test_check_price_limit_chinext_star_20pct():
    """创业板(300)/科创板(688)涨跌停 20%: 涨 15% 不报, 涨 21% 报。"""
    d = AnomalyDetector()
    history = [{"close": 10}]
    bar_ok = {"open": 10, "high": 12, "low": 10, "close": 11.5, "volume": 100, "date": "x"}
    assert d.check_price(bar_ok, history=history, symbol="300750") == []  # 创业板 15% OK

    bar_over = {"open": 10, "high": 13, "low": 10, "close": 12.2, "volume": 100, "date": "x"}
    anomalies = d.check_price(bar_over, history=history, symbol="688981")  # 科创板 22% 超
    assert any("涨跌幅" in a for a in anomalies)


def test_check_price_zero_volume_with_price_change():
    d = AnomalyDetector()
    history = [{"close": 10}]
    bar = {"open": 11, "high": 12, "low": 11, "close": 11, "volume": 0, "date": "x"}
    anomalies = d.check_price(bar, history=history, symbol="600519")
    assert any("成交量为0" in a for a in anomalies)


# ---------------- check_news ----------------


def test_check_news_clean_title():
    d = AnomalyDetector()
    news = {"title": "贵州茅台发布年度业绩报告", "datetime": "2025-01-01", "source": "x"}
    assert d.check_news(news, all_news=None) == []


def test_check_news_short_title():
    d = AnomalyDetector()
    news = {"title": "ab", "datetime": "2025-01-01", "source": "x"}
    anomalies = d.check_news(news, all_news=None)
    assert any("标题过短" in a for a in anomalies)


def test_check_news_garbled_title():
    d = AnomalyDetector()
    # 纯乱码(非中文非 ASCII 占比高)
    news = {"title": "ï¿½ï¿½ï¿½ï¿½ï¿½ï¿½ï¿½ï¿½", "datetime": "2025-01-01", "source": "x"}
    anomalies = d.check_news(news, all_news=None)
    assert any("乱码" in a for a in anomalies)


def test_check_news_duplicate_timestamp():
    """同一时间戳同标题超过阈值(默认 3)报重复。"""
    d = AnomalyDetector()
    dt = "2025-01-01"
    title = "某公司发布公告"
    all_news = [{"title": title, "datetime": dt}] * 5
    anomalies = d.check_news(all_news[0], all_news=all_news)
    assert any("同一时间戳" in a or "出现" in a for a in anomalies)


# ---------------- _is_garbled / _get_price_limit ----------------


def test_is_garbled_pure_chinese_false():
    d = AnomalyDetector()
    assert d._is_garbled("贵州茅台年度报告") is False


def test_is_garbled_pure_ascii_false():
    d = AnomalyDetector()
    assert d._is_garbled("Alibaba Group Holding Ltd") is False  # ASCII 占比高


def test_is_garbled_mixed_garbled_true():
    d = AnomalyDetector()
    assert d._is_garbled("ï¿½ï¿½ï¿½ï¿½ï¿½") is True


def test_is_garbled_empty_false():
    d = AnomalyDetector()
    assert d._is_garbled("") is False


def test_get_price_limit_main_vs_chinext_star():
    d = AnomalyDetector()
    assert d._get_price_limit("600519") == 10.0  # 主板
    assert d._get_price_limit("000001") == 10.0  # 深主板
    assert d._get_price_limit("300750") == 20.0  # 创业板
    assert d._get_price_limit("688981") == 20.0  # 科创板
    assert d._get_price_limit("") == 10.0  # 缺省主板


# ---------------- check_batch ----------------


def test_check_batch_aggregates_price_and_news():
    d = AnomalyDetector()
    prices = [
        {"open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "date": "2025-01-01"},
        {"open": 10, "high": 5, "low": 9, "close": 10, "volume": 100, "date": "2025-01-02"},  # 高<低
    ]
    news = [
        {"title": "正常新闻标题字数足够", "datetime": "2025-01-01", "source": "x"},
        {"title": "ab", "datetime": "2025-01-01", "source": "x"},  # 过短
    ]
    result = d.check_batch(prices=prices, news=news, symbol="600519")
    assert result["total_anomalies"] == 2
    assert len(result["price_anomalies"]) == 1
    assert len(result["news_anomalies"]) == 1


def test_check_batch_empty_inputs():
    d = AnomalyDetector()
    result = d.check_batch()
    assert result["total_anomalies"] == 0
    assert result["price_anomalies"] == []
    assert result["news_anomalies"] == []


# ---------------- 单例 ----------------


def test_get_anomaly_detector_singleton():
    a = get_anomaly_detector()
    b = get_anomaly_detector()
    assert a is b
