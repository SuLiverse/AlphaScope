"""设置存储层 — 管理 model_providers 与应用偏好设置。"""

from __future__ import annotations

import os
import copy
import json
import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

from backend.security.key_vault import decrypt_key, encrypt_key, mask_key
from backend.storage.db import Database
from backend.models.provider_gateway import validate_custom_base_url

_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS model_providers (
    id TEXT PRIMARY KEY,
    workspace_id TEXT DEFAULT 'default',
    name TEXT NOT NULL,
    type TEXT DEFAULT 'openai_compatible',
    base_url TEXT,
    encrypted_api_key TEXT,
    enabled INTEGER DEFAULT 1,
    config_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""

_PREFERENCES_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS app_preferences (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at REAL NOT NULL
)
"""

DEFAULT_APP_PREFERENCES: dict[str, dict[str, Any]] = {
    "general": {
        "language": "zh-CN",
        "theme": "dark",
        "default_symbol": "600519",
        "auto_refresh": True,
        "refresh_interval": 60,
    },
    "network": {
        "api_base_url": "http://127.0.0.1:8000",
        "request_timeout_ms": 12000,
        "retry_count": 1,
        "proxy_url": "",
    },
    "security": {
        "mask_api_keys": True,
        "confirm_deletes": True,
        "allow_external_links": True,
        "audit_log": True,
    },
    "data": {
        "news_limit": 30,
        "price_cache_days": 180,
        "prefer_local_cache": True,
        "auto_fetch_missing": True,
    },
    "knowledge": {
        "enabled": True,
        "shared_knowledge": True,
        "agent_memory": True,
        "auto_write_agent_memory": True,
        "embedding_provider_id": "",
        "embedding_model": "",
        "memory_retention_days": 90,
    },
    "ai_models": {
        "use_unified_model": True,
        "unified": {},
        "routes": {},
    },
}

_INT_LIMITS: dict[tuple[str, str], tuple[int, int]] = {
    ("general", "refresh_interval"): (10, 3600),
    ("network", "request_timeout_ms"): (3000, 120000),
    ("network", "retry_count"): (0, 5),
    ("data", "news_limit"): (5, 100),
    ("data", "price_cache_days"): (30, 3650),
    ("knowledge", "memory_retention_days"): (1, 3650),
}

_MODEL_PREFERENCE_HINTS = (
    "deepseek",
    "sensenova",
    "flash",
    "chat",
    "instruct",
    "reason",
    "pro",
    "gpt",
    "moonshot",
)

_EMBEDDING_MODEL_HINTS = (
    "embedding",
    "embed",
    "bge-",
    "bge_",
    "gte-",
    "gte_",
    "jina-embeddings",
    "text-embedding",
    "text_embedding",
)

_VISION_MODEL_HINTS = (
    "vision",
    "visual",
    "multimodal",
    "multi-modal",
    "mimo",
    "omni",
    "vl",
    "llava",
    "qwen-vl",
    "gpt-4o",
    "gpt-4.1",
    "claude-3",
    "claude-sonnet",
    "claude-opus",
    "gemini",
)

_NON_CHAT_MODEL_HINTS = (
    *_EMBEDDING_MODEL_HINTS,
    "tts",
    "voice",
    "audio",
    "speech",
)


_MOJIBAKE_MARKERS = ("\ufffd", "\u951f", "\u8119", "\u8117")


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def _has_latin1_run(value: str) -> bool:
    run = 0
    for ch in value:
        if "\u00c0" <= ch <= "\u00ff":
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


def _looks_mojibake(value: str) -> bool:
    if not value:
        return False
    if any(marker in value for marker in _MOJIBAKE_MARKERS):
        return True
    if any("\u0080" <= ch <= "\u009f" for ch in value):
        return True
    return _has_latin1_run(value)


def _repair_mojibake_name(value: str) -> str:
    try:
        raw = value.encode("latin1")
    except UnicodeEncodeError:
        return ""
    for encoding in ("utf-8", "gbk"):
        try:
            decoded = raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
        if decoded and _contains_cjk(decoded):
            return decoded
    return ""


def _infer_provider_name(provider_id: str, base_url: str) -> str:
    haystack = f"{provider_id} {base_url}".lower()
    for token, label in (
        ("deepseek", "DeepSeek"),
        ("sensenova", "SenseNova"),
        ("sensecore", "SenseNova"),
        ("sense", "SenseNova"),
        ("moonshot", "Kimi"),
        ("kimi", "Kimi"),
        ("openai", "OpenAI"),
        ("gpt", "OpenAI"),
        ("anthropic", "Claude"),
        ("claude", "Claude"),
        ("mimo", "Mimo"),
    ):
        if token in haystack:
            return label
    return provider_id.strip()


def _clean_provider_name(provider_id: str, name: str, base_url: str) -> str:
    raw_name = str(name or "").strip()
    if raw_name and not _looks_mojibake(raw_name):
        return raw_name
    repaired = _repair_mojibake_name(raw_name) if raw_name else ""
    if repaired:
        return repaired
    inferred = _infer_provider_name(str(provider_id or ""), str(base_url or ""))
    return inferred or raw_name or "Unnamed Provider"


def _preferred_model_id(model_ids: list[str]) -> str:
    """Pick a likely chat model from a provider model listing."""
    text_models = [model_id for model_id in model_ids if _is_text_chat_model(model_id)]
    if text_models:
        return max(text_models, key=_chat_model_score)
    return model_ids[0] if model_ids else ""


def _is_text_chat_model(model_id: str) -> bool:
    model = model_id.lower()
    return not any(token in model for token in _NON_CHAT_MODEL_HINTS)


def _chat_model_score(model_id: str) -> int:
    model = model_id.lower()
    if not _is_text_chat_model(model_id):
        return -1000
    score = 0
    if "pro" in model:
        score += 45
    if "chat" in model:
        score += 35
    if "instruct" in model:
        score += 30
    if "reason" in model:
        score += 25
    if "flash" in model:
        score += 20
    if "2.5" in model or "v2.5" in model:
        score += 18
    if "omni" in model:
        score -= 15
    return score


def _ranked_text_model_ids(model_ids: list[str]) -> list[str]:
    return sorted(
        [model_id for model_id in model_ids if _is_text_chat_model(model_id)],
        key=_chat_model_score,
        reverse=True,
    )


def _model_capabilities(model_id: str) -> dict[str, bool]:
    model = model_id.lower()
    embedding = any(token in model for token in _EMBEDDING_MODEL_HINTS)
    vision = any(token in model for token in _VISION_MODEL_HINTS)
    return {"vision": bool(vision and not embedding), "embedding": bool(embedding)}


def _model_config_item(model_id: str, owned_by: str = "") -> dict[str, Any]:
    return {
        "id": model_id,
        "owned_by": owned_by,
        "capabilities": _model_capabilities(model_id),
    }


def _ensure_schema() -> None:
    """建表(幂等)。包进进程级 DB 锁, 避免与请求线程并发写时撞锁。"""
    with Database().transaction() as conn:
        conn.execute(_TABLE_SQL)
        conn.execute(_PREFERENCES_TABLE_SQL)
        conn.commit()


def _default_preferences() -> dict[str, dict[str, Any]]:
    return copy.deepcopy(DEFAULT_APP_PREFERENCES)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _coerce_int(section: str, key: str, value: Any, default: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        coerced = default
    low, high = _INT_LIMITS.get((section, key), (0, 10_000_000))
    return max(low, min(high, coerced))


def _safe_encrypt_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    try:
        return encrypt_key(api_key)
    except RuntimeError as exc:
        if "AI_FINANCE_MASTER_KEY" in str(exc):
            raise RuntimeError(
                "无法保存 API Key：AI_FINANCE_MASTER_KEY 未配置；请设置主密钥后重试，或留空 API Key 仅保存 Base URL。"
            ) from exc
        raise


def _coerce_preference_value(section: str, key: str, value: Any) -> Any:
    default = DEFAULT_APP_PREFERENCES[section][key]
    if isinstance(default, bool):
        return _coerce_bool(value)
    if isinstance(default, int):
        return _coerce_int(section, key, value, default)
    if isinstance(default, dict):
        return (
            copy.deepcopy(value) if isinstance(value, dict) else copy.deepcopy(default)
        )
    text = str(value if value is not None else default).strip()
    if section == "general" and key == "language":
        return text if text in {"zh-CN", "en-US"} else default
    if section == "general" and key == "theme":
        return text if text in {"dark", "light", "system"} else default
    return text


def _normalize_preferences(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    normalized = _default_preferences()
    for section, values in (raw or {}).items():
        if section not in normalized or not isinstance(values, dict):
            continue
        for key, value in values.items():
            if key in normalized[section]:
                normalized[section][key] = _coerce_preference_value(section, key, value)
    return normalized


def get_app_preferences() -> dict[str, dict[str, Any]]:
    """读取应用偏好设置，并补齐新增默认项。"""
    _ensure_schema()
    with Database().transaction() as conn:
        rows = conn.execute("SELECT key, value_json FROM app_preferences").fetchall()
    # JSON 解析/合并是纯 Python, 在锁外做
    raw = _default_preferences()
    for row in rows:
        section = row["key"]
        if section not in raw:
            continue
        try:
            values = json.loads(row["value_json"] or "{}")
        except json.JSONDecodeError:
            logger.warning("应用偏好设置 %s JSON 解析失败，使用默认值", section)
            continue
        if isinstance(values, dict):
            raw[section].update(values)
    return _normalize_preferences(raw)


def save_app_preferences(
    preferences: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """合并保存应用偏好设置，只接受已声明的 section/key。"""
    # get_app_preferences 自带 transaction; 必须在写事务外调用(_db_lock 不可重入)。
    current = get_app_preferences()
    for section, values in (preferences or {}).items():
        if section in current and isinstance(values, dict):
            current[section].update(values)
    normalized = _normalize_preferences(current)
    now = time.time()
    _ensure_schema()
    with Database().transaction() as conn:
        for section, values in normalized.items():
            conn.execute(
                "INSERT OR REPLACE INTO app_preferences (key, value_json, updated_at) VALUES (?, ?, ?)",
                (section, json.dumps(values, ensure_ascii=False), now),
            )
        conn.commit()
    return normalized


def list_providers() -> list[dict[str, Any]]:
    """列出所有 DB 中的 provider"""
    _ensure_schema()
    with Database().transaction() as conn:
        rows = conn.execute(
            "SELECT id, name, type, base_url, encrypted_api_key, enabled, config_json, created_at, updated_at "
            "FROM model_providers ORDER BY name"
        ).fetchall()
    # 解密在锁外做
    result = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "name": _clean_provider_name(
                    row["id"], row["name"], row["base_url"] or ""
                ),
                "type": row["type"],
                "base_url": row["base_url"] or "",
                "api_key_masked": mask_key(decrypt_key(row["encrypted_api_key"] or "")),
                "enabled": bool(row["enabled"]),
                "config_json": row["config_json"] or "{}",
            }
        )
    return result


def get_provider(provider_id: str) -> Optional[dict[str, Any]]:
    """获取单个 provider（含解密的 api_key）"""
    _ensure_schema()
    with Database().transaction() as conn:
        row = conn.execute(
            "SELECT id, name, type, base_url, encrypted_api_key, enabled, config_json FROM model_providers WHERE id = ?",
            (provider_id,),
        ).fetchone()
    if not row:
        return None
    # 解密在锁外做
    plain = decrypt_key(row["encrypted_api_key"] or "")
    return {
        "id": row["id"],
        "name": _clean_provider_name(row["id"], row["name"], row["base_url"] or ""),
        "type": row["type"],
        "base_url": row["base_url"] or "",
        "api_key": plain,
        "api_key_masked": mask_key(plain),
        "enabled": bool(row["enabled"]),
        "config_json": row["config_json"] or "{}",
    }


def save_provider(
    provider_id: str,
    name: str,
    base_url: str,
    api_key: str = "",
    enabled: bool = True,
    config_json: Optional[str] = None,
) -> dict[str, Any]:
    """添加或更新 provider"""
    now = time.time()
    from backend.models.provider_gateway import normalize_openai_base_url

    # 参数规整 / 加密在锁外做(_safe_encrypt_api_key 可能抛 RuntimeError 提示用户)
    normalized_base_url = normalize_openai_base_url(base_url)
    if normalized_base_url:
        normalized_base_url = validate_custom_base_url(normalized_base_url)
    display_name = _clean_provider_name(provider_id, name, normalized_base_url)
    encrypted_key = _safe_encrypt_api_key(api_key) if api_key else None

    _ensure_schema()
    db = Database()
    # existing 查询 + INSERT/UPDATE 在同一事务(原子性); _sync_to_gateway / get_provider
    # 会再加锁, 必须在事务外调用(_db_lock 不可重入)。
    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id, config_json FROM model_providers WHERE id = ?", (provider_id,)
        ).fetchone()
        next_config_json = config_json
        if next_config_json is None:
            next_config_json = (existing["config_json"] if existing else None) or "{}"
        if existing:
            if encrypted_key is not None:
                conn.execute(
                    "UPDATE model_providers SET name=?, base_url=?, encrypted_api_key=?, enabled=?, config_json=?, updated_at=? WHERE id=?",
                    (
                        display_name,
                        normalized_base_url,
                        encrypted_key,
                        int(enabled),
                        next_config_json,
                        now,
                        provider_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE model_providers SET name=?, base_url=?, enabled=?, config_json=?, updated_at=? WHERE id=?",
                    (
                        display_name,
                        normalized_base_url,
                        int(enabled),
                        next_config_json,
                        now,
                        provider_id,
                    ),
                )
        else:
            conn.execute(
                "INSERT INTO model_providers (id, name, type, base_url, encrypted_api_key, enabled, config_json, created_at, updated_at) "
                "VALUES (?, ?, 'openai_compatible', ?, ?, ?, ?, ?, ?)",
                (
                    provider_id,
                    display_name,
                    normalized_base_url,
                    encrypted_key or "",
                    int(enabled),
                    next_config_json,
                    now,
                    now,
                ),
            )
        conn.commit()
    _sync_to_gateway()
    return get_provider(provider_id)


def delete_provider(provider_id: str) -> bool:
    """删除 provider"""
    _ensure_schema()
    db = Database()
    with db.transaction() as conn:
        existing = conn.execute(
            "SELECT id FROM model_providers WHERE id = ?", (provider_id,)
        ).fetchone()
        if not existing:
            return False
        conn.execute("DELETE FROM model_providers WHERE id = ?", (provider_id,))
        conn.commit()
    _sync_to_gateway()
    return True


def test_connection(provider_id: str) -> dict[str, Any]:
    """测试 provider 连接"""
    provider = get_provider(provider_id)
    if not provider:
        return {"success": False, "error": "Provider 不存在"}

    if not provider["api_key"]:
        return {"success": False, "error": "API Key 未配置"}
    if not provider["base_url"]:
        return {"success": False, "error": "Base URL 未配置"}
    try:
        safe_base_url = validate_custom_base_url(provider["base_url"])
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=provider["api_key"],
            base_url=safe_base_url,
            timeout=15.0,
        )
        models = client.models.list()
        model_items = [
            _model_config_item(
                str(getattr(m, "id", "") or "").strip(),
                str(getattr(m, "owned_by", "") or "").strip(),
            )
            for m in (models.data or [])[:10]
            if str(getattr(m, "id", "") or "").strip()
        ]
        model_ids = [item["id"] for item in model_items]
        generation_model = ""
        generation_preview = ""
        if model_ids:
            generation_candidates = _ranked_text_model_ids(model_ids) or model_ids
            generation_errors: list[str] = []
            for candidate_model in generation_candidates[:4]:
                try:
                    completion = client.chat.completions.create(
                        model=candidate_model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are a concise connectivity checker.",
                            },
                            {
                                "role": "user",
                                "content": "Reply with exactly: OK",
                            },
                        ],
                        max_tokens=16,
                        temperature=0,
                    )
                    content = completion.choices[0].message.content or ""
                    if content.strip():
                        generation_model = candidate_model
                        generation_preview = content.strip()[:80]
                        break
                    generation_errors.append(f"{candidate_model}: empty response")
                except Exception as exc:
                    generation_errors.append(f"{candidate_model}: {str(exc)[:120]}")

            if not generation_model:
                return {
                    "success": False,
                    "models": model_items,
                    "error": (
                        "模型列表可用，但真实生成测试失败；请检查该模型的调用权限、余额或默认模型。"
                        f" 最近错误: {'; '.join(generation_errors[-2:])}"
                    ),
                }

            try:
                existing = json.loads(provider.get("config_json") or "{}")
                if not isinstance(existing, dict):
                    existing = {}
            except Exception:
                existing = {}
            existing["models"] = model_items
            existing["default_model"] = generation_model or _preferred_model_id(
                model_ids
            )
            save_provider(
                provider_id=provider["id"],
                name=provider["name"],
                base_url=provider["base_url"],
                api_key="",
                enabled=provider.get("enabled", True),
                config_json=json.dumps(existing, ensure_ascii=False),
            )
        return {
            "success": True,
            "models": model_items,
            "generation_model": generation_model,
            "generation_preview": generation_preview,
            "message": f"连接成功，发现 {len(model_ids)} 个模型，生成测试通过: {generation_model}",
        }
    except Exception as e:
        return {"success": False, "error": f"连接失败: {e}"}


def export_settings() -> dict[str, Any]:
    """导出设置（脱敏）"""
    providers = list_providers()
    return {
        "version": "1.0",
        "preferences": get_app_preferences(),
        "providers": [
            {
                "id": p["id"],
                "name": p["name"],
                "base_url": p["base_url"],
                "api_key_masked": p["api_key_masked"],
                "enabled": p["enabled"],
            }
            for p in providers
        ],
    }


def import_settings(data: dict[str, Any]) -> dict[str, Any]:
    """导入设置（不含 API Key，需用户手动填写）"""
    providers = data.get("providers", [])
    imported = 0
    for p in providers:
        pid = p.get("id")
        if not pid:
            continue
        try:
            save_provider(
                provider_id=pid,
                name=p.get("name", pid),
                base_url=p.get("base_url", ""),
                api_key="",  # 导入不含 key
                enabled=p.get("enabled", True),
            )
        except ValueError as exc:
            logger.warning("跳过不安全 provider Base URL %s: %s", pid, exc)
            continue
        imported += 1
    if isinstance(data.get("preferences"), dict):
        save_app_preferences(data["preferences"])
    return {
        "imported": imported,
        "message": f"导入 {imported} 个 provider（需手动填写 API Key）",
    }


def _builtin_vendor_config(provider_id: str) -> dict[str, Any] | None:
    from backend.models import provider_gateway

    if provider_id == "deepseek":
        return {
            "api_key": os.getenv("DEEPSEEK_API_KEY"),
            "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            "supports_json_mode": True,
            "label": "DeepSeek",
        }
    if provider_id == "claude":
        return {
            "api_key": os.getenv("CLAUDE_API_KEY"),
            "base_url": (os.getenv("CLAUDE_BASE_URL", "") + "/v1")
            if os.getenv("CLAUDE_BASE_URL")
            else None,
            "supports_json_mode": False,
            "label": "Claude",
        }
    if provider_id == "gpt":
        return {
            "api_key": os.getenv("GPT_API_KEY"),
            "base_url": (os.getenv("GPT_BASE_URL", "") + "/v1")
            if os.getenv("GPT_BASE_URL")
            else None,
            "supports_json_mode": True,
            "label": "GPT",
        }
    if provider_id == "mimo":
        return {
            "api_key": os.getenv("MIMO_API_KEY"),
            "base_url": (os.getenv("MIMO_BASE_URL", "") + "/v1")
            if os.getenv("MIMO_BASE_URL")
            else None,
            "supports_json_mode": False,
            "label": "Mimo",
        }
    if provider_id == "sensenova":
        return {
            "api_key": os.getenv("SENSENOVA_API_KEY"),
            "base_url": os.getenv("SENSENOVA_BASE_URL"),
            "supports_json_mode": False,
            "label": "SenseNova",
        }
    if provider_id == "kimi":
        return {
            "api_key": os.getenv("KIMI_API_KEY"),
            "base_url": os.getenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1"),
            "supports_json_mode": True,
            "label": "Kimi",
        }
    config = provider_gateway._PROVIDER_CONFIG.get(provider_id)
    if config and config.get("api_key") and config.get("base_url"):
        return {
            "api_key": config.get("api_key"),
            "base_url": config.get("base_url"),
            "supports_json_mode": config.get("supports_json_mode", True),
            "label": config.get("label", provider_id),
            "models": config.get("models", {}),
        }
    return None


def _restore_builtin_vendor(provider_id: str, vendors: dict[str, Any]) -> None:
    builtin = _builtin_vendor_config(provider_id)
    if builtin and builtin.get("api_key") and builtin.get("base_url"):
        vendors[provider_id] = builtin
    else:
        vendors.pop(provider_id, None)


def _sync_to_gateway() -> None:
    """将 DB 配置同步到 provider_gateway 的 VENDORS dict"""
    try:
        from backend.models.provider_gateway import (
            KNOWN_PROVIDER_ORDER,
            VENDORS,
            _PROVIDER_CONFIG,
            _models_from_config_json,
            clear_client_cache,
            validate_custom_base_url,
        )

        providers = list_providers()
        provider_ids = {str(p.get("id") or "").strip() for p in providers}
        known_provider_ids = set(KNOWN_PROVIDER_ORDER) | set(_PROVIDER_CONFIG)
        for vendor_id in list(VENDORS.keys()):
            if vendor_id not in provider_ids and vendor_id not in known_provider_ids:
                VENDORS.pop(vendor_id, None)

        for provider_id in known_provider_ids:
            if provider_id not in provider_ids:
                _restore_builtin_vendor(provider_id, VENDORS)

        for p in providers:
            pid = p["id"]
            provider_full = get_provider(pid)
            if not provider_full:
                VENDORS.pop(pid, None)
                continue
            if not provider_full.get("enabled", True):
                _restore_builtin_vendor(pid, VENDORS)
                continue
            api_key = provider_full.get("api_key") or ""
            base_url = provider_full.get("base_url") or ""
            if not api_key or not base_url:
                if pid in known_provider_ids:
                    _restore_builtin_vendor(pid, VENDORS)
                else:
                    VENDORS.pop(pid, None)
                logger.warning(
                    "跳过未完整配置 provider %s: API Key 或 Base URL 缺失", pid
                )
                continue
            try:
                safe_base_url = validate_custom_base_url(base_url)
            except ValueError as exc:
                if pid in known_provider_ids:
                    _restore_builtin_vendor(pid, VENDORS)
                else:
                    VENDORS.pop(pid, None)
                logger.warning("跳过不安全 provider Base URL %s: %s", pid, exc)
                continue
            patch = {
                "api_key": api_key,
                "base_url": safe_base_url,
                "supports_json_mode": True,
                "label": p["name"],
                "config_json": provider_full.get("config_json") or "{}",
                "models": _models_from_config_json(provider_full.get("config_json")),
            }
            if pid in VENDORS:
                VENDORS[pid].update(patch)
            else:
                VENDORS[pid] = patch
        clear_client_cache()
    except Exception as e:
        logger.warning("同步设置到 gateway 失败: %s", e)
