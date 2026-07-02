"""DataPipeline 数据管道单元测试"""

from unittest.mock import MagicMock, patch


class TestPipelineDataConversion:
    """测试 Pipeline 的数据格式转换"""

    def test_to_news_row(self):
        from backend.pipeline import DataPipeline

        item = {
            "title": "茅台提价",
            "source": "cls",
            "summary": "摘要",
            "datetime": "2026-05-18",
            "url": "https://example.com",
            "symbols": ["600519.SH"],
        }
        row = DataPipeline._to_news_row(item)
        assert row["title"] == "茅台提价"
        assert row["source"] == "cls"
        assert row["source_url"] == "https://example.com"
        assert "2026-05-18" in row["published_at"]
        assert row["symbols"] == ["600519.SH"]

    def test_to_report_row(self):
        from backend.pipeline import DataPipeline

        item = {
            "title": "深度报告",
            "source": "tushare",
            "institution": "中信",
            "datetime": "2026-05-18",
            "rating": "买入",
        }
        row = DataPipeline._to_report_row(item)
        assert row["title"] == "深度报告"
        assert row["institution"] == "中信"
        assert row["rating"] == "买入"

    def test_to_announcement_row(self):
        from backend.pipeline import DataPipeline

        item = {
            "title": "分红公告",
            "source": "cninfo",
            "symbol": "600519",
            "datetime": "2026-05-18",
            "url": "https://cninfo.com/xxx",
        }
        row = DataPipeline._to_announcement_row(item)
        assert row["symbol"] == "600519"
        assert row["source_url"] == "https://cninfo.com/xxx"

    def test_to_news_row_missing_fields(self):
        """缺少字段时应使用默认值"""
        from backend.pipeline import DataPipeline

        item = {"title": "只有标题"}
        row = DataPipeline._to_news_row(item)
        assert row["source"] == ""
        assert row["confidence"] == 0.6
        assert row["symbols"] == []


class TestPipelineStatus:
    def test_status_structure(self):
        """测试 status() 返回结构"""
        # 需要 mock 掉实际的 DB 和 Registry 初始化
        with (
            patch("backend.pipeline.get_registry") as mock_reg,
            patch("backend.pipeline.Database") as mock_db,
            patch("backend.pipeline.Deduplicator"),
            patch("backend.pipeline.SourceRanker"),
        ):
            mock_reg.return_value = MagicMock(
                list_providers=MagicMock(return_value=[{"name": "test"}]),
                get_all_health=MagicMock(return_value=[]),
            )
            # status() 现在走 with self._db.transaction() as conn: (PRAGMA 只读)
            mock_conn = MagicMock()
            mock_conn.execute.return_value.fetchone.return_value = (0, "main", "test.db")
            mock_db_inst = MagicMock()
            mock_db_inst.transaction.return_value.__enter__.return_value = mock_conn
            mock_db_inst.transaction.return_value.__exit__.return_value = False
            # 兼容旧 .conn 访问路径(若有)
            mock_db_inst.conn = mock_conn
            mock_db.return_value = mock_db_inst
            from backend.pipeline import DataPipeline

            DataPipeline._instance = None
            p = DataPipeline()
            s = p.status()
            assert "providers" in s
            assert "db_path" in s
            assert "timestamp" in s
            DataPipeline._instance = None
