"""因子生成器测试"""

from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _disable_real_fund_flow_provider():
    with patch("backend.fund_flow.fetch_individual_fund_flow", return_value=None):
        yield


class TestFactorReport:
    """FactorReport 数据类测试"""

    def test_default_values(self):
        from backend.factors.generator import FactorReport

        r = FactorReport(symbol="600519")
        assert r.symbol == "600519"
        assert r.news_sentiment == 0.0
        assert r.event_signal == 0.0
        assert r.analyst_rating == 0.0
        assert r.fund_flow == 0.0
        assert r.momentum == 0.0
        assert r.composite == 0.0
        assert r.news_count == 0

    def test_to_dict(self):
        from backend.factors.generator import FactorReport

        r = FactorReport(symbol="000001", stock_name="平安银行", composite=0.5)
        d = r.to_dict()
        assert d["symbol"] == "000001"
        assert d["stock_name"] == "平安银行"
        assert "factors" in d
        assert d["factors"]["composite"] == 0.5

    def test_computed_at_auto_set(self):
        from backend.factors.generator import FactorReport

        r = FactorReport(symbol="TEST")
        assert r.computed_at  # should be auto-populated


class TestRatingScores:
    """评级映射测试"""

    def test_chinese_ratings(self):
        from backend.factors.generator import _RATING_SCORES

        assert _RATING_SCORES["买入"] == 1.0
        assert _RATING_SCORES["持有"] == 0.0
        assert _RATING_SCORES["卖出"] == -1.0

    def test_english_ratings(self):
        from backend.factors.generator import _RATING_SCORES

        assert _RATING_SCORES["buy"] == 1.0
        assert _RATING_SCORES["hold"] == 0.0
        assert _RATING_SCORES["sell"] == -1.0


class TestEventCategoryScores:
    """事件类型评分测试"""

    def test_all_categories_covered(self):
        from backend.factors.generator import _EVENT_CATEGORY_SCORES

        expected = {
            "earnings",
            "dividend",
            "mna",
            "financing",
            "litigation",
            "policy",
            "supply_chain",
            "insider",
        }
        assert set(_EVENT_CATEGORY_SCORES.keys()) == expected

    def test_litigation_negative(self):
        from backend.factors.generator import _EVENT_CATEGORY_SCORES

        assert _EVENT_CATEGORY_SCORES["litigation"] < 0

    def test_dividend_positive(self):
        from backend.factors.generator import _EVENT_CATEGORY_SCORES

        assert _EVENT_CATEGORY_SCORES["dividend"] > 0


