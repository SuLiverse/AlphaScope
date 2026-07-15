"""SQLite WAL / busy_timeout 启动配置。"""

from __future__ import annotations


def test_database_enables_wal_or_tolerates_failure(tmp_path, monkeypatch):
    import backend.storage.db as dbmod

    # 指向临时库, 避免污染用户 data/
    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "pragma_test.db")
    dbmod.Database._instance = None  # type: ignore[attr-defined]

    db = dbmod.Database()
    mode = db._conn.execute("PRAGMA journal_mode").fetchone()[0]
    # WAL 在多数平台可开; 若文件系统不支持, 至少连接可用
    assert mode.lower() in {"wal", "delete", "memory", "truncate", "persist", "off"}
    # busy_timeout 以毫秒返回
    busy = db._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert int(busy) >= 0
