"""基金组合管理 — 持久化到 SQLite"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PortfolioManager:
    """基金组合管理器 — 持久化到 SQLite"""

    def __init__(self, db=None):
        self._db = db
        self._ensure_table()

    def _ensure_table(self):
        """确保组合表存在"""
        if self._db is None:
            return
        try:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS fund_portfolios (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        description TEXT DEFAULT '',
                        holdings TEXT DEFAULT '[]',
                        created_at TEXT,
                        updated_at TEXT
                    )
                    """
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"创建组合表失败: {e}")

    def create(
        self,
        name: str,
        description: str = "",
        holdings: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """创建组合"""
        portfolio_id = str(uuid.uuid4())[:8]
        now = datetime.now().isoformat()
        holdings_json = json.dumps(holdings or [], ensure_ascii=False)

        if self._db:
            try:
                with self._db.transaction() as conn:
                    conn.execute(
                        "INSERT INTO fund_portfolios VALUES (?, ?, ?, ?, ?, ?)",
                        (portfolio_id, name, description, holdings_json, now, now),
                    )
                    conn.commit()
            except Exception as e:
                logger.error(f"保存组合失败: {e}")

        return {
            "id": portfolio_id,
            "name": name,
            "description": description,
            "holdings": holdings or [],
            "created_at": now,
            "updated_at": now,
        }

    def list_all(self) -> list[dict[str, Any]]:
        """列出所有组合"""
        if not self._db:
            return []
        try:
            with self._db.transaction() as conn:
                rows = conn.execute(
                    "SELECT id, name, description, holdings, created_at, updated_at "
                    "FROM fund_portfolios ORDER BY updated_at DESC"
                ).fetchall()
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "description": r[2],
                    "holdings": json.loads(r[3]) if r[3] else [],
                    "created_at": r[4],
                    "updated_at": r[5],
                }
                for r in rows
            ]
        except Exception as e:
            logger.error(f"查询组合失败: {e}")
            return []

    def get(self, portfolio_id: str) -> Optional[dict[str, Any]]:
        """获取单个组合"""
        if not self._db:
            return None
        try:
            with self._db.transaction() as conn:
                row = conn.execute(
                    "SELECT id, name, description, holdings, created_at, updated_at "
                    "FROM fund_portfolios WHERE id = ?",
                    (portfolio_id,),
                ).fetchone()
            if not row:
                return None
            return {
                "id": row[0],
                "name": row[1],
                "description": row[2],
                "holdings": json.loads(row[3]) if row[3] else [],
                "created_at": row[4],
                "updated_at": row[5],
            }
        except Exception as e:
            logger.error(f"查询组合失败: {e}")
            return None

    def update(
        self,
        portfolio_id: str,
        name: str | None = None,
        description: str | None = None,
        holdings: list[dict[str, Any]] | None = None,
    ) -> Optional[dict[str, Any]]:
        """更新组合"""
        # _db_lock 不可重入: get 自己加锁, 不能在 update 的事务内调用。
        # 先在锁外 get 读现有值, 再单独开事务 UPDATE。
        existing = self.get(portfolio_id)
        if not existing:
            return None

        now = datetime.now().isoformat()
        new_name = name if name is not None else existing["name"]
        new_desc = description if description is not None else existing["description"]
        new_holdings = holdings if holdings is not None else existing["holdings"]
        holdings_json = json.dumps(new_holdings, ensure_ascii=False)

        if self._db:
            try:
                with self._db.transaction() as conn:
                    conn.execute(
                        "UPDATE fund_portfolios SET name=?, description=?, holdings=?, "
                        "updated_at=? WHERE id=?",
                        (new_name, new_desc, holdings_json, now, portfolio_id),
                    )
                    conn.commit()
            except Exception as e:
                logger.error(f"更新组合失败: {e}")

        return {
            "id": portfolio_id,
            "name": new_name,
            "description": new_desc,
            "holdings": new_holdings,
            "created_at": existing["created_at"],
            "updated_at": now,
        }

    def delete(self, portfolio_id: str) -> bool:
        """删除组合"""
        if not self._db:
            return False
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    "DELETE FROM fund_portfolios WHERE id = ?", (portfolio_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"删除组合失败: {e}")
            return False