class TestFactorGenerator:
    """FactorGenerator 计算逻辑测试"""

    def _make_db_mock(
        self, news_rows=None, report_rows=None, announcement_rows=None, price_rows=None
    ):
        """创建 Database mock"""
        mock_conn = MagicMock()

        def mock_execute(sql, params=()):
            result = MagicMock()
            if "news_items" in sql and "SELECT" in sql:
                result.fetchall.return_value = news_rows or []
            elif "research_reports" in sql and "SELECT" in sql:
                result.fetchall.return_value = report_rows or []
            elif "announcements" in sql and "SELECT" in sql:
                result.fetchall.return_value = announcement_rows or []
            elif "price_bars" in sql and "SELECT" in sql:
                result.fetchall.return_value = price_rows or []
            else:
                result.fetchall.return_value = []
            return result

        mock_conn.execute = mock_execute

        mock_db = MagicMock()
        mock_db.conn = mock_conn
        # generator 现在走 with Database().transaction() as conn:, 需让 transaction
        # 上下文给出同一 mock_conn(否则 execute 不走 mock_execute)。
        mock_db.transaction.return_value.__enter__.return_value = mock_conn
        mock_db.transaction.return_value.__exit__.return_value = False
        return mock_db

    def test_empty_data_returns_zero_factors(self):
        from backend.factors.generator import FactorGenerator

        gen = FactorGenerator()

        mock_db = self._make_db_mock()
        with (
            patch("backend.storage.db.Database", return_value=mock_db),
            patch("backend.price_store.get_prices", return_value=[]),
        ):
            report = gen.generate("600519", "贵州茅台", days=30)

        assert report.symbol == "600519"
        assert report.news_sentiment == 0.0
        assert report.event_signal == 0.0
        assert report.analyst_rating == 0.0
        assert report.composite == 0.0

    def test_news_sentiment_positive(self):
        from backend.factors.generator import FactorGenerator

        gen = FactorGenerator()

        news_rows = [
            {
                "title": "贵州茅台业绩大增",
                "sentiment": 0.8,
                "importance": 0.9,
                "confidence": 0.8,
                "published_at": "2026-05-10",
            },
            {
                "title": "茅台超预期",
                "sentiment": 0.6,
                "importance": 0.7,
                "confidence": 0.7,
                "published_at": "2026-05-09",
            },
        ]

        mock_db = self._make_db_mock(news_rows=news_rows)
        with (
            patch("backend.storage.db.Database", return_value=mock_db),
            patch("backend.price_store.get_prices", return_value=[]),
        ):
            report = gen.generate("600519", "贵州茅台")

        assert report.news_count == 2
        assert report.news_sentiment > 0

    def test_event_signal_litigation_negative(self):
        from backend.factors.generator import FactorGenerator

        gen = FactorGenerator()

        ann_rows = [
            {
                "title": "收到行政处罚",
                "category": "litigation",
                "importance": 0.9,
                "published_at": "2026-05-10",
            },
        ]

        mock_db = self._make_db_mock(announcement_rows=ann_rows)
        with (
            patch("backend.storage.db.Database", return_value=mock_db),
            patch("backend.price_store.get_prices", return_value=[]),
        ):
            report = gen.generate("000001", "平安银行")

        assert report.event_count == 1
        assert report.event_signal < 0

    def test_analyst_rating_buy(self):
        from backend.factors.generator import FactorGenerator

        gen = FactorGenerator()

        report_rows = [
            {
                "title": "茅台深度报告",
                "rating": "买入",
                "target_price": 2000,
                "institution": "中信证券",
                "published_at": "2026-05-10",
            },
            {
                "title": "茅台点评",
                "rating": "推荐",
                "target_price": 1900,
                "institution": "国泰君安",
                "published_at": "2026-05-09",
            },
        ]

        mock_db = self._make_db_mock(report_rows=report_rows)
        with (
            patch("backend.storage.db.Database", return_value=mock_db),
            patch("backend.price_store.get_prices", return_value=[]),
        ):
            report = gen.generate("600519", "贵州茅台")

        assert report.report_count == 2
        assert report.analyst_rating > 0

    def test_weighted_composite(self):
        from backend.factors.generator import FactorGenerator, FactorReport

        gen = FactorGenerator()

        report = FactorReport(
            symbol="TEST",
            news_sentiment=0.8,
            event_signal=0.6,
            analyst_rating=0.4,
            fund_flow=0.2,
            momentum=0.0,
        )
        composite = gen._weighted_composite(report)
        assert -1.0 <= composite <= 1.0
        assert composite > 0  # all positive factors → positive composite

    def test_fund_flow_uses_fetched_dataframe_for_summary(self):
        from backend.factors.generator import FactorGenerator, FactorReport

        gen = FactorGenerator()
        report = FactorReport(symbol="600519")
        fake_df = MagicMock()
        fake_df.__len__.return_value = 5
        summary = {
            "main_total_yi": 2.5,
            "last_main_yi": 1.25,
            "inflow_days": 4,
            "outflow_days": 1,
        }

        with (
            patch(
                "backend.fund_flow.fetch_individual_fund_flow", return_value=fake_df
            ) as mock_fetch,
            patch(
                "backend.fund_flow.summarize_fund_flow", return_value=summary
            ) as mock_summary,
        ):
            gen._compute_fund_flow(report, "600519", include_signals=True)

        mock_fetch.assert_called_once_with("600519", days=5)
        mock_summary.assert_called_once_with(fake_df, recent_days=5)
        assert report.fund_flow > 0
        assert report.signals[-1]["type"] == "fund_flow"
        assert report.signals[-1]["last_main_yi"] == 1.25

    def test_fund_flow_cached_dataframe_is_degraded_not_missing(self):
        from backend.factors.generator import FactorGenerator, FactorReport

        gen = FactorGenerator()
        report = FactorReport(symbol="600519")
        fake_df = MagicMock()
        fake_df.__len__.return_value = 5
        fake_df.attrs = {"degraded": True, "source_status": "cache"}
        summary = {
            "main_total_yi": 2.5,
            "last_main_yi": 1.25,
            "inflow_days": 4,
            "outflow_days": 1,
        }

        with (
            patch("backend.fund_flow.fetch_individual_fund_flow", return_value=fake_df),
            patch("backend.fund_flow.summarize_fund_flow", return_value=summary),
        ):
            gen._compute_fund_flow(report, "600519", include_signals=True)

        assert report.fund_flow > 0
        assert report.degraded_inputs == ["fund_flow"]
        assert report.missing_dimensions == []

    def test_momentum_uses_clean_price_store_data(self):
        from datetime import datetime, timedelta

        from backend.factors.generator import FactorGenerator, FactorReport

        gen = FactorGenerator()
        report = FactorReport(symbol="600519")
        # 日期相对 now 生成, 始终落在动量的 days 窗口内, 避免硬编码日期随时间漂出
        # 截止线 (now - days) 而成为时间炸弹; 收盘价/成交量保持不变, 数值断言不受影响。
        base = datetime.now()

        def _d(offset: int) -> str:
            return (base - timedelta(days=offset)).strftime("%Y-%m-%d")

        clean_rows = [
            {"date": _d(6), "close": 1296.0, "volume": 10},
            {"date": _d(5), "close": 1290.0, "volume": 12},
            {"date": _d(4), "close": 1286.0, "volume": 14},
            {"date": _d(3), "close": 1273.0, "volume": 16},
        ]

        with patch(
            "backend.price_store.get_prices", return_value=clean_rows
        ) as mock_get_prices:
            gen._compute_momentum(report, "600519", days=30, include_signals=True)

        mock_get_prices.assert_called_once_with("600519", frequency="1d", limit=60)
        signal = report.signals[-1]
        assert signal["type"] == "momentum"
        assert -5 < signal["short_return_pct"] < 0
        assert -5 < signal["mid_return_pct"] < 0
        assert report.momentum < 0

    def test_generate_batch(self):
        from backend.factors.generator import FactorGenerator

        gen = FactorGenerator()

        mock_db = self._make_db_mock()
        with (
            patch("backend.storage.db.Database", return_value=mock_db),
            patch("backend.price_store.get_prices", return_value=[]),
        ):
            reports = gen.generate_batch(
                ["600519", "000001"], {"600519": "贵州茅台", "000001": "平安银行"}
            )

        assert len(reports) == 2
        assert reports[0].symbol == "600519"
        assert reports[1].symbol == "000001"


