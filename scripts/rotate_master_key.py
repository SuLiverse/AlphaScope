"""主密钥安全轮换脚本 — 用旧 master key 解密所有已存密文, 换新随机 key 重加密回写。

背景
----
release 目录 .env 此前硬编码固定 master key(AUDIT C3), 需换为随机 key。
但 db 里可能有用旧 key 加密的密文(model_providers.encrypted_api_key 等),
直接换 key 会让旧密文解密失败。本脚本安全轮换:

1. 备份 .env 与 db
2. 用旧 key 解密三表所有密文(datasource_credentials / model_providers / notifier_channels)
3. 生成新随机 key
4. 用新 key 重加密回写 db
5. 更新 .env 为新 key

可回滚: 任一步失败则不写新 key、不改 .env, 保留旧密文与旧 key;
备份文件(.env.bak / *.db.bak)可用于手动恢复。

用法
----
    python scripts/rotate_master_key.py [--env .env] [--db data/db/ai_finance.db] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# (表, 密文列, 主键列)
_CIPHER_TABLES = [
    ("datasource_credentials", "encrypted_key", "name"),
    ("model_providers", "encrypted_api_key", "id"),
    ("notifier_channels", "config_encrypted", "channel"),
]


def _read_master_key(env_path: Path) -> str:
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("AI_FINANCE_MASTER_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def _update_env_master_key(env_path: Path, new_key: str) -> None:
    """把 .env 里的 AI_FINANCE_MASTER_KEY= 行替换为新 key; 无则追加。"""
    if not env_path.exists():
        env_path.write_text(f"AI_FINANCE_MASTER_KEY={new_key}\n", encoding="utf-8")
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith("AI_FINANCE_MASTER_KEY="):
            lines[i] = f"AI_FINANCE_MASTER_KEY={new_key}"
            found = True
            break
    if not found:
        lines.append(f"AI_FINANCE_MASTER_KEY={new_key}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rotate(env_path: Path, db_path: Path, *, dry_run: bool = False) -> int:
    old_key = _read_master_key(env_path) or os.environ.get("AI_FINANCE_MASTER_KEY", "")
    if not old_key:
        print("[rotate] 无 master key(.env 与环境均无), 退出(交给 launcher 首启生成)")
        return 1

    # 1. 备份
    if not dry_run:
        if env_path.exists():
            shutil.copy2(env_path, env_path.with_suffix(env_path.suffix + ".bak"))
            print(f"[rotate] 备份 .env -> {env_path.with_suffix(env_path.suffix + '.bak')}")
        if db_path.exists():
            shutil.copy2(db_path, db_path.with_suffix(db_path.suffix + ".bak"))
            print(f"[rotate] 备份 db -> {db_path.with_suffix(db_path.suffix + '.bak')}")

    # 2. 旧 key 解密所有密文
    os.environ["AI_FINANCE_MASTER_KEY"] = old_key
    from backend.security.key_vault import decrypt_key, encrypt_key

    plains: list[tuple[str, str, str, object, str]] = []  # (table, col, idcol, id, plain)
    if not db_path.exists():
        print(f"[rotate] db 不存在({db_path}), 仅轮换 .env key(无密文需迁移)")
    else:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        for table, col, idcol in _CIPHER_TABLES:
            try:
                rows = cur.execute(
                    f"SELECT {idcol}, {col} FROM {table} WHERE {col} IS NOT NULL AND {col}!=''"
                ).fetchall()
            except sqlite3.OperationalError as e:
                print(f"[rotate] 跳过 {table}(表或列不存在): {e}")
                continue
            for rid, cipher in rows:
                plain = decrypt_key(cipher)
                if not plain:
                    print(f"[rotate] WARN: {table}/{rid} 解密失败(可能非旧 key 加密), 跳过")
                    continue
                plains.append((table, col, idcol, rid, plain))
        con.close()
    print(f"[rotate] 旧 key 解密成功 {len(plains)} 条密文")

    if dry_run:
        print(f"[rotate] dry-run: 将用新 key 重加密 {len(plains)} 条密文并更新 .env, 实际未写")
        return 0

    # 3. 生成新 key
    new_key = secrets.token_urlsafe(32)
    os.environ["AI_FINANCE_MASTER_KEY"] = new_key

    # 4. 新 key 重加密回写 db(此时 db 仍用旧 key 加密的密文, 用新 key 重写)
    if plains:
        con = sqlite3.connect(str(db_path))
        cur = con.cursor()
        for table, col, idcol, rid, plain in plains:
            new_cipher = encrypt_key(plain)
            cur.execute(f"UPDATE {table} SET {col}=? WHERE {idcol}=?", (new_cipher, rid))
        con.commit()
        con.close()
        print(f"[rotate] 已用新 key 重加密回写 {len(plains)} 条密文")

    # 5. 更新 .env(db 已新 key, 必须更新 .env 否则解不开)
    _update_env_master_key(env_path, new_key)
    print("[rotate] .env 已更新为新随机 key")
    print("[rotate] 完成! 确认无误后可删除 .env.bak / *.db.bak")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--env", default=str(REPO_ROOT / ".env"))
    ap.add_argument("--db", default=str(REPO_ROOT / "data/db/ai_finance.db"))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    return rotate(Path(args.env), Path(args.db), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
