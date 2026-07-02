"""研究存档 API — 列表/统计/读取/删除/后验回填契约测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.api.main import app

    return TestClient(app)


def test_archive_list_stats_combo(client):
    """列表/统计/组合统计端点结构正确,空数据不抛。"""
    r = client.get("/api/archive")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "reports" in body["data"]
    assert "total" in body["data"]

    r = client.get("/api/archive/stats")
    assert r.status_code == 200
    stats = r.json()["data"]
    for k in ("total", "buy", "sell", "hold", "stocks"):
        assert k in stats

    r = client.get("/api/archive/combo-stats")
    assert r.status_code == 200
    assert "combos" in r.json()["data"]


def test_archive_create_and_read(client):
    """新建归档条目后,可在列表中检索到并读取全文。"""
    import time

    sym = f"T{int(time.time()) % 100000}"
    r = client.post(
        "/api/archive",
        json={
            "symbol": sym,
            "stock_name": f"测试股{sym}",
            "content": "# 测试报告\n\n这是一份测试研报。",
            "rating": "建议买入",
            "report_type": "frontend_report",
            "payload": {"confidence": 70},
        },
    )
    assert r.status_code == 200
    assert r.json()["success"] is True
    path = r.json()["data"]["path"]

    # 列表能筛到
    r = client.get(f"/api/archive?stock={sym}")
    items = r.json()["data"]["reports"]
    assert any(i["symbol"] == sym for i in items)

    # 读取全文
    r = client.get(f"/api/archive/report/{path}")
    assert r.status_code == 200
    assert "测试报告" in r.json()["data"]["content"]

    # 删除
    r = client.delete(f"/api/archive/report/{path}")
    assert r.status_code == 200
    assert r.json()["data"]["deleted"] == path


def test_archive_read_illegal_path_rejected(client):
    """路径遍历防护:绝对路径被 400 拒;相对 ../ 被 httpx 规范化为 404。
    两种情况都不得返回报告内容(非 200 成功)。"""
    # 绝对路径 → 路由显式拒绝
    r = client.get("/api/archive/report//etc/passwd")
    assert r.status_code == 400
    # 相对遍历 → 客户端规范化后命中不到路由(404),同样不会泄露内容
    r = client.get("/api/archive/report/../../etc/passwd")
    assert r.status_code != 200


def test_archive_backfill_endpoint(client):
    """后验回填端点存在并返回结构(无数据时 tagged=0,不抛)。"""
    r = client.post("/api/archive/backfill")
    # 端点存在:200(成功)或优雅失败(模块不可用),但不应是 404/500
    assert r.status_code == 200
    body = r.json()
    # 成功时含 tagged/skipped/errors;失败时 success=False + error
    if body.get("success"):
        data = body["data"]
        for k in ("tagged", "skipped", "errors"):
            assert k in data
