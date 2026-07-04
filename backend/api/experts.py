"""投资人库 API — 列出 config/experts.yaml 中的投资人 persona(只读)。

供前端"投资人面板"展示。纯新增,不改动既有功能。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.schemas.api import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/experts", tags=["experts"])


@router.get("")
def list_experts():
    """列出投资人 persona(id/名称/风格/图标/关注维度/理念预览)。"""
    import yaml

    from backend.expert_panel import EXPERTS_YAML_PATH

    try:
        data = yaml.safe_load(EXPERTS_YAML_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[experts] 读取 experts.yaml 失败: %s", exc)
        return ApiResponse(success=True, data={"experts": [], "total": 0})

    experts = []
    for e in data.get("experts") or []:
        prompt = str(e.get("system_prompt") or "").strip()
        preview = (prompt[:160] + "…") if len(prompt) > 160 else prompt
        experts.append(
            {
                "id": e.get("key"),
                "name": e.get("name"),
                "style": e.get("style"),
                "icon": e.get("icon"),
                "focus_dims": e.get("focus_dims") or [],
                "preview": preview,
                "model": e.get("preferred_model"),
            }
        )

    return ApiResponse(success=True, data={"experts": experts, "total": len(experts)})


class TeamFromPersonasRequest(BaseModel):
    member_ids: list[str] = Field(default_factory=list, description="投资人 persona key 列表")
    name: str = Field(default="自定义投资人团", max_length=60)


@router.post("/team")
def create_team_from_personas(req: TeamFromPersonasRequest):
    """用选中的投资人 persona 组建一个真实专家团:
    先把每位 persona 登记为 agent(upsert 到 agent_configs),再创建团队。
    这样 persona 才能作为有效团队成员被「多Agent网络」运行。
    """
    import time

    import yaml

    from backend.agent_store import save_agent, save_team
    from backend.expert_panel import EXPERTS_YAML_PATH

    try:
        data = yaml.safe_load(EXPERTS_YAML_PATH.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[experts] 读取 experts.yaml 失败: %s", exc)
        return ApiResponse(success=False, error="读取投资人配置失败", error_code="EXPERTS_READ_FAILED")

    by_key = {e.get("key"): e for e in (data.get("experts") or []) if e.get("key")}
    valid_ids: list[str] = []
    for key in req.member_ids[:30]:
        e = by_key.get(key)
        if not e:
            continue  # 跳过无效 persona,避免悬空成员
        save_agent(
            agent_id=key,
            name=e.get("name") or key,
            description=e.get("style") or "",
            system_prompt=str(e.get("system_prompt") or ""),
            provider=e.get("preferred_vendor") or "deepseek",
            model=e.get("preferred_model") or "deepseek-chat",
        )
        valid_ids.append(key)

    if not valid_ids:
        return ApiResponse(success=False, error="没有有效的投资人", error_code="NO_VALID_PERSONAS")

    team_id = f"persona-team-{int(time.time())}"
    team = save_team(
        team_id=team_id,
        name=req.name,
        description=f"由投资人库组建({len(valid_ids)} 位)",
        member_ids=valid_ids,
    )
    return ApiResponse(success=True, data={"team": team, "team_id": team_id, "members": valid_ids})
