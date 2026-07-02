"""tickflow API 请求体校验测试 — SourceBody/PreviewBody 的 url/method 校验。

防止无效 url(非 http/https)和非 GET/POST method 进到 dispatch 时才崩。
Pydantic 模型层校验, 无需 client。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

pytest.importorskip("fastapi")


def test_source_body_accepts_http_and_https():
    from backend.api.tickflow import PreviewBody, SourceBody

    assert SourceBody(url="http://example.com/api").url == "http://example.com/api"
    assert SourceBody(url="https://x.com/api").url == "https://x.com/api"
    assert SourceBody(url="").url == ""  # 空允许(后续步骤可填)
    # PreviewBody 同款校验
    assert PreviewBody(url="https://x.com/api").url == "https://x.com/api"


def test_source_body_rejects_non_http_url():
    from backend.api.tickflow import PreviewBody, SourceBody

    for bad in ("ftp://x", "example.com/api", "file:///etc/passwd", "javascript:alert(1)"):
        with pytest.raises(ValidationError):
            SourceBody(url=bad)
        with pytest.raises(ValidationError):
            PreviewBody(url=bad)


def test_source_body_method_literal_get_post():
    from backend.api.tickflow import SourceBody

    assert SourceBody(method="GET").method == "GET"
    assert SourceBody(method="POST").method == "POST"
    # 小写也接受(Literal 大小写敏感, 但 Pydantic 对 Literal 不自动转; 这里测原样)
    # 非 GET/POST 应被拒
    for bad in ("PUT", "DELETE", "get"):
        with pytest.raises(ValidationError):
            SourceBody(method=bad)
