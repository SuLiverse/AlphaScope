"""通知推送渠道 — 配置存储 + API 契约 + 分发纯函数测试。"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# 测试环境无 AI_FINANCE_MASTER_KEY, 启用开发 fallback key 让 key_vault 加解密可往返。
# (生产由 .env 的 master key 保护;此处仅测试落库/解密逻辑,不涉及真实密钥。)
os.environ.setdefault("AI_FINANCE_ALLOW_DEV_KEY_FALLBACK", "1")


@pytest.fixture()
def client():
    from backend.api.main import app

    return TestClient(app)


# ---------------- 配置存储(加密落库) ----------------


def _clear_channels():
    from backend import notifier_store

    for ch in list(notifier_store.list_channels()):
        notifier_store.delete_channel(ch["channel"])


def test_store_save_list_decrypt():
    from backend import notifier_store

    _clear_channels()
    notifier_store.save_channel(
        "serverchan", enabled=True, config={"sckey": "SCT123abc"}
    )
    items = notifier_store.list_channels()
    assert any(c["channel"] == "serverchan" and c["enabled"] for c in items)

    # 凭证明文不应出现在列表(只回传 has_credentials / fields_configured)
    item = next(c for c in items if c["channel"] == "serverchan")
    assert item["has_credentials"] is True
    assert item["fields_configured"]["sckey"] is True
    assert "SCT123abc" not in str(item)

    # 内部读取可解密
    cfg = notifier_store.get_channel_config("serverchan")
    assert cfg.get("sckey") == "SCT123abc"
    assert cfg.get("_enabled") is True
    _clear_channels()


# ---------------- API 契约 ----------------


def test_api_unknown_channel_rejected(client):
    r = client.post("/api/notifiers/bogus", json={"enabled": True, "config": {}})
    assert r.status_code == 400


def test_api_save_list_delete(client):
    _clear_channels()
    r = client.post(
        "/api/notifiers/pushplus",
        json={"enabled": True, "config": {"token": "tok_abc"}},
    )
    assert r.status_code == 200
    items = r.json()["data"]["channels"]
    assert any(c["channel"] == "pushplus" for c in items)

    r = client.get("/api/notifiers")
    assert r.status_code == 200
    # 凭证明文不泄露
    assert "tok_abc" not in r.text

    r = client.delete("/api/notifiers/pushplus")
    assert r.status_code == 200
    _clear_channels()


def test_api_dispatch_no_channels(client):
    """无启用渠道时返回 sent=0,不抛。"""
    _clear_channels()
    r = client.post("/api/notifiers/dispatch", json={"title": "t", "body": "b"})
    assert r.status_code == 200
    assert r.json()["data"]["total"] == 0


def test_api_dispatch_alerts_empty(client):
    from backend import alert_store

    alert_store.clear_all()
    r = client.post("/api/notifiers/dispatch-alerts")
    assert r.status_code == 200
    assert r.json()["data"]["reason"] == "无未确认告警"


def test_api_dispatch_alerts_all_succeed_marks_acked(client):
    """全部渠道成功 → acknowledge_all, 告警不再未确认。"""
    from backend import alert_store
    from backend import notifier_store

    _clear_channels()
    alert_store.clear_all()
    alert_store.add_alert(
        alert_id="d1", symbol="s", name="", alert_type="price_change", message="m1"
    )
    # 配两个启用渠道
    notifier_store.save_channel("serverchan", True, {"sckey": "SCT1"})
    notifier_store.save_channel("pushplus", True, {"token": "tok1"})

    with patch(
        "backend.notifiers._http_get", return_value={"ok": True, "status": 200, "body": "{}"}
    ):
        r = client.post("/api/notifiers/dispatch-alerts")
    data = r.json()["data"]
    assert data["all_succeeded"] is True
    assert data["acknowledged"] >= 1
    assert alert_store.count_unacknowledged() == 0
    _clear_channels()
    alert_store.clear_all()


def test_api_dispatch_alerts_partial_fail_keeps_unacked(client):
    """部分渠道失败 → 不标读, 告警保留以便下次重试。"""
    from backend import alert_store
    from backend import notifier_store

    _clear_channels()
    alert_store.clear_all()
    alert_store.add_alert(
        alert_id="d2", symbol="s", name="", alert_type="price_change", message="m2"
    )
    notifier_store.save_channel("serverchan", True, {"sckey": "SCT1"})
    notifier_store.save_channel("pushplus", True, {"token": "tok1"})

    # serverchan 走 _http_get, pushplus 走 _http_post_json; 让 post 失败
    def fake_get(url, timeout=10):
        return {"ok": True, "status": 200, "body": "{}"}

    def fake_post(url, payload, headers=None, timeout=10):
        return {"ok": False, "error": "HTTP 500"}

    import backend.notifiers as N

    with patch.object(N, "_http_get", side_effect=fake_get), patch.object(
        N, "_http_post_json", side_effect=fake_post
    ):
        r = client.post("/api/notifiers/dispatch-alerts")
    data = r.json()["data"]
    assert data["all_succeeded"] is False
    assert data["acknowledged"] == 0
    # 告警仍为未确认(失败渠道下次可重试)
    assert alert_store.count_unacknowledged() == 1
    _clear_channels()
    alert_store.clear_all()


# ---------------- 分发纯函数(mock 网络) ----------------


def test_dispatch_unknown_channel():
    from backend.notifiers import dispatch

    r = dispatch("bogus", {}, "t", "b")
    assert r.ok is False
    assert "未知渠道" in r.message


def test_dispatch_serverchan_missing_key():
    from backend.notifiers import send_serverchan

    r = send_serverchan("", "t", "b")
    assert r.ok is False
    assert "SendKey" in r.message


def test_dispatch_serverchan_success_mock():
    from backend.notifiers import send_serverchan

    with patch("backend.notifiers._http_get", return_value={"ok": True, "status": 200, "body": "{}"}):
        r = send_serverchan("SCT123", "title", "body")
    assert r.ok is True
    assert r.channel == "serverchan"


def test_dispatch_feishu_invalid_webhook():
    from backend.notifiers import send_feishu

    r = send_feishu("https://example.com/hook", "t", "b")
    assert r.ok is False  # 非飞书地址被拒


def test_dispatch_feishu_truncates_long_body():
    """飞书消息体应在 ~3500 字处截断, [:3500] 不能作为字面文本泄漏到消息里。"""
    from backend.notifiers import send_feishu

    captured = {}

    def _fake_post(url, payload, headers=None, timeout=10):
        captured["payload"] = payload
        return {"ok": True, "status": 200, "body": "{}"}

    with patch("backend.notifiers._http_post_json", side_effect=_fake_post):
        long_body = "X" * 10000
        r = send_feishu("https://open.feishu.cn/open-apis/bot/v2/hook/xxx", "T", long_body)
    assert r.ok is True
    text = captured["payload"]["content"]["text"]
    # 消息体被截断到上限内, 不再是完整 10000 字 + 杂散 [:3500]
    assert len(text) <= 3500
    assert "[:3500]" not in text
    assert text.startswith("T")  # 标题保留


def test_dispatch_email_missing_config():
    from backend.notifiers import send_email

    r = send_email("", 587, "", "", "", "", "t", "b")
    assert r.ok is False
    assert "SMTP" in r.message
