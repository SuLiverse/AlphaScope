"""CORS 外层化回归 — 401 必须带 Access-Control-Allow-* 头，预检先于鉴权应答。

背景：auth 中间件原在 CORS 外层，令牌缺失时 401 不带 CORS 头，浏览器把它变成
不透明的 "Failed to fetch"，前端令牌引导页（读取 401 状态码）永远不触发，
跨域开发/部署下整站表现为「全部接口失败」。修复后 CORS 注册在最后（最外层）。
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from backend.api import main

ORIGIN = "http://127.0.0.1:3000"
PROTECTED = "/api/settings/preferences"


@pytest.fixture()
def tokened_client(monkeypatch):
    """启用本地 token 鉴权的 TestClient（lifespan 走 ensure_local_api_token 的既有 env）。"""
    monkeypatch.setenv("ALPHASCOPE_LOCAL_API_TOKEN", "test-token-12345")
    monkeypatch.setattr(main, "_local_api_token_cached", None, raising=False)
    with TestClient(main.app) as client:
        yield client


class TestCorsAuthOrder:
    def test_unauthorized_response_carries_cors_headers(self, tokened_client):
        """鉴权 401 也必须带 allow-origin，浏览器才能读到 401 并弹令牌引导页。"""
        resp = tokened_client.get(PROTECTED, headers={"Origin": ORIGIN})
        assert resp.status_code == 401
        assert resp.headers.get("access-control-allow-origin") == ORIGIN

    def test_preflight_answered_before_auth(self, tokened_client):
        """预检 OPTIONS 无 token 也必须 200，且放行 content-type 自定义头。"""
        resp = tokened_client.options(
            PROTECTED,
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == ORIGIN
        assert "content-type" in resp.headers.get("access-control-allow-headers", "")

    def test_authorized_request_still_passes_auth_layer(self, tokened_client):
        """带正确 token 的请求不受 CORS 层外移影响。"""
        resp = tokened_client.get(PROTECTED, headers={"Origin": ORIGIN, main.LOCAL_TOKEN_HEADER: "test-token-12345"})
        assert resp.status_code == 200
