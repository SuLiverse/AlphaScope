"""Plan 031 回归测试：所有 OpenAI( 构造必须注入 pinned-DNS http_client。

锁住两条历史绕过点的修复：
1. backend/ai_chat.py   — 自定义供应商聊天/模型列表路径（用户 API Key 真实流经）
2. backend/rag/vector_store.py — 向量 embedding 路径

哨兵用例遍历 backend/ 源码，防止未来新增裸 OpenAI( 构造重新引入 DNS rebinding TOCTOU。
全程离线：http_client 工厂与 OpenAI 构造全部打桩，不发起任何真实连接。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

import backend.ai_chat as ai_chat
from backend.rag.vector_store import _OpenAIEmbeddingFunction

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"

FAKE_BASE_URL = "https://api.example.com"  # 仅作打桩透传, 不做 DNS 解析


# ============== 1. ai_chat 自定义供应商路径 ==============


def test_ai_chat_custom_client_injects_pinned_http_client(monkeypatch):
    """_create_custom_client 必须调用 pinned 工厂并把 http_client 传给 OpenAI 构造。"""
    recorded: dict = {}

    def _fake_factory(base_url, *, timeout, local_only=False):
        recorded["factory"] = (base_url, timeout, local_only)
        recorded["http_client"] = marker = httpx.Client()
        return marker

    def _fake_openai(**kwargs):
        recorded["openai_kwargs"] = kwargs
        return MagicMock(name="openai-client-stub")

    monkeypatch.setattr(ai_chat, "create_ssrf_safe_http_client", _fake_factory)
    # normalize_base_url 会做真实 DNS 解析（validate_custom_base_url）, 打桩为恒等保持离线。
    monkeypatch.setattr(ai_chat, "normalize_base_url", lambda url: url)
    monkeypatch.setattr(ai_chat, "OpenAI", _fake_openai)

    client = ai_chat._create_custom_client(FAKE_BASE_URL, "  sk-test  ")

    assert client is not None
    assert recorded["factory"] == (FAKE_BASE_URL, 60.0, False)
    assert recorded["openai_kwargs"]["http_client"] is recorded["http_client"]
    assert recorded["openai_kwargs"]["api_key"] == "sk-test"  # 原有 strip 语义保持
    assert recorded["openai_kwargs"]["timeout"] == 60.0


def test_ai_chat_custom_client_closes_http_client_when_openai_fails(monkeypatch):
    """OpenAI 构造抛错时必须先关闭注入的 http_client 再 raise（参照 gateway.create_client 生命周期）。"""

    class _Boom(Exception):
        pass

    marker = httpx.Client()
    monkeypatch.setattr(ai_chat, "normalize_base_url", lambda url: url)
    monkeypatch.setattr(
        ai_chat,
        "create_ssrf_safe_http_client",
        lambda base_url, *, timeout, local_only=False: marker,
    )

    def _raise(**_kwargs):
        raise _Boom("构造失败")

    monkeypatch.setattr(ai_chat, "OpenAI", _raise)

    with pytest.raises(_Boom):
        ai_chat._create_custom_client(FAKE_BASE_URL, "k")
    assert marker.is_closed


def test_ai_chat_callers_close_client(monkeypatch):
    """fetch_model_list / call_llm_custom 用 try/finally 确保 client.close()（连带关闭 http_client）。"""
    closed: list = []
    stub = MagicMock()
    stub.models.list.return_value = MagicMock(
        data=[MagicMock(id="m2"), MagicMock(id="m1"), MagicMock(id="")]
    )
    stub.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content="hi"))]
    )
    stub.close.side_effect = lambda: closed.append(True)
    monkeypatch.setattr(ai_chat, "_create_custom_client", lambda base_url, api_key: stub)

    ids = ai_chat.fetch_model_list(FAKE_BASE_URL, "k")
    assert ids == ["m1", "m2"]  # 去重 + 排序 + 剔除空 id 语义保持
    assert closed == [True]

    reply = ai_chat.call_llm_custom(
        FAKE_BASE_URL, "k", "model-x", [{"role": "user", "content": "hi"}]
    )
    assert reply == "hi"
    assert closed == [True, True]


# ============== 2. vector_store embedding 路径 ==============


def _patch_embedding_deps(monkeypatch, recorded: dict):
    def _fake_factory(base_url, *, timeout, local_only=False):
        recorded["factory"] = (base_url, timeout, local_only)
        recorded["factory_calls"] = recorded.get("factory_calls", 0) + 1
        return MagicMock(name="http-client-stub")  # 已被 OpenAI 打桩吞掉, 无需真实资源

    def _fake_openai(**kwargs):
        recorded["openai_kwargs"] = kwargs
        return MagicMock(name="openai-client-stub")

    # vector_store 为保持 openai 可选依赖语义采用函数内导入, 因此打桩源模块属性。
    monkeypatch.setattr(
        "backend.models.provider_gateway.create_ssrf_safe_http_client", _fake_factory
    )
    monkeypatch.setattr("openai.OpenAI", _fake_openai)


def test_vector_store_embedding_client_injects_pinned_http_client(monkeypatch):
    """_OpenAIEmbeddingFunction._get_client 懒建时必须注入 pinned http_client 并复用。"""
    recorded: dict = {}
    _patch_embedding_deps(monkeypatch, recorded)

    ef = _OpenAIEmbeddingFunction(
        provider_id="p1",
        model="emb-1",
        base_url="https://api.example.com/v1",
        api_key="k",
    )
    client = ef._get_client()

    assert recorded["factory"] == ("https://api.example.com/v1", 30.0, False)
    assert recorded["openai_kwargs"]["http_client"] is not None
    assert recorded["openai_kwargs"]["timeout"] == 30.0
    assert client is ef._get_client()  # 缓存复用, 不重建
    assert recorded["factory_calls"] == 1


def test_vector_store_embedding_close_then_rebuild(monkeypatch):
    """close() 先关闭旧 client 再置空; 之后 _get_client 会重建（防连接泄漏的释放路径）。"""
    recorded: dict = {}
    _patch_embedding_deps(monkeypatch, recorded)

    ef = _OpenAIEmbeddingFunction(
        provider_id="p1",
        model="emb-1",
        base_url="https://api.example.com/v1",
        api_key="k",
    )
    first = ef._get_client()
    ef.close()
    assert ef._client is None
    assert first.close.called  # openai client 已被显式关闭

    ef._get_client()
    assert recorded["factory_calls"] == 2  # 重建走完整注入路径


# ============== 3. 本地回环 LLM 开关语义（功能回归护栏） ==============


def test_local_llm_loopback_opt_in_still_allowed(monkeypatch):
    """ALLOW_LOCAL_LLM_BASE_URL=1 时回环 base_url 注入 pinned transport 不得被错误拒绝。"""
    from backend.models.provider_gateway import (
        create_ssrf_safe_http_client as real_factory,
    )

    monkeypatch.setenv("ALLOW_LOCAL_LLM_BASE_URL", "1")
    client = real_factory("http://127.0.0.1:8000/v1", timeout=5.0)
    try:
        assert isinstance(client, httpx.Client)
    finally:
        client.close()

    # 未开启开关时回环地址仍被拒绝（默认拒绝语义不回归）
    monkeypatch.delenv("ALLOW_LOCAL_LLM_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        real_factory("http://127.0.0.1:8000/v1", timeout=5.0)


# ============== 4. 防回归哨兵 ==============

# 白名单（活文档）：新增合法裸构造必须同步更新此列表并写明原因。
_WHITELIST = {
    # pinned-DNS transport 工厂 create_ssrf_safe_http_client 与参照实现 create_client 的定义处本身
    "models/provider_gateway.py",
    # 已注入 create_ssrf_safe_http_client 的安全路径（多行构造, http_client= 位于后续行）
    "api/settings.py",
    "settings_store.py",
}


def _openai_call_statements(text: str):
    """产出 (起始行号, 语句文本)。从含 OpenAI( 的行向后拼接至圆括号配平, 兼容多行构造。

    注意 AsyncOpenAI( 也含 OpenAI( 子串, 会被一并检查（其同样接受 http_client=）。
    """
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if "OpenAI(" not in line:
            continue
        depth = line.count("(") - line.count(")")
        parts = [line]
        j = idx
        while depth > 0 and j + 1 < len(lines) and j - idx < 10:
            j += 1
            parts.append(lines[j])
            depth += lines[j].count("(") - lines[j].count(")")
        yield idx + 1, " ".join(parts)


def test_no_bare_openai_constructor_outside_whitelist():
    """backend/ 下非白名单文件中的每个 OpenAI( 构造都必须带 http_client=。"""
    offenders = []
    for path in sorted(BACKEND_DIR.rglob("*.py")):
        rel = path.relative_to(BACKEND_DIR).as_posix()
        if rel in _WHITELIST:
            continue
        for lineno, stmt in _openai_call_statements(
            path.read_text(encoding="utf-8")
        ):
            if "http_client=" not in stmt:
                offenders.append(f"backend/{rel}:{lineno}")
    assert offenders == [], (
        "以下 OpenAI( 构造未注入 pinned-DNS http_client（DNS rebinding 风险）, "
        "请按 provider_gateway.create_client 参照用法修复或更新白名单:\n"
        + "\n".join(offenders)
    )
