"""视觉分析 API — K线图分析 + 结构化报告"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.provider_timeout import call_with_timeout
from backend.schemas.api import ApiResponse

router = APIRouter(prefix="/api/vision", tags=["vision"])

VISION_ANALYSIS_TIMEOUT_SECONDS = 25.0


class VisionAnalyzeRequest(BaseModel):
    image_base64: str = Field(max_length=28 * 1024 * 1024, description="图片 base64 编码")
    mime_type: str = Field(default="image/png", max_length=80, description="MIME 类型")
    user_context: str = Field(default="", max_length=10_000, description="用户上下文")
    vendor: str = Field(default="deepseek", max_length=80, description="视觉模型供应商")
    model: str = Field(default="deepseek-chat", max_length=160, description="模型名称")
    ticker: str = Field(default="", max_length=32, description="股票代码（可选）")


@router.post("/analyze")
async def analyze_vision(req: VisionAnalyzeRequest):
    """分析K线图/金融图片"""
    from backend.vision.vision_agent import analyze_image

    try:
        result = await asyncio.to_thread(
            call_with_timeout,
            lambda: analyze_image(
                image_base64=req.image_base64,
                mime_type=req.mime_type,
                user_context=req.user_context,
                vendor=req.vendor,
                model=req.model,
                ticker=req.ticker,
            ),
            VISION_ANALYSIS_TIMEOUT_SECONDS,
            name="vision-analysis",
        )
    except TimeoutError as exc:
        return ApiResponse(
            success=False,
            data={"degraded": True, "source_status": "timeout"},
            error=f"视觉分析超时: {exc}",
            error_code="VISION_ANALYSIS_TIMEOUT",
        )

    # 构建响应
    data = {
        "analysis": result.summary,
        "ticker": result.detection.ticker if result.detection else "",
        "ticker_name": result.detection.ticker_name if result.detection else "",
        "chart_type": result.detection.chart_type if result.detection else "",
        "period": result.detection.period if result.detection else "",
        "is_chart": result.detection.is_chart if result.detection else False,
        "needs_more_info": result.needs_more_info,
        "missing_info": result.missing_info,
    }

    if result.real_data and result.real_data.data_available:
        data["real_data"] = {
            "latest_close": result.real_data.latest_close,
            "real_trend": result.real_data.real_trend,
            "trend_consistent": result.real_data.trend_consistent,
            "conflicts": result.real_data.conflicts,
            "data_source": result.real_data.data_source,
        }

    if result.kline_analysis:
        data["kline"] = {
            "trend": result.kline_analysis.trend,
            "support_levels": result.kline_analysis.support_levels,
            "resistance_levels": result.kline_analysis.resistance_levels,
            "patterns": result.kline_analysis.patterns,
            "summary": result.kline_analysis.summary,
        }

    return ApiResponse(success=result.ok, data=data)


@router.post("/report")
async def generate_report(req: VisionAnalyzeRequest):
    """生成结构化视觉分析报告"""
    from backend.vision.vision_agent import analyze_image
    from backend.vision.report_generator import generate_vision_report

    try:
        result = await asyncio.to_thread(
            call_with_timeout,
            lambda: analyze_image(
                image_base64=req.image_base64,
                mime_type=req.mime_type,
                user_context=req.user_context,
                vendor=req.vendor,
                model=req.model,
                ticker=req.ticker,
            ),
            VISION_ANALYSIS_TIMEOUT_SECONDS,
            name="vision-report",
        )
    except TimeoutError as exc:
        return ApiResponse(
            success=False,
            data={
                "report": "视觉分析超时，请稍后重试或缩小图片后再试。",
                "ticker": "",
                "is_chart": False,
                "degraded": True,
                "source_status": "timeout",
            },
            error=f"视觉分析超时: {exc}",
            error_code="VISION_ANALYSIS_TIMEOUT",
        )

    report = generate_vision_report(result)

    return ApiResponse(
        success=result.ok,
        data={
            "report": report,
            "ticker": result.detection.ticker if result.detection else "",
            "is_chart": result.detection.is_chart if result.detection else False,
        },
    )