class TestFormatFactorSummary:
    """因子摘要格式化测试"""

    def test_basic_format(self):
        from backend.factors.generator import FactorReport, format_factor_summary

        report = FactorReport(
            symbol="600519",
            stock_name="贵州茅台",
            composite=0.35,
            news_sentiment=0.6,
            news_count=5,
        )
        text = format_factor_summary(report)
        assert "600519" in text
        assert "贵州茅台" in text
        assert "+0.35" in text
        assert "新闻情绪" in text

    def test_with_signals(self):
        from backend.factors.generator import FactorReport, format_factor_summary

        report = FactorReport(
            symbol="600519",
            signals=[
                {"type": "news", "title": "茅台业绩大增", "sentiment": 0.8},
                {
                    "type": "event",
                    "category": "earnings",
                    "title": "年报发布",
                    "score": 0.5,
                },
            ],
        )
        text = format_factor_summary(report)
        assert "茅台业绩大增" in text
        assert "年报发布" in text


class TestConvenienceFunctions:
    """便捷函数测试"""

    def test_get_factor_generator_singleton(self):
        from backend.factors.generator import get_factor_generator
        import backend.factors.generator as mod

        mod._generator = None  # reset
        gen1 = get_factor_generator()
        gen2 = get_factor_generator()
        assert gen1 is gen2

    def test_generate_factor_report(self):
        from backend.factors.generator import generate_factor_report, FactorReport

        mock_db = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = []
        mock_db.conn = mock_conn
        mock_db.transaction.return_value.__enter__.return_value = mock_conn
        mock_db.transaction.return_value.__exit__.return_value = False

        import backend.factors.generator as mod

        mod._generator = None  # reset singleton

        with patch("backend.storage.db.Database", return_value=mock_db):
            report = generate_factor_report("600519")
        assert isinstance(report, FactorReport)
        assert report.symbol == "600519"
