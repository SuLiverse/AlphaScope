"""Agent 存储层 — 管理 agent_configs 和 agent_teams 表"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.storage.db import Database

_AGENT_TABLE = """
CREATE TABLE IF NOT EXISTS agent_configs (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    provider TEXT DEFAULT 'deepseek',
    model TEXT DEFAULT 'deepseek-chat',
    tools TEXT DEFAULT '[]',
    temperature REAL DEFAULT 0.3,
    max_tokens INTEGER DEFAULT 2048,
    output_schema TEXT DEFAULT '{}',
    card_style TEXT DEFAULT 'default',
    enabled INTEGER DEFAULT 1,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""

_TEAM_TABLE = """
CREATE TABLE IF NOT EXISTS agent_teams (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    workflow_config TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""

_MEMBER_TABLE = """
CREATE TABLE IF NOT EXISTS agent_team_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id TEXT REFERENCES agent_teams(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL,
    role TEXT DEFAULT 'member',
    sort_order INTEGER DEFAULT 0,
    config_json TEXT DEFAULT '{}'
)
"""


def _ensure_tables() -> None:
    """Create tables if not exist (idempotent, safe to call on every use)."""
    db = Database()
    with db.transaction() as conn:
        conn.execute(_AGENT_TABLE)
        conn.execute(_TEAM_TABLE)
        conn.execute(_MEMBER_TABLE)
        conn.commit()


def _get_conn():
    """Ensure tables exist and return the database connection (public API)."""
    _ensure_tables()
    return Database().conn


# Ensure tables exist on import
_ensure_tables()


# ============== Agent CRUD ==============


def list_agents() -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM agent_configs ORDER BY name").fetchall()
    return [_row_to_agent(r) for r in rows]


def get_agent(agent_id: str) -> Optional[dict[str, Any]]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM agent_configs WHERE id=?", (agent_id,)).fetchone()
    return _row_to_agent(row) if row else None


def save_agent(
    agent_id: str,
    name: str,
    description: str = "",
    system_prompt: str = "",
    provider: str = "deepseek",
    model: str = "deepseek-chat",
    tools: list[str] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    enabled: bool = True,
) -> dict[str, Any]:
    conn = _get_conn()
    now = time.time()
    tools_json = json.dumps(tools or [], ensure_ascii=False)

    existing = conn.execute(
        "SELECT id FROM agent_configs WHERE id=?", (agent_id,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE agent_configs SET name=?, description=?, system_prompt=?, provider=?, model=?, "
            "tools=?, temperature=?, max_tokens=?, enabled=?, updated_at=? WHERE id=?",
            (
                name,
                description,
                system_prompt,
                provider,
                model,
                tools_json,
                temperature,
                max_tokens,
                int(enabled),
                now,
                agent_id,
            ),
        )
    else:
        conn.execute(
            "INSERT INTO agent_configs (id, name, description, system_prompt, provider, model, tools, "
            "temperature, max_tokens, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                agent_id,
                name,
                description,
                system_prompt,
                provider,
                model,
                tools_json,
                temperature,
                max_tokens,
                int(enabled),
                now,
                now,
            ),
        )
    conn.commit()
    return get_agent(agent_id)


def delete_agent(agent_id: str) -> bool:
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM agent_configs WHERE id=?", (agent_id,)
    ).fetchone()
    if not existing:
        return False
    conn.execute("DELETE FROM agent_configs WHERE id=?", (agent_id,))
    conn.execute("DELETE FROM agent_team_members WHERE agent_id=?", (agent_id,))
    conn.commit()
    return True


def _row_to_agent(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "system_prompt": row["system_prompt"] or "",
        "provider": row["provider"] or "deepseek",
        "model": row["model"] or "deepseek-chat",
        "tools": json.loads(row["tools"] or "[]"),
        "temperature": row["temperature"] or 0.3,
        "max_tokens": row["max_tokens"] or 2048,
        "enabled": bool(row["enabled"]),
    }


# ============== Team CRUD ==============


def list_teams() -> list[dict[str, Any]]:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM agent_teams ORDER BY name").fetchall()
    return [_row_to_team(r) for r in rows]


def get_team(team_id: str) -> Optional[dict[str, Any]]:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM agent_teams WHERE id=?", (team_id,)).fetchone()
    if not row:
        return None
    team = _row_to_team(row)
    # Load members
    members = conn.execute(
        "SELECT agent_id, role, sort_order FROM agent_team_members WHERE team_id=? ORDER BY sort_order",
        (team_id,),
    ).fetchall()
    team["members"] = [
        {"agent_id": m["agent_id"], "role": m["role"], "sort_order": m["sort_order"]}
        for m in members
    ]
    return team


def save_team(
    team_id: str,
    name: str,
    description: str = "",
    member_ids: list[str] | None = None,
) -> dict[str, Any]:
    conn = _get_conn()
    now = time.time()

    existing = conn.execute(
        "SELECT id FROM agent_teams WHERE id=?", (team_id,)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE agent_teams SET name=?, description=?, updated_at=? WHERE id=?",
            (name, description, now, team_id),
        )
    else:
        conn.execute(
            "INSERT INTO agent_teams (id, name, description, created_at, updated_at) VALUES (?,?,?,?,?)",
            (team_id, name, description, now, now),
        )

    # Update members
    if member_ids is not None:
        conn.execute("DELETE FROM agent_team_members WHERE team_id=?", (team_id,))
        for i, agent_id in enumerate(member_ids):
            conn.execute(
                "INSERT INTO agent_team_members (team_id, agent_id, role, sort_order) VALUES (?,?,?,?)",
                (team_id, agent_id, "member", i),
            )
    conn.commit()
    return get_team(team_id)


def delete_team(team_id: str) -> bool:
    conn = _get_conn()
    existing = conn.execute(
        "SELECT id FROM agent_teams WHERE id=?", (team_id,)
    ).fetchone()
    if not existing:
        return False
    conn.execute("DELETE FROM agent_teams WHERE id=?", (team_id,))
    conn.execute("DELETE FROM agent_team_members WHERE team_id=?", (team_id,))
    conn.commit()
    return True


def _row_to_team(row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"] or "",
        "workflow_config": row["workflow_config"] or "{}",
    }
