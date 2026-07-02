"""Agent/专家团管理 API — CRUD 端点"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/manage", tags=["manage"])


# ============== Request Models ==============


class AgentSaveRequest(BaseModel):
    id: str = Field(description="Agent ID")
    name: str = Field(description="显示名称")
    description: str = Field(default="", description="描述")
    system_prompt: str = Field(default="", description="系统提示词")
    provider: str = Field(default="deepseek", description="模型供应商")
    model: str = Field(default="deepseek-chat", description="模型名称")
    tools: list[str] = Field(default_factory=list, description="工具列表")
    temperature: float = Field(default=0.3, description="温度")
    max_tokens: int = Field(default=2048, description="最大 token")
    enabled: bool = Field(default=True, description="是否启用")


class TeamSaveRequest(BaseModel):
    id: str = Field(description="专家团 ID")
    name: str = Field(description="显示名称")
    description: str = Field(default="", description="描述")
    member_ids: list[str] = Field(
        default_factory=list, description="成员 Agent ID 列表"
    )


# ============== Agent Endpoints ==============


@router.get("/agents")
async def list_agents():
    """Agent 列表"""
    from backend.agent_store import list_agents as _list

    return ApiResponse(success=True, data={"agents": _list()})


@router.post("/agents")
async def save_agent(req: AgentSaveRequest):
    """创建/更新 Agent"""
    from backend.agent_store import save_agent as _save

    result = _save(
        agent_id=req.id,
        name=req.name,
        description=req.description,
        system_prompt=req.system_prompt,
        provider=req.provider,
        model=req.model,
        tools=req.tools,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        enabled=req.enabled,
    )
    return ApiResponse(success=True, data=result)


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """删除 Agent"""
    from backend.agent_store import delete_agent as _delete

    deleted = _delete(agent_id)
    if not deleted:
        return ApiResponse(success=False, error="Agent 不存在")
    return ApiResponse(success=True, data={"deleted": agent_id})


# ============== Team Endpoints ==============


@router.get("/teams")
async def list_teams():
    """专家团列表"""
    from backend.agent_store import list_teams as _list

    return ApiResponse(success=True, data={"teams": _list()})


@router.post("/teams")
async def save_team(req: TeamSaveRequest):
    """创建/更新专家团"""
    from backend.agent_store import save_team as _save

    result = _save(
        team_id=req.id,
        name=req.name,
        description=req.description,
        member_ids=req.member_ids,
    )
    return ApiResponse(success=True, data=result)


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str):
    """删除专家团"""
    from backend.agent_store import delete_team as _delete

    deleted = _delete(team_id)
    if not deleted:
        return ApiResponse(success=False, error="专家团不存在")
    return ApiResponse(success=True, data={"deleted": team_id})
