"""Tests for shared ConversationStore in chat endpoints — 聊天端点共享 ConversationStore 防连接泄漏"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

import backend.api.main as api_main
from backend.ai_assistant.orchestrator import ChatOrchestrator


@pytest.fixture(autouse=True)
def _reset_shared_store():
    # _shared_conversation_store 是模块态(惰性单例), 每个用例前重置以便独立验证懒加载;
    # 用例后保留现场, 与运行中 API 进程的行为一致。
    api_main._shared_conversation_store = None
    yield


def test_get_conversation_store_returns_same_instance():
    """调用两次 _get_conversation_store() 返回同一对象(惰性单例)"""
    store1 = api_main._get_conversation_store()
    store2 = api_main._get_conversation_store()
    assert store1 is store2


def test_shared_store_does_not_own_connection():
    """共享 store 绑定 Database 单例, _own_conn 必须为 False(不再每请求自开连接)"""
    store = api_main._get_conversation_store()
    assert store._own_conn is False


def test_orchestrators_share_same_connection():
    """两个 ChatOrchestrator(store=...) 实例共享同一 store._conn"""
    orch1 = ChatOrchestrator(store=api_main._get_conversation_store())
    orch2 = ChatOrchestrator(store=api_main._get_conversation_store())
    assert orch1._store._conn is orch2._store._conn
