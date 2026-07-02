"""通知渠道配置存储层 — 持久化用户配置的推送渠道凭证(SQLite)。

凭证加密复用 key_vault(AES-GCM);表里只存加密密文。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from backend.storage.db import Database

logger = logging.getLogger(__name__)

_TABLE = """
CREATE TABLE IF NOT EXISTS notifier_channels (
    channel TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 0,
    config_encrypted TEXT DEFAULT '',
    updated_at REAL NOT NULL
)
"""


_schema_ensured = False


def _ensure_schema() -> None:
    """建表(幂等)。包进进程级 DB 锁。首次建表后置 flag, 后续调用跳过。"""
    global _schema_ensured
    if _schema_ensured:
        return
    db = Database()
    with db.transaction() as conn:
        conn.execute(_TABLE)
        conn.commit()
    _schema_ensured = True


def _encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    try:
        from backend.security.key_vault import encrypt_key

        return encrypt_key(plaintext) or ""
    except Exception as e:  # noqa: BLE001
        logger.debug("notifier 凭证加密失败, 明文不落库: %s", e)
        return ""


def _decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        from backend.security.key_vault import decrypt_key

        return decrypt_key(ciphertext) or ""
    except Exception:  # noqa: BLE001
        return ""


def list_channels() -> list[dict[str, Any]]:
    """列出渠道配置(凭证字段不回传明文,仅返回是否已配置)。"""
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        rows = conn.execute(
            "SELECT channel, enabled, config_encrypted, updated_at FROM notifier_channels"
        ).fetchall()
    # 解密在锁外做(I/O 不应占着进程级 DB 锁)
    out = []
    for r in rows:
        cfg = {}
        try:
            cfg = json.loads(_decrypt(r["config_encrypted"]) or "{}")
        except Exception:  # noqa: BLE001
            cfg = {}
        out.append(
            {
                "channel": r["channel"],
                "enabled": bool(r["enabled"]),
                "has_credentials": bool(r["config_encrypted"]),
                # 仅回传非敏感字段名,不回传 token/webhook/password 明文
                "fields_configured": {k: bool(v) for k, v in cfg.items()},
                "updated_at": r["updated_at"],
            }
        )
    return out


def get_channel_config(channel: str) -> dict[str, Any]:
    """读取某渠道的完整凭证(仅后端内部用,API 不直接暴露)。"""
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT config_encrypted, enabled FROM notifier_channels WHERE channel=?",
            (channel,),
        ).fetchone()
    if not row:
        return {}
    try:
        cfg = json.loads(_decrypt(row["config_encrypted"]) or "{}")
    except Exception:  # noqa: BLE001
        cfg = {}
    cfg["_enabled"] = bool(row["enabled"])
    return cfg


def save_channel(channel: str, enabled: bool, config: dict) -> None:
    # 加密在锁外做
    enc = _encrypt(json.dumps(config or {}, ensure_ascii=False))
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO notifier_channels (channel, enabled, config_encrypted, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(channel) DO UPDATE SET "
            "enabled=excluded.enabled, config_encrypted=excluded.config_encrypted, "
            "updated_at=excluded.updated_at",
            (channel, int(bool(enabled)), enc, time.time()),
        )
        conn.commit()


def delete_channel(channel: str) -> bool:
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        cur = conn.execute(
            "DELETE FROM notifier_channels WHERE channel=?", (channel,)
        )
        conn.commit()
        return cur.rowcount > 0
