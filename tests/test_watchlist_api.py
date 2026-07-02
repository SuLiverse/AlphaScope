"""D · 自选股后端持久化 API 测试(隔离 DB)。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from backend.api.main import app
import backend.storage.db as db_mod

client = TestClient(app)


@pytest.fixture
def tmp_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    tmp = Path(path)
    monkeypatch.setattr(db_mod, "DB_PATH", tmp)
    db_mod.Database._instance = None
    # 重置 watchlist_store 的 _schema_ensured: 临时 DB 是空的, 必须重新建表。
    # 该 flag 是模块级全局, 不随 Database._instance 重置, 跨测试会污染。
    from backend import watchlist_store

    watchlist_store._schema_ensured = False
    yield tmp
    db_mod.Database._instance = None
    try:
        os.unlink(tmp)
    except OSError:
        pass


def test_watchlist_crud(tmp_db):
    assert client.get("/api/watchlist").json()["data"]["items"] == []

    r = client.post("/api/watchlist", json={"symbol": "600519", "name": "贵州茅台"})
    items = r.json()["data"]["items"]
    assert any(i["symbol"] == "600519" for i in items)

    # 重复加入不产生重复行(更新名称)
    client.post("/api/watchlist", json={"symbol": "600519", "name": "茅台"})
    items = client.get("/api/watchlist").json()["data"]["items"]
    assert sum(1 for i in items if i["symbol"] == "600519") == 1
    assert next(i for i in items if i["symbol"] == "600519")["name"] == "茅台"

    r = client.delete("/api/watchlist/600519")
    assert r.json()["data"]["items"] == []


def test_watchlist_validates_symbol(tmp_db):
    r = client.post("/api/watchlist", json={"symbol": "", "name": "x"})
    assert r.status_code == 422
