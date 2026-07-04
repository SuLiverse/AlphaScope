"""
Team Loader: 从 YAML 加载专家团配置。

职责：
- 加载 experts.yaml 中的团队定义
- 解析团队成员配置
- 提供团队列表和成员查询接口
"""

import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

try:
    from project_paths import CONFIG_DIR
except ImportError:
    from backend.project_paths import CONFIG_DIR

from backend.cache import get_cached

EXPERTS_YAML_PATH = CONFIG_DIR / "experts.yaml"


def _get_localized(value: Any, fallback: str = "") -> str:
    """从可能的多语言 dict 中提取中文值"""
    if isinstance(value, dict):
        return value.get("zh", value.get("en", fallback))
    return str(value) if value else fallback


@dataclass
class ExpertMember:
    """单个专家成员配置"""

    id: str
    name: str
    name_en: str = ""
    profession: str = ""
    profession_en: str = ""
    role: str = "member"
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    prompt_file: str = ""
    focus_dims: List[str] = field(default_factory=list)
    stop_loss_style: str = ""
    output_schema: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class ExpertTeam:
    """专家团配置"""

    id: str
    name: str
    name_en: str = ""
    description: str = ""
    avatar: str = ""
    prompt_file: str = ""
    output_schema: str = ""
    members: List[ExpertMember] = field(default_factory=list)
    workflow: str = "parallel_then_debate"
    max_rounds: int = 2
    require_citations: bool = True
    require_risk_review: bool = True


def _load_teams_from_disk(config_path: Optional[str] = None) -> Dict[str, ExpertTeam]:
    """从磁盘加载专家团配置（内部函数，无缓存）"""
    p = Path(config_path) if config_path else EXPERTS_YAML_PATH
    if not p.exists():
        return {}
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}

    teams = {}
    for team_raw in raw.get("teams", []):
        team_id = team_raw.get("id", "")
        if not team_id:
            continue

        members = []
        for m in team_raw.get("members", []):
            members.append(
                ExpertMember(
                    id=m.get("id", ""),
                    name=_get_localized(m.get("displayName", ""), m.get("id", "")),
                    name_en=m.get("displayName", {}).get("en", "") if isinstance(m.get("displayName"), dict) else "",
                    profession=_get_localized(m.get("profession", "")),
                    profession_en=m.get("profession", {}).get("en", "")
                    if isinstance(m.get("profession"), dict)
                    else "",
                    role=m.get("role", "member"),
                    provider=m.get("provider", "deepseek"),
                    model=m.get("model", "deepseek-chat"),
                    prompt_file=m.get("promptFile", ""),
                    focus_dims=m.get("focusDims", []),
                    stop_loss_style=m.get("stopLossStyle", ""),
                    enabled=m.get("enabled", True),
                )
            )

        desc_raw = team_raw.get("description", "")
        desc = _get_localized(desc_raw)

        teams[team_id] = ExpertTeam(
            id=team_id,
            name=_get_localized(team_raw.get("displayName", ""), team_id),
            name_en=team_raw.get("displayName", {}).get("en", "")
            if isinstance(team_raw.get("displayName"), dict)
            else "",
            description=desc,
            avatar=team_raw.get("avatar", ""),
            prompt_file=team_raw.get("promptFile", ""),
            output_schema=team_raw.get("outputSchema", ""),
            members=members,
        )
    return teams


def load_teams(config_path: Optional[str] = None) -> Dict[str, ExpertTeam]:
    """从 experts.yaml 的 teams 段加载所有专家团配置（带缓存）"""
    if config_path is not None:
        return _load_teams_from_disk(config_path)
    return get_cached("teams:all", lambda: _load_teams_from_disk(), ttl_seconds=60)


def get_team(team_id: str, config_path: Optional[str] = None) -> Optional[ExpertTeam]:
    """获取指定专家团配置"""
    teams = load_teams(config_path)
    return teams.get(team_id)


def list_team_names(config_path: Optional[str] = None) -> List[Dict[str, str]]:
    """返回所有团队的 id/name 列表，供 UI 选择"""
    teams = load_teams(config_path)
    return [{"id": t.id, "name": t.name, "name_en": t.name_en} for t in teams.values()]
