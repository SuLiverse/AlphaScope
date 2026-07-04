"""
Storage Backend Abstraction (v0.28)

统一存储接口，支持 SQLite（当前）和 PostgreSQL（未来）。
当前实现委托给现有 Database 单例。

使用方式：
    backend = get_storage_backend()
    backend.save_conversation(...)
    backend.save_message(...)
"""

import json
import time
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional


class StorageBackend(ABC):
    """存储后端抽象基类"""

    @abstractmethod
    def save_conversation(self, conv_id: str, data: Dict[str, Any]) -> None:
        """保存/更新对话"""
        ...

    @abstractmethod
    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        """获取对话"""
        ...

    @abstractmethod
    def list_conversations(self, stock_symbol: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """列出对话"""
        ...

    @abstractmethod
    def delete_conversation(self, conv_id: str) -> None:
        """删除对话"""
        ...

    @abstractmethod
    def save_message(self, conv_id: str, role: str, content: str, metadata: Optional[Dict] = None) -> int:
        """保存消息"""
        ...

    @abstractmethod
    def get_messages(self, conv_id: str) -> List[Dict[str, Any]]:
        """获取消息列表"""
        ...

    @abstractmethod
    def save_evidence(self, evidence_id: str, data: Dict[str, Any]) -> None:
        """保存证据"""
        ...

    @abstractmethod
    def search_messages(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """搜索消息"""
        ...

    @abstractmethod
    def save_audit_log(
        self,
        action: str,
        target_type: str,
        target_id: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """保存审计日志"""
        ...


class SQLiteBackend(StorageBackend):
    """SQLite 存储后端（委托给现有 ConversationStore 和 Database）"""

    def __init__(self):
        from backend.storage.db import Database
        from backend.ai_assistant.conversation_store import ConversationStore

        self._db = Database()
        self._store = ConversationStore(db=self._db)
        self._ensure_audit_table()

    def _ensure_audit_table(self):
        """确保审计日志表存在"""
        try:
            conn = self._db.conn
            conn.execute(
                """CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    metadata TEXT,
                    created_at REAL NOT NULL
                )"""
            )
            conn.commit()
        except Exception:
            pass

    def save_conversation(self, conv_id: str, data: Dict[str, Any]) -> None:
        """保存/更新对话元数据"""
        # ConversationStore 的 create_conversation 已处理创建
        # 这里处理更新场景
        try:
            if data.get("title"):
                self._store.update_title(conv_id, data["title"])
        except Exception:
            pass

    def get_conversation(self, conv_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get_conversation(conv_id)

    def list_conversations(self, stock_symbol: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        return self._store.list_conversations(stock_symbol=stock_symbol, limit=limit)

    def delete_conversation(self, conv_id: str) -> None:
        self._store.delete_conversation(conv_id)

    def save_message(self, conv_id: str, role: str, content: str, metadata: Optional[Dict] = None) -> int:
        return self._store.add_message(conv_id, role, content, metadata=metadata)

    def get_messages(self, conv_id: str) -> List[Dict[str, Any]]:
        return self._store.get_messages(conv_id)

    def save_evidence(self, evidence_id: str, data: Dict[str, Any]) -> None:
        """保存证据到 evidence_items 表"""
        try:
            from backend.evidence_store import save_evidence as _save

            _save(
                evidence_type=data.get("evidence_type", "other"),
                title=data.get("title", data.get("claim", "")),
                source=data.get("source", data.get("source_name", "")),
                claim=data.get("claim", ""),
                content_summary=data.get("content_summary", ""),
                symbols=data.get("symbols", []),
                confidence=data.get("confidence", 0.7),
                source_url=data.get("source_url", ""),
                data_date=data.get("data_date", ""),
            )
        except Exception:
            pass

    def search_messages(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        return self._store.search_messages(query)

    def save_audit_log(
        self,
        action: str,
        target_type: str,
        target_id: str,
        metadata: Optional[Dict] = None,
    ) -> None:
        """保存审计日志"""
        try:
            conn = self._db.conn
            conn.execute(
                """INSERT INTO audit_logs (action, target_type, target_id, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    action,
                    target_type,
                    target_id,
                    json.dumps(metadata or {}),
                    time.time(),
                ),
            )
            conn.commit()
        except Exception:
            pass


# ============== 工厂函数 ==============

_backend_instance: Optional[StorageBackend] = None


def get_storage_backend(backend_type: str = "sqlite") -> StorageBackend:
    """获取存储后端实例（单例）"""
    global _backend_instance
    if _backend_instance is not None:
        return _backend_instance

    if backend_type == "sqlite":
        _backend_instance = SQLiteBackend()
    else:
        raise ValueError(f"不支持的存储后端: {backend_type}")

    return _backend_instance
