"""数据源配置与凭证管理。

职责:
- 维护付费/自定义数据源的 API Key (AES-GCM 加密存 SQLite, 复用 key_vault)
- 维护各数据源的启停/优先级 (落盘到 config/data_sources.yaml, 热重载 registry)
- 提供预置付费数据源目录 (Tushare / Choice / iFinD / 聚宽 等, 含官网与说明)

设计原则: 不改动各 Provider 的取 key 方式 (它们读 os.environ),
保存凭证时把明文 key 注入对应 token_env 环境变量, 再 reload registry,
即可让 "填 key → 立即生效" 无需改动任何 provider 代码。
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

import yaml

from backend.security.key_vault import decrypt_key, encrypt_key, mask_key
from backend.storage.db import Database

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config" / "data_sources.yaml"

# ruamel round-trip YAML (保留注释与顺序); 不可用时回退 PyYAML
try:
    from ruamel.yaml import YAML

    _HAS_RUAMEL = True
except ImportError:
    _HAS_RUAMEL = False

# 数据源凭证表 (与 model_providers 同库, 独立表)
_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS datasource_credentials (
    name TEXT PRIMARY KEY,
    token_env TEXT,
    encrypted_key TEXT,
    config_json TEXT DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""

# 预置付费/商业数据源目录 — 用户可一键跳转官网获取 Key
# fields: name, label, types(数据类型), cost_tier, token_env, signup_url,
#         doc_url, description, advantages
PRESET_DATASOURCES: list[dict[str, Any]] = [
    {
        "name": "tushare",
        "label": "Tushare Pro",
        "types": ["prices", "fundamentals", "reports", "announcements", "fund_flow"],
        "cost_tier": "freemium",
        "token_env": "TUSHARE_TOKEN",
        "signup_url": "https://tushare.pro/register?reg=7",
        "doc_url": "https://tushare.pro/document/2",
        "description": "A股最全准专业数据, 积分制, 免费额度可用, 高频/财务/资金全覆盖。",
        "advantages": "行情/财务/研报/公告/资金流一体; 积分越高权限越大; 数据稳定, 适合量化回测与基本面研究。",
    },
    {
        "name": "choice",
        "label": "Choice（东方财富）",
        "types": ["prices", "fundamentals", "reports", "announcements", "fund_flow"],
        "cost_tier": "paid",
        "token_env": "CHOICE_TOKEN",
        "signup_url": "https://choice.eastmoney.com/",
        "doc_url": "https://choice.eastmoney.com/openapi",
        "description": "东财全量金融数据 API, 行情/财务/资金/研报, 机构级覆盖。",
        "advantages": "A股+港股+美股行情; 主力资金与Level-2; 财务数据库深; 与东财终端一致。",
    },
    {
        "name": "ifind",
        "label": "同花顺 iFinD",
        "types": ["prices", "fundamentals", "reports", "announcements"],
        "cost_tier": "paid",
        "token_env": "IFIND_TOKEN",
        "signup_url": "https://dict.10jqka.com.cn/",
        "doc_url": "https://platform.10jqka.com.cn/",
        "description": "同花顺机构版数据, 研报/财务/行情, 需申请授权码。",
        "advantages": "研报库丰富; 产业链与主题数据; 财务指标口径全; 适合深度基本面。",
    },
    {
        "name": "jqdata",
        "label": "聚宽 JQData",
        "types": ["prices", "fundamentals", "factors"],
        "cost_tier": "freemium",
        "token_env": "JQDATA_TOKEN",
        "signup_url": "https://www.joinquant.com/",
        "doc_url": "https://www.joinquant.com/help/api/help",
        "description": "聚宽数据服务, 行情/财务/因子, token 制, 免费额度可用。",
        "advantages": "因子库与 barra 风险模型; 历史行情回测友好; 财务衍生指标全; 适合多因子研究。",
    },
    {
        "name": "wind",
        "label": "Wind 万得",
        "types": [
            "prices",
            "fundamentals",
            "reports",
            "announcements",
            "fund_flow",
            "macro",
        ],
        "cost_tier": "paid",
        "token_env": "WIND_TOKEN",
        "signup_url": "https://www.wind.com.cn/",
        "doc_url": "https://www.wind.com.cn/newedeber/datahub.html",
        "description": "机构全量数据, 需企业授权, 个人暂不可直接申请。",
        "advantages": "最全最权威; 覆盖全球多资产; 宏观与行业链最深; 机构标配。",
    },
    {
        "name": "finnhub",
        "label": "Finnhub（美股/全球）",
        "types": ["news", "sentiment", "insider", "esg", "calendar"],
        "cost_tier": "freemium",
        "token_env": "FINNHUB_TOKEN",
        "signup_url": "https://finnhub.io/register",
        "doc_url": "https://finnhub.io/docs/api",
        "description": "美股/全球新闻、情绪、内部人交易、ESG, 免费额度可用。",
        "advantages": "实时新闻与情绪; 内部人交易数据; ESG与公司日历; 全球标的覆盖。",
    },
    {
        "name": "alpha_vantage",
        "label": "Alpha Vantage（全球行情）",
        "types": ["prices", "fundamentals"],
        "cost_tier": "freemium",
        "token_env": "ALPHAVANTAGE_TOKEN",
        "signup_url": "https://www.alphavantage.co/support/#api-key",
        "doc_url": "https://www.alphavantage.co/documentation/",
        "description": "全球股票/外汇/加密行情与基本面, 免费额度可用。",
        "advantages": "全球多市场行情; 技术指标库丰富; 免费层够用; 接入简单。",
    },
]

_PRESET_BY_NAME = {d["name"]: d for d in PRESET_DATASOURCES}


def _db() -> Database:
    return Database()


_schema_ensured = False


def _ensure_table() -> None:
    """建表(幂等)。包进进程级 DB 锁。首次建表后置 flag 跳过(provider 启动读凭证高频调)。"""
    global _schema_ensured
    if _schema_ensured:
        return
    with _db().transaction() as conn:
        conn.execute(_TABLE_SQL)
        conn.commit()
    _schema_ensured = True


def list_presets() -> list[dict[str, Any]]:
    """预置付费数据源目录 (含当前 key 是否已配置、是否已启用)。"""
    _ensure_table()
    creds = _list_credentials_map()
    config = _load_yaml()
    out: list[dict[str, Any]] = []
    for p in PRESET_DATASOURCES:
        name = p["name"]
        cred = creds.get(name)
        enabled = _is_enabled_in_config(config, name)
        out.append(
            {
                "name": name,
                "label": p["label"],
                "types": p["types"],
                "cost_tier": p["cost_tier"],
                "token_env": p["token_env"],
                "signup_url": p["signup_url"],
                "doc_url": p.get("doc_url"),
                "description": p["description"],
                "advantages": p["advantages"],
                "has_key": cred is not None,
                "key_masked": cred.get("key_masked") if cred else None,
                "enabled": enabled,
            }
        )
    return out


def _list_credentials_map() -> dict[str, dict[str, Any]]:
    with _db().transaction() as conn:
        rows = conn.execute(
            "SELECT name, token_env, encrypted_key, config_json, updated_at FROM datasource_credentials"
        ).fetchall()
    # 解密在锁外做(不占 DB 锁)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        name, token_env, encrypted_key, config_json, updated_at = r
        try:
            plain = decrypt_key(encrypted_key or "")
        except Exception:
            plain = ""
        out[name] = {
            "token_env": token_env,
            "key_masked": mask_key(plain) if plain else None,
            "config_json": config_json or "{}",
            "updated_at": updated_at,
        }
    return out


def get_credential(name: str) -> Optional[dict[str, Any]]:
    """获取某数据源凭证 (含明文 key, 仅供后端注入用; API 层不直接返回明文)。"""
    _ensure_table()
    with _db().transaction() as conn:
        row = conn.execute(
            "SELECT name, token_env, encrypted_key, config_json FROM datasource_credentials WHERE name=?",
            (name,),
        ).fetchone()
    if not row:
        return None
    name, token_env, encrypted_key, config_json = row
    try:
        plain = decrypt_key(encrypted_key or "")
    except Exception:
        plain = ""
    return {
        "name": name,
        "token_env": token_env,
        "api_key": plain,
        "config_json": config_json or "{}",
    }


def save_credential(
    name: str, api_key: str, token_env: Optional[str] = None
) -> dict[str, Any]:
    """保存数据源 API Key (加密落盘) 并立即注入环境变量 + 热重载 registry。"""
    _ensure_table()
    preset = _PRESET_BY_NAME.get(name)
    env = (
        token_env
        or (preset["token_env"] if preset else None)
        or f"{name.upper()}_TOKEN"
    )
    now = time.time()
    encrypted = encrypt_key(api_key) if api_key else ""
    # existing 查询 + INSERT/UPDATE 在同一事务内(原子性); _reload_registry 不碰 DB,
    # 但为稳妥放在锁外。
    with _db().transaction() as conn:
        existing = conn.execute(
            "SELECT name FROM datasource_credentials WHERE name=?", (name,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE datasource_credentials SET token_env=?, encrypted_key=?, updated_at=? WHERE name=?",
                (env, encrypted, now, name),
            )
        else:
            conn.execute(
                "INSERT INTO datasource_credentials (name, token_env, encrypted_key, config_json, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (name, env, encrypted, "{}", now, now),
            )
        conn.commit()
    # 立即注入环境变量, 让 provider 重新实例化时能读到
    if api_key:
        os.environ[env] = api_key
    # 热重载 registry, 让带 key 的 provider 立即注册生效
    _reload_registry()
    logger.info("数据源 %s 凭证已保存并热重载 (env=%s)", name, env)
    return {
        "name": name,
        "token_env": env,
        "key_masked": mask_key(api_key) if api_key else None,
    }


def delete_credential(name: str) -> bool:
    _ensure_table()
    with _db().transaction() as conn:
        cur = conn.execute("DELETE FROM datasource_credentials WHERE name=?", (name,))
        conn.commit()
        rowcount = cur.rowcount
    # 清掉环境变量并重载 (provider 将因无 key 而不可用)
    preset = _PRESET_BY_NAME.get(name)
    env = preset["token_env"] if preset else f"{name.upper()}_TOKEN"
    os.environ.pop(env, None)
    _reload_registry()
    return rowcount > 0


# ---------------- 权重 / 启停 (落盘 yaml, 保留注释) ----------------


def _load_yaml():
    """加载 YAML 为 ruamel CommentedMap (保留注释/顺序); 不可用时回退 PyYAML dict。"""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            if _HAS_RUAMEL:
                return YAML().load(f) or {}
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("读取数据源配置失败: %s", e)
        return {}


def _save_yaml(config) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        if _HAS_RUAMEL:
            YAML().dump(config, f)
        else:
            yaml.safe_dump(
                config, f, allow_unicode=True, sort_keys=False, default_flow_style=False
            )


# data_type (provider.data_types 用的复数形式) -> yaml 里的 _providers 键名 (单数)
# 因为 data_sources.yaml 用 price/announcement/report 等单数, 而 provider.data_types 用复数
_DATA_TYPE_TO_YAML_KEY: dict[str, str] = {
    "prices": "price",
    "announcements": "announcement",
    "reports": "report",
    # 以下单复数一致 (data_type 直接作为 yaml 键)
    "news": "news",
    "us": "us",
    "hk": "hk",
    "macro": "macro",
    "sentiment": "sentiment",
    "fundamentals": "fundamentals",
    "fund_flow": "fund_flow",
    "dragon_tiger": "dragon_tiger",
    "events": "events",
    "insider": "insider",
    "esg": "esg",
    "calendar": "calendar",
    "interest_rate": "interest_rate",
    "gdp": "gdp",
    "cpi": "cpi",
    "employment": "employment",
    "housing": "housing",
    "alternative": "alternative",
}


def _yaml_key_for(data_type: str) -> str:
    """data_type -> yaml 的 {key}_providers 中 key 部分。"""
    return _DATA_TYPE_TO_YAML_KEY.get(data_type, data_type)


def _section_key(data_type: str) -> str:
    """完整的 yaml 键, 如 price_providers。"""
    return f"{_yaml_key_for(data_type)}_providers"


def _is_enabled_in_config(config, provider_name: str) -> bool:
    """任一 data_type 下该 provider enabled 即视为启用 (默认 true)。"""
    for key, val in config.items() if hasattr(config, "items") else []:
        if key.endswith("_providers") and isinstance(val, dict):
            entry = val.get(provider_name)
            if isinstance(entry, dict) and entry.get("enabled") is False:
                continue
            if entry is not None:
                return entry.get("enabled", True) if isinstance(entry, dict) else True
    return True


def get_config_summary() -> dict[str, Any]:
    """返回所有数据源在所有 data_type 下的优先级/启停 (供前端编辑)。"""
    config = _load_yaml()
    # 反向映射: yaml 单数键 -> data_type 复数
    yaml_to_dtype = {v: k for k, v in _DATA_TYPE_TO_YAML_KEY.items()}
    summary: dict[str, Any] = {}
    for key, val in config.items() if hasattr(config, "items") else []:
        if key.endswith("_providers") and isinstance(val, dict):
            short = key.replace("_providers", "")
            dtype = yaml_to_dtype.get(short, short)  # 默认用单数键本身
            for pname, pconf in val.items():
                pconf = pconf if isinstance(pconf, dict) else {}
                summary.setdefault(pname, {})[dtype] = {
                    "enabled": pconf.get("enabled", True),
                    "priority": pconf.get("priority", 0),
                }
    return summary


def update_provider_config(
    provider_name: str,
    data_type: str,
    enabled: Optional[bool] = None,
    priority: Optional[int] = None,
) -> dict[str, Any]:
    """更新某 provider 在某 data_type 下的启停/优先级, 落盘 (保留注释) + 热重载。"""
    config = _load_yaml()
    if not config:
        config = {}
    key = _section_key(data_type)  # data_type 复数 -> yaml 单数键
    if key not in config:
        config[key] = {}
    section = config[key]
    if provider_name not in section:
        section[provider_name] = {}
    entry = section[provider_name]
    if not isinstance(entry, dict):
        entry = {}
        section[provider_name] = entry
    if enabled is not None:
        entry["enabled"] = bool(enabled)
    if priority is not None:
        entry["priority"] = max(0, min(100, int(priority)))
    _save_yaml(config)
    _reload_registry()
    logger.info(
        "数据源 %s.%s 配置已更新 (enabled=%s, priority=%s) 并热重载",
        provider_name,
        data_type,
        enabled,
        priority,
    )
    return {
        "provider": provider_name,
        "data_type": data_type,
        "enabled": entry.get("enabled", True),
        "priority": entry.get("priority", 0),
    }


# ---------------- registry 热重载 ----------------


def _reload_registry() -> None:
    try:
        from backend.providers.registry import get_registry

        get_registry().reload()
    except Exception as e:
        logger.warning("registry 热重载失败: %s", e)


def init_credentials_on_startup() -> None:
    """启动时把已保存的数据源 key 注入环境变量, 使 provider 自动注册时可用。"""
    try:
        _ensure_table()
        creds = _list_credentials_map()
        for name, cred in creds.items():
            env = cred.get("token_env")
            if not env:
                continue
            # 需要明文, 重新解密
            full = get_credential(name)
            if full and full.get("api_key"):
                os.environ[env] = full["api_key"]
                logger.info("已注入数据源凭证环境变量: %s (%s)", name, env)
    except Exception as e:
        logger.warning("启动注入数据源凭证失败: %s", e)
