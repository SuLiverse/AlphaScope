"""主密钥轮换脚本测试 — tmp .env + tmp db 验证迁移逻辑(旧 key 解密→新 key 重加密)。"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _make_db(db_path: Path):
    """建三张密文表 + 插入一条用当前 os.environ master key 加密的密文。"""
    from backend.security.key_vault import encrypt_key

    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE model_providers (id TEXT PRIMARY KEY, name TEXT, encrypted_api_key TEXT)"
    )
    con.execute(
        "CREATE TABLE datasource_credentials (name TEXT PRIMARY KEY, encrypted_key TEXT)"
    )
    con.execute(
        "CREATE TABLE notifier_channels (channel TEXT PRIMARY KEY, config_encrypted TEXT)"
    )
    cipher = encrypt_key("sk-secret-12345")
    con.execute(
        "INSERT INTO model_providers (id, name, encrypted_api_key) VALUES (?, ?, ?)",
        ("p1", "test", cipher),
    )
    con.commit()
    con.close()
    return cipher


def _read_env_key(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("AI_FINANCE_MASTER_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


class TestRotate:
    def test_rotates_cipher_and_env(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        db = tmp_path / "test.db"
        old_key = "old-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        env.write_text(f"AI_FINANCE_MASTER_KEY={old_key}\n", encoding="utf-8")
        monkeypatch.setenv("AI_FINANCE_MASTER_KEY", old_key)
        _make_db(db)

        from scripts.rotate_master_key import rotate

        assert rotate(env, db, dry_run=False) == 0

        # .env 已更新为新随机 key(不等于旧 key)
        new_key = _read_env_key(env)
        assert new_key and new_key != old_key

        # 新 key 能解密 db 重加密后的密文
        monkeypatch.setenv("AI_FINANCE_MASTER_KEY", new_key)
        from backend.security.key_vault import decrypt_key

        con = sqlite3.connect(str(db))
        cipher = con.execute(
            "SELECT encrypted_api_key FROM model_providers WHERE id='p1'"
        ).fetchone()[0]
        con.close()
        assert decrypt_key(cipher) == "sk-secret-12345"

    def test_dry_run_no_change(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        db = tmp_path / "test.db"
        old_key = "old-key-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        env.write_text(f"AI_FINANCE_MASTER_KEY={old_key}\n", encoding="utf-8")
        monkeypatch.setenv("AI_FINANCE_MASTER_KEY", old_key)
        cipher = _make_db(db)

        from scripts.rotate_master_key import rotate

        assert rotate(env, db, dry_run=True) == 0
        assert old_key in env.read_text()  # .env 未变
        con = sqlite3.connect(str(db))
        assert (
            con.execute(
                "SELECT encrypted_api_key FROM model_providers WHERE id='p1'"
            ).fetchone()[0]
            == cipher
        )  # db 密文未变
        con.close()

    def test_no_cipher_only_env(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        db = tmp_path / "test.db"
        old_key = "old-key-cccccccccccccccccccccccccccccccccc"
        env.write_text(f"AI_FINANCE_MASTER_KEY={old_key}\n", encoding="utf-8")
        monkeypatch.setenv("AI_FINANCE_MASTER_KEY", old_key)
        con = sqlite3.connect(str(db))
        con.execute("CREATE TABLE model_providers (id TEXT, encrypted_api_key TEXT)")
        con.execute("CREATE TABLE datasource_credentials (name TEXT, encrypted_key TEXT)")
        con.execute("CREATE TABLE notifier_channels (channel TEXT, config_encrypted TEXT)")
        con.commit()
        con.close()

        from scripts.rotate_master_key import rotate

        assert rotate(env, db, dry_run=False) == 0
        assert _read_env_key(env) != old_key  # .env 仍更新

    def test_no_key_exits(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"  # 不存在
        db = tmp_path / "test.db"
        monkeypatch.delenv("AI_FINANCE_MASTER_KEY", raising=False)
        from scripts.rotate_master_key import rotate

        assert rotate(env, db, dry_run=False) == 1
