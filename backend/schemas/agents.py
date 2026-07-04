"""Agent/专家团统一配置模型

将分散在 agents/base.py、expert_panel.py、teams/team_loader.py 中的
重复数据结构统一为单一 Pydantic schema 层。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ============================================================
# 工作流模式
# ============================================================


class WorkflowMode(str, Enum):
    """专家团工作流模式"""

    SINGLE_AGENT = "single_agent"
    PARALLEL_EXPERTS = "parallel_experts"
    DEBATE = "debate"
    ROUNDTABLE = "roundtable"
    DEVILS_ADVOCATE = "devils_advocate"
    CHAIRMAN_RULING = "chairman_ruling"


# ============================================================
# 工具权限
# ============================================================


class ToolPermission(BaseModel):
    """工具权限配置"""

    name: str = Field(description="工具名称")
    tool_type: str = Field(description="工具类型: data_source/rag/search/crawler")
    provider: str = Field(default="", description="数据供应商")
    enabled: bool = Field(default=True, description="是否启用")
    rate_limit: str = Field(default="", description="速率限制，如 60/min")
    max_results: int = Field(default=10, description="最大结果数")


# ============================================================
# 模型配置
# ============================================================


class ModelConfig(BaseModel):
    """单个模型配置"""

    provider: str = Field(description="供应商ID: deepseek/claude/gpt/sensenova/mimo")
    model: str = Field(description="模型名称")
    api_key: str = Field(default="", description="API Key")
    base_url: str = Field(default="", description="自定义 Base URL")
    max_tokens: int = Field(default=600, description="最大输出 token 数")
    temperature: float = Field(default=0.3, description="温度")


class FallbackConfig(BaseModel):
    """降级配置"""

    provider: str = Field(default="deepseek", description="降级供应商")
    model: str = Field(default="deepseek-chat", description="降级模型")


# ============================================================
# Agent 配置
# ============================================================


class AgentConfig(BaseModel):
    """单个 Agent 配置"""

    key: str = Field(description="Agent 唯一标识，如 fundamental/technical/sentiment")
    name: str = Field(description="显示名称")
    role: str = Field(default="analyst", description="角色: analyst/critic/chairman/expert")
    instruction: str = Field(default="", description="系统提示词")
    provider: str = Field(default="deepseek", description="LLM 供应商")
    model: str = Field(default="deepseek-chat", description="模型名称")
    api_key: str = Field(default="", description="API Key（空则继承全局）")
    base_url: str = Field(default="", description="自定义 Base URL")
    inherit_global_key: bool = Field(default=True, description="是否继承全局 Key")
    enabled: bool = Field(default=True, description="是否启用")
    avatar: str = Field(default="", description="头像标识")
    card_style: str = Field(default="default", description="卡片样式")
    focus_dims: list[str] = Field(default_factory=list, description="关注维度")
    stop_loss_style: str = Field(default="", description="止损风格")
    output_schema: dict[str, Any] = Field(default_factory=dict, description="输出 JSON schema")


# ============================================================
# 专家团配置
# ============================================================


class ExpertMemberConfig(BaseModel):
    """专家团成员配置"""

    id: str = Field(description="成员ID")
    name: str = Field(description="显示名称（中文）")
    name_en: str = Field(default="", description="显示名称（英文）")
    profession: str = Field(default="", description="专业领域（中文）")
    profession_en: str = Field(default="", description="专业领域（英文）")
    role: str = Field(default="member", description="角色: lead/member")
    provider: str = Field(default="deepseek", description="LLM 供应商")
    model: str = Field(default="deepseek-chat", description="模型名称")
    api_key: str = Field(default="", description="API Key")
    base_url: str = Field(default="", description="自定义 Base URL")
    inherit_global_key: bool = Field(default=True, description="是否继承全局 Key")
    enabled: bool = Field(default=True, description="是否启用")
    avatar: str = Field(default="", description="头像标识")
    card_style: str = Field(default="default", description="卡片样式")
    prompt_file: str = Field(default="", description="提示词文件路径")
    system_prompt: str = Field(default="", description="系统提示词（内联）")
    focus_dims: list[str] = Field(default_factory=list, description="关注维度")
    stop_loss_style: str = Field(default="", description="止损风格")


class TeamConfig(BaseModel):
    """专家团配置"""

    id: str = Field(description="团队ID")
    name: str = Field(description="团队名称（中文）")
    name_en: str = Field(default="", description="团队名称（英文）")
    description: str = Field(default="", description="团队描述")
    avatar: str = Field(default="", description="头像标识")
    workflow: WorkflowMode = Field(default=WorkflowMode.PARALLEL_EXPERTS, description="工作流模式")
    max_rounds: int = Field(default=2, description="辩论最大轮次")
    require_citations: bool = Field(default=True, description="要求引用来源")
    require_risk_review: bool = Field(default=True, description="要求风控审核")
    enable_critic: bool = Field(default=True, description="启用 Critic")
    enable_chairman: bool = Field(default=True, description="启用 Chairman")
    members: list[ExpertMemberConfig] = Field(default_factory=list, description="成员列表")
    output_schema: dict[str, Any] = Field(default_factory=dict, description="输出 JSON schema")


# ============================================================
# 分析输出结构
# ============================================================


class AgentOutput(BaseModel):
    """Agent 分析输出"""

    signal: str = Field(default="观望", description="信号: 买入/卖出/观望")
    confidence: float = Field(default=50.0, description="置信度 0-100")
    reason: str = Field(default="无明确观点", description="分析理由")
    evidence: list[dict[str, Any]] = Field(default_factory=list, description="证据列表")
    invalid_if: str = Field(default="", description="失效条件")
    risks: list[str] = Field(default_factory=list, description="风险因素")


class ExpertOutput(BaseModel):
    """专家分析输出"""

    view: str = Field(default="", description="观点摘要")
    action: str = Field(default="观望", description="操作: 买入/卖出/观望/减持")
    position: int = Field(default=0, ge=0, le=100, description="建议仓位 0-100")
    stop_loss: float = Field(default=0.0, description="止损价")
    evidence: list[dict[str, Any]] = Field(default_factory=list, description="证据列表")
    invalid_if: str = Field(default="", description="失效条件")
    risks: list[str] = Field(default_factory=list, description="风险因素")


class AnalysisSummary(BaseModel):
    """分析汇总"""

    final: str = Field(default="观望", description="最终建议")
    buy: int = Field(default=0, description="买入票数")
    sell: int = Field(default=0, description="卖出票数")
    hold: int = Field(default=0, description="观望建议数")
    reduce: int = Field(default=0, description="减持票数")
    avg_confidence: float = Field(default=0.0, description="平均置信度")
    total_agents: int = Field(default=0, description="参与 Agent 数")
    score: float = Field(default=50.0, ge=0, le=100, description="确定性评级评分 0-100")
    rating: str = Field(default="中性", description="五档评级: 强烈推荐/推荐/中性/谨慎/回避")
    rating_breakdown: dict[str, Any] = Field(default_factory=dict, description="评分可审计明细(W/D/raw/conf_factor 等)")
