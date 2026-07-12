"""研报质量门控 API — 把 M3 的确定性门控暴露为可调用接口。

对任意报告文本运行 :func:`backend.quality.report_gate.run_gate`,返回
critical/warning/info issues。纯新增,不改动既有功能。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/quality", tags=["quality"])


class ReportGateRequest(BaseModel):
    text: str = Field(default="", max_length=200_000, description="待检查的报告正文")
    evidence_chain: dict | None = Field(default=None, description="证据链(可选,evidence_chain.build 输出)")
    critic: dict | None = Field(default=None, description="LLM 审稿结果(可选)")
    mode: str | None = Field(default=None)


class HistoricalCutoffRequest(BaseModel):
    as_of: date | None = Field(default=None, description="历史评测的统一数据截止日")

    @field_validator("as_of")
    @classmethod
    def reject_future_as_of(cls, value: date | None) -> date | None:
        if value and value > date.today():
            raise ValueError("历史评测截止日不能晚于今天")
        return value


class ResearchTrustRequest(HistoricalCutoffRequest):
    evidence: list[dict | str] = Field(default_factory=list, max_length=5_000)
    agents: dict | list[dict] | None = None
    contradictions: list[str] = Field(default_factory=list, max_length=1_000)
    missing_evidence: list[str] = Field(default_factory=list, max_length=1_000)


class ResearchCompareRequest(HistoricalCutoffRequest):
    baseline: dict = Field(default_factory=dict)
    candidate: dict = Field(default_factory=dict)


@router.post("/report-gate")
async def report_gate(req: ReportGateRequest):
    """对报告文本运行确定性质量门控,返回是否通过 + 各级 issues。"""
    from backend.quality.report_gate import run_gate

    result = run_gate(req.text, evidence_chain=req.evidence_chain, critic=req.critic, mode=req.mode)
    return ApiResponse(success=True, data=result)


@router.post("/research-trust")
async def research_trust(req: ResearchTrustRequest):
    """计算证据来源、日期、时效性、覆盖率与冲突组成的确定性可信度。"""
    from backend.quality.research_trust import assess_research_trust
    from backend.runtime.research_snapshot import as_of_timestamp

    result = assess_research_trust(
        req.evidence,
        agent_signals=req.agents,
        contradictions=req.contradictions,
        missing_evidence=req.missing_evidence,
        now=as_of_timestamp(req.as_of),
    )
    return ApiResponse(success=True, data=result)


@router.post("/research-compare")
async def research_compare(req: ResearchCompareRequest):
    """用同一机械评分卡比较单模型基线与候选研究工作流。"""
    from backend.quality.research_trust import compare_research_outputs
    from backend.runtime.research_snapshot import as_of_timestamp

    return ApiResponse(
        success=True,
        data=compare_research_outputs(req.baseline, req.candidate, now=as_of_timestamp(req.as_of)),
    )
