"""研报质量门控 API — 把 M3 的确定性门控暴露为可调用接口。

对任意报告文本运行 :func:`backend.quality.report_gate.run_gate`,返回
critical/warning/info issues。纯新增,不改动既有功能。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/quality", tags=["quality"])


class ReportGateRequest(BaseModel):
    text: str = Field(default="", max_length=200_000, description="待检查的报告正文")
    evidence_chain: dict | None = Field(default=None, description="证据链(可选,evidence_chain.build 输出)")
    critic: dict | None = Field(default=None, description="LLM 审稿结果(可选)")
    mode: str | None = Field(default=None)


@router.post("/report-gate")
async def report_gate(req: ReportGateRequest):
    """对报告文本运行确定性质量门控,返回是否通过 + 各级 issues。"""
    from backend.quality.report_gate import run_gate

    result = run_gate(req.text, evidence_chain=req.evidence_chain, critic=req.critic, mode=req.mode)
    return ApiResponse(success=True, data=result)
