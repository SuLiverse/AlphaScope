"""ConversationStore 持久化层单元测试"""

import pytest
import tempfile
import os
from pathlib import Path


@pytest.fixture
def tmp_store(monkeypatch):
    """创建临时 ConversationStore 用于测试"""
    import backend.storage.db as db_mod
    import backend.ai_assistant.conversation_store as cs_mod

    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir) / "test_ai.db"
    monkeypatch.setattr(db_mod, "DB_PATH", tmp_path)
    # 重置单例
    db_mod.Database._instance = None

    from backend.storage.db import Database

    db = Database()
    store = cs_mod.ConversationStore(db=db)
    yield store
    db.close()
    db_mod.Database._instance = None
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


class TestConversationStore:
    def test_tables_created(self, tmp_store):
        """测试 AI 对话表是否创建"""
        cur = tmp_store._conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        assert "ai_conversations" in tables
        assert "ai_messages" in tables

    def test_create_conversation(self, tmp_store):
        """测试创建对话"""
        conv_id = tmp_store.create_conversation(
            title="测试对话",
            stock_symbol="600519",
            stock_name="贵州茅台",
            mode="deep",
            provider="deepseek",
            model="deepseek-chat",
        )
        assert conv_id
        assert len(conv_id) == 16

        conv = tmp_store.get_conversation(conv_id)
        assert conv is not None
        assert conv["title"] == "测试对话"
        assert conv["stock_symbol"] == "600519"
        assert conv["mode"] == "deep"

    def test_add_message(self, tmp_store):
        """测试添加消息"""
        conv_id = tmp_store.create_conversation(title="测试")
        msg_id = tmp_store.add_message(conv_id, "user", "你好")
        assert msg_id > 0

        msg_id2 = tmp_store.add_message(conv_id, "assistant", "你好！有什么可以帮你的？")
        assert msg_id2 > msg_id

        count = tmp_store.get_message_count(conv_id)
        assert count == 2

    def test_get_messages(self, tmp_store):
        """测试获取消息列表"""
        conv_id = tmp_store.create_conversation(title="测试")
        tmp_store.add_message(conv_id, "user", "问题1")
        tmp_store.add_message(conv_id, "assistant", "回答1")
        tmp_store.add_message(conv_id, "user", "问题2")

        messages = tmp_store.get_messages(conv_id)
        assert len(messages) == 3
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "问题1"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["content"] == "问题2"

    def test_list_conversations(self, tmp_store):
        """测试列出对话"""
        tmp_store.create_conversation(title="对话1", stock_symbol="600519")
        tmp_store.create_conversation(title="对话2", stock_symbol="300750")
        tmp_store.create_conversation(title="对话3")

        all_convs = tmp_store.list_conversations()
        assert len(all_convs) == 3

        filtered = tmp_store.list_conversations(stock_symbol="600519")
        assert len(filtered) == 1
        assert filtered[0]["title"] == "对话1"

    def test_update_title(self, tmp_store):
        """测试更新标题"""
        conv_id = tmp_store.create_conversation(title="原标题")
        tmp_store.update_title(conv_id, "新标题")

        conv = tmp_store.get_conversation(conv_id)
        assert conv["title"] == "新标题"

    def test_delete_conversation(self, tmp_store):
        """测试删除对话"""
        conv_id = tmp_store.create_conversation(title="待删除")
        tmp_store.add_message(conv_id, "user", "消息1")
        tmp_store.add_message(conv_id, "assistant", "消息2")

        tmp_store.delete_conversation(conv_id)

        conv = tmp_store.get_conversation(conv_id)
        assert conv is None

        messages = tmp_store.get_messages(conv_id)
        assert len(messages) == 0

    def test_search_messages(self, tmp_store):
        """测试搜索消息"""
        conv_id = tmp_store.create_conversation(title="搜索测试")
        tmp_store.add_message(conv_id, "user", "贵州茅台估值怎么样？")
        tmp_store.add_message(conv_id, "assistant", "贵州茅台当前PE为25倍")
        tmp_store.add_message(conv_id, "user", "宁德时代呢？")

        results = tmp_store.search_messages("贵州茅台")
        assert len(results) == 2

        results = tmp_store.search_messages("宁德时代")
        assert len(results) == 1

    def test_message_metadata(self, tmp_store):
        """测试消息元数据"""
        conv_id = tmp_store.create_conversation(title="元数据测试")
        tmp_store.add_message(
            conv_id,
            "assistant",
            "分析结果",
            metadata={"mode": "deep", "agents": {"fundamental": {"signal": "buy"}}},
        )

        messages = tmp_store.get_messages(conv_id)
        assert len(messages) == 1
        meta = messages[0]["metadata"]
        assert meta["mode"] == "deep"
        assert "fundamental" in meta["agents"]

    def test_conversation_message_count(self, tmp_store):
        """测试消息计数自动更新"""
        conv_id = tmp_store.create_conversation(title="计数测试")
        conv = tmp_store.get_conversation(conv_id)
        assert conv["message_count"] == 0

        tmp_store.add_message(conv_id, "user", "消息1")
        conv = tmp_store.get_conversation(conv_id)
        assert conv["message_count"] == 1

        tmp_store.add_message(conv_id, "assistant", "回复1")
        conv = tmp_store.get_conversation(conv_id)
        assert conv["message_count"] == 2
