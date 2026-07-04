"""Database 存储层单元测试"""

import pytest
import tempfile
import os


@pytest.fixture
def tmp_db(monkeypatch):
    """创建临时数据库用于测试"""
    import backend.storage.db as db_mod
    from pathlib import Path

    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir) / "test.db"
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path)
    # 重置单例
    db_mod.Database._instance = None
    db = db_mod.Database()
    yield db
    db.close()
    db_mod.Database._instance = None
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


class TestDatabase:
    def test_tables_created(self, tmp_db):
        cur = tmp_db.conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert "news_items" in tables
        assert "research_reports" in tables
        assert "announcements" in tables
        assert "price_bars" in tables
        assert "source_fetch_logs" in tables
        assert "evidence_items" in tables

    def test_insert_news(self, tmp_db):
        tmp_db.insert_news(
            {
                "id": "news_test_001",
                "title": "测试新闻",
                "source": "cls",
                "summary": "摘要",
            }
        )
        cur = tmp_db.conn.cursor()
        cur.execute("SELECT title FROM news_items WHERE id = ?", ("news_test_001",))
        row = cur.fetchone()
        assert row[0] == "测试新闻"

    def test_insert_report(self, tmp_db):
        tmp_db.insert_report(
            {
                "id": "report_test_001",
                "title": "深度报告",
                "source": "tushare",
                "institution": "中信",
            }
        )
        cur = tmp_db.conn.cursor()
        cur.execute("SELECT title FROM research_reports WHERE id = ?", ("report_test_001",))
        row = cur.fetchone()
        assert row[0] == "深度报告"

    def test_insert_announcement(self, tmp_db):
        tmp_db.insert_announcement(
            {
                "id": "ann_test_001",
                "symbol": "600519",
                "title": "分红公告",
                "source": "cninfo",
            }
        )
        cur = tmp_db.conn.cursor()
        cur.execute("SELECT symbol FROM announcements WHERE id = ?", ("ann_test_001",))
        row = cur.fetchone()
        assert row[0] == "600519"

    def test_insert_fetch_log(self, tmp_db):
        tmp_db.insert_fetch_log(
            {
                "source": "news",
                "endpoint": "CN",
                "status": "success",
                "latency_ms": 150.0,
                "items_count": 10,
            }
        )
        cur = tmp_db.conn.cursor()
        cur.execute("SELECT source, items_count FROM source_fetch_logs ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        assert row[0] == "news"
        assert row[1] == 10

    def test_insert_news_upsert(self, tmp_db):
        """INSERT OR REPLACE 应该更新已有记录"""
        tmp_db.insert_news({"id": "news_upsert", "title": "v1", "source": "cls"})
        tmp_db.insert_news({"id": "news_upsert", "title": "v2", "source": "cls"})
        cur = tmp_db.conn.cursor()
        cur.execute("SELECT title FROM news_items WHERE id = ?", ("news_upsert",))
        row = cur.fetchone()
        assert row[0] == "v2"
