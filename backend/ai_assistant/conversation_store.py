"""AI 对话持久化层

SQLite-backed conversation storage.
复用现有 Database 单例，纯数据访问层，无 LLM 调用。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


def _ensure_ai_tables(conn) -> None:
    """创建 AI 对话相关表（幂等）"""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            stock_symbol TEXT DEFAULT '',
            stock_name TEXT DEFAULT '',
            mode TEXT DEFAULT 'free',
            provider TEXT DEFAULT 'deepseek',
            model TEXT DEFAULT 'deepseek-chat',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            metadata TEXT DEFAULT '{}'
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            metadata TEXT DEFAULT '{}',
            FOREIGN KEY (conversation_id) REFERENCES ai_conversations(id)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_messages_conv ON ai_messages(conversation_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_conversations_symbol ON ai_conversations(stock_symbol)")
    conn.commit()


class ConversationStore:
    """SQLite-backed conversation persistence.

    Uses the existing Database singleton when available,
    falls back to direct connection for standalone usage.
    """

    def __init__(self, db=None):
        if db is not None:
            self._conn = db.conn
            self._db_lock = db._db_lock
            self._own_conn = False
        else:
            from backend.storage.db import DB_PATH

            import sqlite3

            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._db_lock = __import__("threading").Lock()
            self._own_conn = True
        with self._db_lock:
            _ensure_ai_tables(self._conn)

    def create_conversation(
        self,
        title: str = "",
        stock_symbol: str = "",
        stock_name: str = "",
        mode: str = "free",
        provider: str = "deepseek",
        model: str = "deepseek-chat",
        metadata: Optional[dict] = None,
    ) -> str:
        """创建新对话，返回 UUID"""
        conv_id = uuid.uuid4().hex[:16]
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._db_lock:
            self._conn.execute(
                """INSERT INTO ai_conversations
                (id, title, stock_symbol, stock_name, mode, provider, model,
                 created_at, updated_at, message_count, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
                (
                    conv_id,
                    title,
                    stock_symbol,
                    stock_name,
                    mode,
                    provider,
                    model,
                    now,
                    now,
                    meta_json,
                ),
            )
            self._conn.commit()
        return conv_id

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        metadata: Optional[dict] = None,
    ) -> int:
        """追加消息，返回消息 ID"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._db_lock:
            cur = self._conn.execute(
                """INSERT INTO ai_messages
                (conversation_id, role, content, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?)""",
                (conversation_id, role, content, now, meta_json),
            )
            self._conn.execute(
                """UPDATE ai_conversations
                SET updated_at = ?, message_count = message_count + 1
                WHERE id = ?""",
                (now, conversation_id),
            )
            self._conn.commit()
            return cur.lastrowid

    def update_model(self, conversation_id: str, provider: str = "", model: str = "") -> None:
        """更新对话使用的 Provider / Model。"""
        fields = []
        values = []
        if provider:
            fields.append("provider = ?")
            values.append(provider)
        if model:
            fields.append("model = ?")
            values.append(model)
        if not fields:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        fields.append("updated_at = ?")
        values.append(now)
        values.append(conversation_id)
        with self._db_lock:
            self._conn.execute(
                f"UPDATE ai_conversations SET {', '.join(fields)} WHERE id = ?",
                values,
            )
            self._conn.commit()

    def get_conversation(self, conversation_id: str) -> Optional[dict]:
        """加载对话头信息"""
        with self._db_lock:
            row = self._conn.execute("SELECT * FROM ai_conversations WHERE id = ?", (conversation_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    def get_messages(self, conversation_id: str, limit: int = 200) -> List[dict]:
        """加载对话消息，按时间排序"""
        with self._db_lock:
            rows = self._conn.execute(
                """SELECT * FROM ai_messages
                WHERE conversation_id = ?
                ORDER BY id ASC LIMIT ?""",
                (conversation_id, limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_conversations(self, stock_symbol: Optional[str] = None, limit: int = 50) -> List[dict]:
        """列出最近对话"""
        with self._db_lock:
            if stock_symbol:
                rows = self._conn.execute(
                    """SELECT * FROM ai_conversations
                    WHERE stock_symbol = ?
                    ORDER BY updated_at DESC LIMIT ?""",
                    (stock_symbol, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM ai_conversations ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def update_title(self, conversation_id: str, title: str) -> None:
        """更新对话标题"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._db_lock:
            self._conn.execute(
                "UPDATE ai_conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, now, conversation_id),
            )
            self._conn.commit()

    def delete_conversation(self, conversation_id: str) -> None:
        """删除对话及其所有消息"""
        with self._db_lock:
            self._conn.execute(
                "DELETE FROM ai_messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            self._conn.execute(
                "DELETE FROM ai_conversations WHERE id = ?",
                (conversation_id,),
            )
            self._conn.commit()

    def search_messages(self, query: str, limit: int = 20) -> List[dict]:
        """全文搜索消息内容"""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._db_lock:
            rows = self._conn.execute(
                """SELECT m.*, c.title as conversation_title
                FROM ai_messages m
                JOIN ai_conversations c ON m.conversation_id = c.id
                WHERE m.content LIKE ? ESCAPE '\\'
                ORDER BY m.timestamp DESC LIMIT ?""",
                (f"%{escaped}%", limit),
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_message_count(self, conversation_id: str) -> int:
        """获取对话消息数"""
        with self._db_lock:
            row = self._conn.execute(
                "SELECT COUNT(*) as cnt FROM ai_messages WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return row["cnt"] if row else 0

    @staticmethod
    def _row_to_dict(row) -> dict:
        """sqlite3.Row -> dict, 自动解析 JSON 字段"""
        d = dict(row)
        for key in ("metadata",):
            if key in d and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
