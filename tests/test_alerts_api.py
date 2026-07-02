"""自选股监控告警 — alert_store + alerts API 契约测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from backend.api.main import app

    return TestClient(app)


def _reset_alerts():
    from backend import alert_store

    alert_store.clear_all()


def test_alert_store_add_dedupe_ack_clear():
    from backend import alert_store

    _reset_alerts()
    assert alert_store.count_unacknowledged() == 0

    # 新增
    assert alert_store.add_alert(
        alert_id="t1",
        symbol="600519",
        name="贵州茅台",
        alert_type="price_change",
        message="测试告警",
        severity="warning",
    )
    assert alert_store.count_unacknowledged() == 1

    # 去重(同 alert_id 返回 False)
    assert not alert_store.add_alert(
        alert_id="t1",
        symbol="600519",
        name="贵州茅台",
        alert_type="price_change",
        message="测试告警",
        severity="warning",
    )
    assert alert_store.count_unacknowledged() == 1

    # 列表
    items = alert_store.list_alerts()
    assert len(items) == 1
    assert items[0]["alert_id"] == "t1"
    assert items[0]["acknowledged"] is False

    # 确认单条
    assert alert_store.acknowledge_alert("t1")
    assert alert_store.count_unacknowledged() == 0
    assert not alert_store.acknowledge_alert("not_exist")

    # 清空
    assert alert_store.clear_all() >= 0
    assert alert_store.count_unacknowledged() == 0


def test_alert_store_unacknowledged_filter():
    from backend import alert_store

    _reset_alerts()
    alert_store.add_alert(
        alert_id="a1", symbol="s1", name="", alert_type="price_change", message="m1"
    )
    alert_store.add_alert(
        alert_id="a2", symbol="s2", name="", alert_type="volume_spike", message="m2"
    )
    alert_store.acknowledge_alert("a1")
    unack = alert_store.list_alerts(unacknowledged_only=True)
    assert {i["alert_id"] for i in unack} == {"a2"}
    alert_store.clear_all()


def test_alerts_api_list_count_ack(client):
    _reset_alerts()
    from backend import alert_store

    alert_store.add_alert(
        alert_id="api1",
        symbol="600519",
        name="贵州茅台",
        alert_type="price_change",
        message="茅台 上涨 5%",
        severity="warning",
    )

    # 列表
    r = client.get("/api/alerts")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    items = body["data"]["items"]
    assert any(i["alert_id"] == "api1" for i in items)

    # 计数
    r = client.get("/api/alerts/count")
    assert r.status_code == 200
    assert r.json()["data"]["unacknowledged"] >= 1

    # 确认单条
    r = client.post("/api/alerts/api1/ack")
    assert r.status_code == 200
    assert r.json()["data"]["acknowledged"] is True

    # 全部已读
    r = client.post("/api/alerts/ack-all")
    assert r.status_code == 200
    assert r.json()["data"]["acknowledged"] >= 0

    alert_store.clear_all()


def test_alerts_api_check_endpoint(client):
    """手动触发扫描:无自选股时 scanned=0,不抛异常。"""
    _reset_alerts()
    r = client.post("/api/alerts/check")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "scanned" in body["data"]
    assert "new" in body["data"]


def test_alerts_api_clear(client):
    from backend import alert_store

    _reset_alerts()
    alert_store.add_alert(
        alert_id="c1", symbol="s", name="", alert_type="price_change", message="m"
    )
    r = client.post("/api/alerts/clear")
    assert r.status_code == 200
    assert r.json()["data"]["cleared"] >= 1
    assert alert_store.count_unacknowledged() == 0


def test_alert_store_concurrent_writes_no_deadlock_or_lock_error():
    """进程级单例 DB + check_same_thread=False: 后台监控线程写 + 请求线程读并发时,
    必须经 transaction() 的 _db_lock 串行化, 不应抛 database is locked。"""
    import threading

    from backend import alert_store

    _reset_alerts()
    errors: list[str] = []

    def writer(start: int):
        try:
            for i in range(start, start + 30):
                alert_store.add_alert(
                    alert_id=f"cw-{start}-{i}",
                    symbol="s",
                    name="",
                    alert_type="price_change",
                    message=f"并发写 {i}",
                )
        except Exception as e:  # noqa: BLE001
            errors.append(f"writer-{start}: {e}")

    def reader():
        try:
            for _ in range(60):
                alert_store.list_alerts()
                alert_store.count_unacknowledged()
        except Exception as e:  # noqa: BLE001
            errors.append(f"reader: {e}")

    threads = [threading.Thread(target=writer, args=(k * 100,)) for k in range(4)]
    threads.append(threading.Thread(target=reader))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"并发访问抛错(锁未生效?): {errors}"
    alert_store.clear_all()
